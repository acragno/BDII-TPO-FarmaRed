from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.loaders.mongodb_loader import (
    LOAD_ORDER,
    _group_details,
    _to_document,
    ensure_indexes,
    load_dataset,
)
from src.loaders.validate import validate_data
from tests.support import DATA_DIR, EXPECTED_COUNTS

EXPECTED_COLLECTIONS = {
    table: EXPECTED_COUNTS[table] for table in LOAD_ORDER
}


def test_to_document_uses_original_id_and_bson_dates() -> None:
    document = _to_document(
        "ventas",
        {
            "id_venta": "V001",
            "id_cliente": "C004",
            "id_receta": None,
            "fecha": date(2025, 9, 18),
            "total": 3850,
        },
    )

    assert document["_id"] == "V001"
    assert document["id_venta"] == "V001"
    assert document["fecha"] == datetime(2025, 9, 18, tzinfo=timezone.utc)
    assert "id_receta" not in document


def test_details_are_embedded_and_sorted() -> None:
    grouped = _group_details(
        [
            {
                "id_detalle": "D003",
                "id_venta": "V002",
                "id_producto": "PRD001",
                "cantidad": 1,
                "precio_unit": 2250,
                "desconocido": "se ignora",
            },
            {
                "id_detalle": "D002",
                "id_venta": "V002",
                "id_producto": "PRD011",
                "cantidad": 2,
                "precio_unit": 1750,
            },
        ]
    )

    assert grouped == {
        "V002": [
            {
                "id_detalle": "D002",
                "id_producto": "PRD011",
                "cantidad": 2,
                "precio_unit": 1750,
            },
            {
                "id_detalle": "D003",
                "id_producto": "PRD001",
                "cantidad": 1,
                "precio_unit": 2250,
            },
        ]
    }


@pytest.mark.integration
def test_load_is_idempotent(mongo_test_db) -> None:
    result = validate_data(DATA_DIR)
    assert result.ok, [str(issue) for issue in result.issues]

    first = load_dataset(mongo_test_db, result.records)
    first_indexes = ensure_indexes(mongo_test_db)
    second = load_dataset(mongo_test_db, result.records)
    ensure_indexes(mongo_test_db)

    assert first == second
    assert first.collections == EXPECTED_COLLECTIONS
    assert first.items == EXPECTED_COUNTS["detalle_ventas"]
    assert first_indexes["clientes"] == ["uniq_clientes_dni"]

    collections = set(mongo_test_db.list_collection_names())
    assert collections == set(LOAD_ORDER)
    assert "detalle_ventas" not in collections

    for table, expected in EXPECTED_COLLECTIONS.items():
        assert mongo_test_db[table].count_documents({}) == expected
    assert len(mongo_test_db["ventas"].distinct("_id")) == EXPECTED_COUNTS["ventas"]


@pytest.mark.integration
def test_documents_keep_types_and_embedded_items(mongo_test_db) -> None:
    result = validate_data(DATA_DIR)
    load_dataset(mongo_test_db, result.records)

    sale = mongo_test_db["ventas"].find_one({"_id": "V001"})
    assert sale["id_venta"] == "V001"
    assert sale["fecha"] == datetime(2025, 9, 18, tzinfo=timezone.utc)
    assert isinstance(sale["total"], int)
    assert sale["items"] == [
        {
            "id_detalle": "D001",
            "id_producto": "PRD007",
            "cantidad": 1,
            "precio_unit": 3850,
        }
    ]

    multi = mongo_test_db["ventas"].find_one({"_id": "V002"})
    assert [item["id_detalle"] for item in multi["items"]] == ["D002", "D003"]

    client = mongo_test_db["clientes"].find_one({"_id": "C005"})
    assert client["activo"] is True
    assert "nro_afiliado" not in client

    batch = mongo_test_db["stock_lotes"].find_one({"_id": "L001"})
    assert batch["vencimiento"] == datetime(2027, 8, 31, tzinfo=timezone.utc)
    assert isinstance(batch["unidades"], int)

    recipe = mongo_test_db["recetas"].find_one({"_id": "RC002"})
    assert recipe["proxima_dispensa"] == datetime(
        2026, 9, 15, tzinfo=timezone.utc
    )
    assert "proxima_dispensa" not in mongo_test_db["recetas"].find_one(
        {"_id": "RC001"}
    )


@pytest.mark.integration
def test_indexes(mongo_test_db) -> None:
    result = validate_data(DATA_DIR)
    load_dataset(mongo_test_db, result.records)
    ensure_indexes(mongo_test_db)

    client_index = mongo_test_db["clientes"].index_information()[
        "uniq_clientes_dni"
    ]
    assert client_index["key"] == [("dni", 1)]
    assert client_index["unique"] is True

    pharmacist_index = mongo_test_db["farmaceuticos"].index_information()[
        "uniq_farmaceuticos_matricula"
    ]
    assert pharmacist_index["unique"] is True

    stock_index = mongo_test_db["stock_lotes"].index_information()[
        "idx_stock_lotes_sucursal_producto_vencimiento"
    ]
    assert stock_index["key"] == [
        ("id_sucursal", 1),
        ("id_producto", 1),
        ("vencimiento", 1),
    ]

    sale_indexes = mongo_test_db["ventas"].index_information()
    assert "idx_ventas_id_cliente" in sale_indexes
    assert "idx_ventas_fecha" in sale_indexes
