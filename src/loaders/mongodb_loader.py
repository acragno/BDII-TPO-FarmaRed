"""Carga inicial de los datos validados en MongoDB"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Mapping, Sequence

from pymongo import ReplaceOne
from pymongo.collection import Collection
from pymongo.database import Database

from src.loaders.validate import TABLES

LOAD_ORDER: tuple[str, ...] = (
    "proveedores",
    "sucursales",
    "clientes",
    "farmaceuticos",
    "productos",
    "stock_lotes",
    "recetas",
    "ventas",
)

DETAIL_FIELDS = ("id_detalle", "id_producto", "cantidad", "precio_unit")


@dataclass(frozen=True)
class LoadReport:
    """Cantidades cargadas por colección"""

    collections: dict[str, int]
    items: int


def load_dataset(
    database: Database,
    records: Mapping[str, Sequence[Mapping[str, Any]]],
) -> LoadReport:
    details = _group_details(records.get("detalle_ventas", ()))
    counts: dict[str, int] = {}

    for table in LOAD_ORDER:
        documents = [
            _to_document(table, record) for record in records.get(table, ())
        ]
        if table == "ventas":
            for document in documents:
                document["items"] = details.get(document["id_venta"], [])

        _upsert_many(database[table], documents)
        counts[table] = len(documents)

    return LoadReport(
        collections=counts,
        items=sum(len(items) for items in details.values()),
    )


def clear_database(database: Database) -> dict[str, int]:
    counts = {
        name: database[name].count_documents({})
        for name in database.list_collection_names()
    }
    database.client.drop_database(database.name)
    return counts


def ensure_indexes(database: Database) -> dict[str, list[str]]:
    created: dict[str, list[str]] = {}

    created["clientes"] = [
        database["clientes"].create_index(
            "dni", unique=True, name="uniq_clientes_dni"
        )
    ]
    created["farmaceuticos"] = [
        database["farmaceuticos"].create_index(
            "matricula", unique=True, name="uniq_farmaceuticos_matricula"
        )
    ]
    created["productos"] = [
        database["productos"].create_index(
            "id_producto", name="idx_productos_id_producto"
        )
    ]
    created["ventas"] = [
        database["ventas"].create_index(
            "id_cliente", name="idx_ventas_id_cliente"
        ),
        database["ventas"].create_index("fecha", name="idx_ventas_fecha"),
    ]
    created["stock_lotes"] = [
        database["stock_lotes"].create_index(
            [("id_sucursal", 1), ("id_producto", 1), ("vencimiento", 1)],
            name="idx_stock_lotes_sucursal_producto_vencimiento",
        )
    ]
    created["recetas"] = [
        database["recetas"].create_index(
            "id_cliente", name="idx_recetas_id_cliente"
        )
    ]

    created["outbox"] = [
        database["outbox"].create_index(
            [("state", 1), ("created_at", 1)],
            name="idx_outbox_state_created_at",
        )
]

    return created


def _to_document(
    table: str, record: Mapping[str, Any]
) -> dict[str, Any]:
    identifier = record[TABLES[table].id_field]
    document: dict[str, Any] = {"_id": identifier}

    for field_name, value in record.items():
        if value is None:
            continue
        document[field_name] = _to_bson(value)

    return document


def _to_bson(value: Any) -> Any:
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    return value


def _group_details(
    details: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for detail in details:
        sale_id = detail["id_venta"]
        grouped.setdefault(sale_id, []).append(
            {field: detail[field] for field in DETAIL_FIELDS}
        )

    for items in grouped.values():
        items.sort(key=lambda item: item["id_detalle"])

    return grouped


def _upsert_many(
    collection: Collection, documents: Sequence[Mapping[str, Any]]
) -> None:
    if not documents:
        return

    requests = [
        ReplaceOne({"_id": document["_id"]}, document, upsert=True)
        for document in documents
    ]
    collection.bulk_write(requests, ordered=False)
