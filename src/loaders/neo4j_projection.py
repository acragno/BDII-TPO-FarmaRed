"""Proyección de lectura de FarmaRed en Neo4j"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from neo4j import Driver, Session, Transaction
from pymongo.database import Database

CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    ("uniq_cliente_id_cliente", "Cliente", "id_cliente"),
    ("uniq_sucursal_id_sucursal", "Sucursal", "id_sucursal"),
    ("uniq_farmaceutico_id_farmaceutico", "Farmaceutico", "id_farmaceutico"),
    ("uniq_producto_id_producto", "Producto", "id_producto"),
    ("uniq_receta_id_receta", "Receta", "id_receta"),
    ("uniq_venta_id_venta", "Venta", "id_venta"),
)

RELATIONSHIP_ORDER: tuple[str, ...] = (
    "REALIZO",
    "TIENE_RECETA",
    "UTILIZA",
    "REGISTRO",
    "TRABAJA_EN",
    "INCLUYE",
)


class ProjectionError(RuntimeError):
    """La proyección no se pudo construir o quedó inconsistente."""


@dataclass(frozen=True)
class NodeSpec:
    collection: str
    label: str
    excluded: tuple[str, ...] = ()
    date_fields: tuple[str, ...] = ()


NODE_SPECS: tuple[NodeSpec, ...] = (
    NodeSpec("clientes", "Cliente"),
    NodeSpec("sucursales", "Sucursal"),
    NodeSpec("farmaceuticos", "Farmaceutico"),
    NodeSpec("productos", "Producto"),
    NodeSpec(
        "recetas",
        "Receta",
        date_fields=("fecha_emision", "proxima_dispensa"),
    ),
    NodeSpec("ventas", "Venta", excluded=("items",), date_fields=("fecha",)),
)


@dataclass(frozen=True)
class ProjectionReport:
    constraints: tuple[str, ...]
    nodes: dict[str, int]
    relationships: dict[str, int]

    @property
    def total_nodes(self) -> int:
        return sum(self.nodes.values())

    @property
    def total_relationships(self) -> int:
        return sum(self.relationships.values())


def build_projection(
    mongo_db: Database,
    driver: Driver,
    database: str = "neo4j",
) -> ProjectionReport:
    source = _read_source(mongo_db)
    if not source["clientes"] and not source["ventas"]:
        raise ProjectionError(
            "MongoDB no tiene datos cargados; ejecutá 'load-mongodb' primero"
        )

    with driver.session(database=database) as session:
        constraints = ensure_constraints(session)
        session.execute_write(_rebuild, source)
        nodes, relationships = _graph_counts(session)

    _verify_counts(source, nodes, relationships)
    return ProjectionReport(
        constraints=constraints, nodes=nodes, relationships=relationships
    )


def ensure_constraints(session: Session) -> tuple[str, ...]:
    names: list[str] = []
    for name, label, property_name in CONSTRAINTS:
        session.run(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{property_name} IS UNIQUE"
        ).consume()
        names.append(name)
    return tuple(names)


def _read_source(mongo_db: Database) -> dict[str, list[dict[str, Any]]]:
    return {
        spec.collection: list(mongo_db[spec.collection].find({}))
        for spec in NODE_SPECS
    }


def _rebuild(tx: Transaction, source: dict[str, list[dict[str, Any]]]) -> None:
    tx.run("MATCH (n) DETACH DELETE n").consume()

    for spec in NODE_SPECS:
        rows = [
            _node_properties(spec, document)
            for document in source[spec.collection]
        ]
        if not rows:
            continue
        tx.run(
            f"UNWIND $rows AS row CREATE (n:{spec.label}) SET n = row",
            rows=rows,
        ).consume()

    for relationship_type, rows in _relationship_rows(source).items():
        if not rows:
            continue
        tx.run(
            _RELATIONSHIP_QUERIES[relationship_type],
            rows=rows,
        ).consume()


def _node_properties(
    spec: NodeSpec, document: dict[str, Any]
) -> dict[str, Any]:
    properties = {
        name: value
        for name, value in document.items()
        if name != "_id" and name not in spec.excluded
    }

    for field in spec.date_fields:
        value = properties.get(field)
        if isinstance(value, datetime):
            properties[field] = value.date()
        elif isinstance(value, date):
            properties[field] = value

    return properties


def _relationship_rows(
    source: dict[str, list[dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    sales = source["ventas"]

    return {
        "REALIZO": [
            {
                "id_cliente": sale["id_cliente"],
                "id_venta": sale["id_venta"],
            }
            for sale in sales
        ],
        "TIENE_RECETA": [
            {
                "id_cliente": recipe["id_cliente"],
                "id_receta": recipe["id_receta"],
            }
            for recipe in source["recetas"]
        ],
        "UTILIZA": [
            {
                "id_venta": sale["id_venta"],
                "id_receta": sale["id_receta"],
            }
            for sale in sales
            if sale.get("id_receta")
        ],
        "REGISTRO": [
            {
                "id_farmaceutico": sale["id_farmaceutico"],
                "id_venta": sale["id_venta"],
            }
            for sale in sales
        ],
        "TRABAJA_EN": [
            {
                "id_farmaceutico": pharmacist["id_farmaceutico"],
                "id_sucursal": pharmacist["id_sucursal"],
            }
            for pharmacist in source["farmaceuticos"]
        ],
        "INCLUYE": [
            {
                "id_venta": sale["id_venta"],
                "id_producto": item["id_producto"],
                "id_detalle": item["id_detalle"],
                "cantidad": item["cantidad"],
                "precio_unit": item["precio_unit"],
            }
            for sale in sales
            for item in sale.get("items", ())
        ],
    }


_RELATIONSHIP_QUERIES = {
    "REALIZO": """
        UNWIND $rows AS row
        MATCH (cliente:Cliente {id_cliente: row.id_cliente})
        MATCH (venta:Venta {id_venta: row.id_venta})
        CREATE (cliente)-[:REALIZO]->(venta)
    """,
    "TIENE_RECETA": """
        UNWIND $rows AS row
        MATCH (cliente:Cliente {id_cliente: row.id_cliente})
        MATCH (receta:Receta {id_receta: row.id_receta})
        CREATE (cliente)-[:TIENE_RECETA]->(receta)
    """,
    "UTILIZA": """
        UNWIND $rows AS row
        MATCH (venta:Venta {id_venta: row.id_venta})
        MATCH (receta:Receta {id_receta: row.id_receta})
        CREATE (venta)-[:UTILIZA]->(receta)
    """,
    "REGISTRO": """
        UNWIND $rows AS row
        MATCH (farmaceutico:Farmaceutico {id_farmaceutico: row.id_farmaceutico})
        MATCH (venta:Venta {id_venta: row.id_venta})
        CREATE (farmaceutico)-[:REGISTRO]->(venta)
    """,
    "TRABAJA_EN": """
        UNWIND $rows AS row
        MATCH (farmaceutico:Farmaceutico {id_farmaceutico: row.id_farmaceutico})
        MATCH (sucursal:Sucursal {id_sucursal: row.id_sucursal})
        CREATE (farmaceutico)-[:TRABAJA_EN]->(sucursal)
    """,
    "INCLUYE": """
        UNWIND $rows AS row
        MATCH (venta:Venta {id_venta: row.id_venta})
        MATCH (producto:Producto {id_producto: row.id_producto})
        CREATE (venta)-[relacion:INCLUYE]->(producto)
        SET relacion.id_detalle = row.id_detalle,
            relacion.cantidad = row.cantidad,
            relacion.precio_unit = row.precio_unit
    """,
}


def _graph_counts(session: Session) -> tuple[dict[str, int], dict[str, int]]:
    node_rows = session.run(
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS total"
    )
    measured_nodes = {row["label"]: row["total"] for row in node_rows}

    relationship_rows = session.run(
        "MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS total"
    )
    measured_relationships = {
        row["tipo"]: row["total"] for row in relationship_rows
    }

    nodes = {
        spec.label: measured_nodes.get(spec.label, 0) for spec in NODE_SPECS
    }
    relationships = {
        name: measured_relationships.get(name, 0)
        for name in RELATIONSHIP_ORDER
    }
    return nodes, relationships


def _verify_counts(
    source: dict[str, list[dict[str, Any]]],
    nodes: dict[str, int],
    relationships: dict[str, int],
) -> None:
    expected_nodes = {
        spec.label: len(source[spec.collection]) for spec in NODE_SPECS
    }
    expected_relationships = {
        name: len(rows) for name, rows in _relationship_rows(source).items()
    }

    problems: list[str] = []
    for label, expected in expected_nodes.items():
        if nodes.get(label) != expected:
            problems.append(
                f"{label}: esperados {expected}, encontrados {nodes.get(label, 0)}"
            )
    for name, expected in expected_relationships.items():
        if relationships.get(name) != expected:
            problems.append(
                f"{name}: esperadas {expected}, encontradas "
                f"{relationships.get(name, 0)}"
            )

    if problems:
        raise ProjectionError(
            "La proyección quedó incompleta: " + "; ".join(problems)
        )
