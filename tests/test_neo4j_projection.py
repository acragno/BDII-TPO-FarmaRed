from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.loaders.neo4j_projection import (
    CONSTRAINTS,
    NODE_SPECS,
    ProjectionError,
    _node_properties,
    _relationship_rows,
    _verify_counts,
    build_projection,
)


def _source() -> dict[str, list[dict]]:
    return {
        "clientes": [
            {"_id": "C1", "id_cliente": "C1", "nombre": "Ana", "activo": True}
        ],
        "sucursales": [
            {"_id": "S1", "id_sucursal": "S1", "nombre": "Centro"}
        ],
        "farmaceuticos": [
            {"_id": "F1", "id_farmaceutico": "F1", "id_sucursal": "S1"}
        ],
        "productos": [{"_id": "P1", "id_producto": "P1", "nombre": "Ibuprofeno"}],
        "recetas": [
            {
                "_id": "R1",
                "id_receta": "R1",
                "id_cliente": "C1",
                "fecha_emision": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "proxima_dispensa": None,
            }
        ],
        "ventas": [
            {
                "_id": "V1",
                "id_venta": "V1",
                "id_cliente": "C1",
                "id_farmaceutico": "F1",
                "id_receta": "R1",
                "fecha": datetime(2025, 2, 1, tzinfo=timezone.utc),
                "items": [
                    {
                        "id_detalle": "D1",
                        "id_producto": "P1",
                        "cantidad": 2,
                        "precio_unit": 100,
                    }
                ],
            },
            {
                "_id": "V2",
                "id_venta": "V2",
                "id_cliente": "C1",
                "id_farmaceutico": "F1",
                "fecha": datetime(2025, 3, 1, tzinfo=timezone.utc),
                "items": [],
            },
        ],
    }


def test_constraints_cover_every_node_label() -> None:
    labels = {spec.label for spec in NODE_SPECS}
    constrained = {label for _, label, _ in CONSTRAINTS}

    assert constrained == labels
    assert len({name for name, _, _ in CONSTRAINTS}) == len(CONSTRAINTS)


def test_node_properties_drop_internal_fields_and_convert_dates() -> None:
    spec = next(spec for spec in NODE_SPECS if spec.label == "Venta")

    properties = _node_properties(
        spec,
        {
            "_id": "V1",
            "id_venta": "V1",
            "fecha": datetime(2025, 2, 1, tzinfo=timezone.utc),
            "items": [{"id_detalle": "D1"}],
            "total": 200,
        },
    )

    assert properties == {"id_venta": "V1", "fecha": date(2025, 2, 1), "total": 200}


def test_node_properties_convert_recipe_dates_and_preserve_nulls() -> None:
    spec = next(spec for spec in NODE_SPECS if spec.label == "Receta")

    properties = _node_properties(
        spec,
        {
            "_id": "R1",
            "id_receta": "R1",
            "fecha_emision": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "proxima_dispensa": None,
        },
    )

    assert properties == {
        "id_receta": "R1",
        "fecha_emision": date(2025, 1, 1),
        "proxima_dispensa": None,
    }


def test_relationship_rows_reflect_the_dataset() -> None:
    rows = _relationship_rows(_source())

    assert len(rows["REALIZO"]) == 2
    assert len(rows["TIENE_RECETA"]) == 1
    assert len(rows["UTILIZA"]) == 1
    assert rows["UTILIZA"] == [{"id_venta": "V1", "id_receta": "R1"}]
    assert len(rows["REGISTRO"]) == 2
    assert len(rows["TRABAJA_EN"]) == 1
    assert rows["INCLUYE"] == [
        {
            "id_venta": "V1",
            "id_producto": "P1",
            "id_detalle": "D1",
            "cantidad": 2,
            "precio_unit": 100,
        }
    ]


def test_verify_counts_accepts_a_complete_projection() -> None:
    source = _source()
    nodes = {spec.label: len(source[spec.collection]) for spec in NODE_SPECS}
    relationships = {
        name: len(rows) for name, rows in _relationship_rows(source).items()
    }

    _verify_counts(source, nodes, relationships)


def test_verify_counts_rejects_a_missing_node() -> None:
    source = _source()
    nodes = {spec.label: len(source[spec.collection]) for spec in NODE_SPECS}
    nodes["Venta"] = 1
    relationships = {
        name: len(rows) for name, rows in _relationship_rows(source).items()
    }

    with pytest.raises(ProjectionError, match="Venta: esperados 2"):
        _verify_counts(source, nodes, relationships)


@pytest.mark.integration
def test_projection_is_rebuilt_without_duplicates(
    mongo_client, neo4j_driver, config
) -> None:
    source = mongo_client[config.mongo_db]
    if source["ventas"].count_documents({}) == 0:
        pytest.skip("MongoDB no tiene datos; ejecutá 'seed' primero")

    first = build_projection(source, neo4j_driver)
    second = build_projection(source, neo4j_driver)

    assert first == second

    expected_nodes = {
        spec.label: source[spec.collection].count_documents({})
        for spec in NODE_SPECS
    }
    assert first.nodes == expected_nodes
    assert first.total_nodes == sum(expected_nodes.values())

    sales = list(source["ventas"].find({}))
    expected_relationships = {
        "REALIZO": len(sales),
        "TIENE_RECETA": source["recetas"].count_documents({}),
        "UTILIZA": sum(1 for sale in sales if sale.get("id_receta")),
        "REGISTRO": len(sales),
        "TRABAJA_EN": source["farmaceuticos"].count_documents({}),
        "INCLUYE": sum(len(sale.get("items", ())) for sale in sales),
    }
    assert first.relationships == expected_relationships

    with neo4j_driver.session() as session:
        id_fields = {label: prop for _, label, prop in CONSTRAINTS}
        for spec in NODE_SPECS:
            duplicates = session.run(
                f"MATCH (n:{spec.label}) "
                f"WITH n.{id_fields[spec.label]} AS id, count(*) AS total "
                "WHERE total > 1 RETURN id"
            ).data()
            assert duplicates == [], f"{spec.label} tiene IDs duplicados"

        constraint_names = {
            record["name"]
            for record in session.run("SHOW CONSTRAINTS YIELD name")
        }
        assert {name for name, _, _ in CONSTRAINTS} <= constraint_names

        sale_with_items = next(
            (sale for sale in sales if sale.get("items")), None
        )
        if sale_with_items is not None:
            embedded = session.run(
                "MATCH (v:Venta {id_venta: $id})-[r:INCLUYE]->(p:Producto) "
                "RETURN r.id_detalle AS id_detalle, r.cantidad AS cantidad, "
                "r.precio_unit AS precio_unit, p.id_producto AS id_producto "
                "ORDER BY id_detalle",
                id=sale_with_items["id_venta"],
            ).data()
            assert embedded == [
                {
                    "id_detalle": item["id_detalle"],
                    "cantidad": item["cantidad"],
                    "precio_unit": item["precio_unit"],
                    "id_producto": item["id_producto"],
                }
                for item in sorted(
                    sale_with_items["items"], key=lambda item: item["id_detalle"]
                )
            ]

        if "V001" in {sale["id_venta"] for sale in sales}:
            fecha = session.run(
                "MATCH (v:Venta {id_venta: 'V001'}) RETURN toString(v.fecha) AS fecha"
            ).single()["fecha"]
            assert fecha == "2025-09-18"
