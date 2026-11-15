"""Consulta 08: Lotes con menos de 50 unidades, indicando producto, sucursal y proveedor."""

from __future__ import annotations

import json
from typing import Any

from pymongo.database import Database

from src.config import Config
from src.db.mongo import create_client, get_database

UMBRAL_STOCK_BAJO = 50

COLECCION_STOCK_LOTES = "stock_lotes"
COLECCION_PRODUCTOS = "productos"
COLECCION_PROVEEDORES = "proveedores"
COLECCION_SUCURSALES = "sucursales"


def q08(db: Database) -> list[dict[str, Any]]:
    """Obtiene los lotes con menos de 50 unidades, indicando producto, sucursal y proveedor.

    Propósito:
        Identificar lotes con bajo nivel de existencias (menos de 50 unidades) para
        gestión de reposición y control de inventario. No se excluyen lotes de la
        Droguería, lotes vencidos ni lotes correspondientes a productos inactivos,
        ya que la consigna no impone restricciones de stock adicionales. La consulta
        tampoco depende de la fecha actual del sistema.

    Parámetros:
        db (Database): Instancia de la base de datos operativa de MongoDB.

    Retorna:
        list[dict[str, Any]]: Lista de documentos con la estructura exacta:
        {
            "id_lote": str,
            "nro_lote": str,
            "unidades": int,
            "vencimiento": datetime,
            "producto": {"id_producto": str, "nombre": str} | None,
            "sucursal": {"id_sucursal": str, "nombre": str, "tipo": str} | None,
            "proveedor": {"id_proveedor": str, "razon_social": str} | None,
        }
        Sin campo '_id' en ningún nivel, ordenados por unidades ascendente y
        por id_lote ascendente como criterio de desempate.

    Motor:
        MongoDB.

    Resolución de relaciones:
        Relaciones N:1 resueltas por referencia mediante un aggregation pipeline
        sobre la colección 'stock_lotes' con tres etapas $lookup encadenadas:
        1. Lote -> Producto: $lookup de 'stock_lotes.id_producto' hacia 'productos._id'.
        2. Producto -> Proveedor: $lookup de 'producto.id_proveedor' hacia 'proveedores._id'.
           El proveedor es el proveedor habitual del producto y se alcanza a través de él.
        3. Lote -> Sucursal: $lookup de 'stock_lotes.id_sucursal' hacia 'sucursales._id'.
        Cada etapa usa $unwind con 'preserveNullAndEmptyArrays: True'. Si una referencia
        está rota o falta, el subdocumento correspondiente se normaliza a None en el
        $project final sin ocultar el lote.
    """
    pipeline = [
        {"$match": {"unidades": {"$lt": UMBRAL_STOCK_BAJO}}},
        {
            "$lookup": {
                "from": COLECCION_PRODUCTOS,
                "localField": "id_producto",
                "foreignField": "_id",
                "as": "producto",
            }
        },
        {"$unwind": {"path": "$producto", "preserveNullAndEmptyArrays": True}},
        {
            "$lookup": {
                "from": COLECCION_PROVEEDORES,
                "localField": "producto.id_proveedor",
                "foreignField": "_id",
                "as": "proveedor",
            }
        },
        {"$unwind": {"path": "$proveedor", "preserveNullAndEmptyArrays": True}},
        {
            "$lookup": {
                "from": COLECCION_SUCURSALES,
                "localField": "id_sucursal",
                "foreignField": "_id",
                "as": "sucursal",
            }
        },
        {"$unwind": {"path": "$sucursal", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "_id": 0,
                "id_lote": 1,
                "nro_lote": 1,
                "unidades": 1,
                "vencimiento": 1,
                "producto": {
                    "$cond": {
                        "if": "$producto",
                        "then": {
                            "id_producto": "$producto.id_producto",
                            "nombre": "$producto.nombre",
                        },
                        "else": None,
                    }
                },
                "sucursal": {
                    "$cond": {
                        "if": "$sucursal",
                        "then": {
                            "id_sucursal": "$sucursal.id_sucursal",
                            "nombre": "$sucursal.nombre",
                            "tipo": "$sucursal.tipo",
                        },
                        "else": None,
                    }
                },
                "proveedor": {
                    "$cond": {
                        "if": "$proveedor",
                        "then": {
                            "id_proveedor": "$proveedor.id_proveedor",
                            "razon_social": "$proveedor.razon_social",
                        },
                        "else": None,
                    }
                },
            }
        },
        {"$sort": {"unidades": 1, "id_lote": 1}},
    ]

    cursor = db[COLECCION_STOCK_LOTES].aggregate(pipeline)
    return list(cursor)


if __name__ == "__main__":
    config = Config.from_env()
    client = create_client(config)
    try:
        database = get_database(client, config)
        resultado = q08(database)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        client.close()
