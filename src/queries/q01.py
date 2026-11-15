"""Consulta 01: Productos activos con todos los datos de su proveedor."""

from __future__ import annotations

import json
from typing import Any

from pymongo.database import Database

from src.config import Config
from src.db.mongo import create_client, get_database

COLECCION_PRODUCTOS = "productos"
COLECCION_PROVEEDORES = "proveedores"
CAMPO_ACTIVO = "activo"
CAMPO_ID_PROVEEDOR = "id_proveedor"
CAMPO_ID_PRODUCTO = "id_producto"
CAMPO_PROVEEDOR = "proveedor"


def q01(db: Database) -> list[dict[str, Any]]:
    """Obtiene los productos activos junto con los datos completos de su proveedor.

    Propósito:
        Listar el catálogo de productos disponibles para la venta (activo = true),
        incorporando los datos completos del proveedor habitual asociado a cada uno.
        No se filtra por proveedor activo, ya que un producto activo debe informarse
        incluso si se dejó de operar con su proveedor. Si la referencia al proveedor
        es inexistente, el producto se devuelve igualmente con 'proveedor: None'.

    Parámetros:
        db (Database): Instancia de la base de datos operativa de MongoDB.

    Retorna:
        list[dict[str, Any]]: Lista de documentos completos de producto con sus
        atributos (id_producto, nombre, principio_activo, categoria, presentacion,
        condicion_venta, precio_unit, id_proveedor, activo) y el subdocumento
        'proveedor' embebido (o None si la referencia está rota), sin el campo '_id'
        en ningún nivel, ordenados por id_producto ascendente.

    Motor:
        MongoDB.

    Resolución de relaciones:
        Relación N:1 resuelta por referencia mediante un aggregation pipeline:
        se realiza $lookup desde 'productos.id_proveedor' hacia 'proveedores._id',
        desenrollando el array resultante con $unwind (con preserveNullAndEmptyArrays = True)
        para embeber al proveedor como un objeto singular sin perder productos con
        referencias rotas. Se resuelve en MongoDB porque los proveedores son datos de
        referencia de baja frecuencia de actualización que no se proyectan en Neo4j.
    """
    pipeline = [
        {"$match": {CAMPO_ACTIVO: True}},
        {
            "$lookup": {
                "from": COLECCION_PROVEEDORES,
                "localField": CAMPO_ID_PROVEEDOR,
                "foreignField": "_id",
                "as": CAMPO_PROVEEDOR,
            }
        },
        {
            "$unwind": {
                "path": f"${CAMPO_PROVEEDOR}",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {"$addFields": {CAMPO_PROVEEDOR: {"$ifNull": [f"${CAMPO_PROVEEDOR}", None]}}},
        {"$project": {"_id": 0, f"{CAMPO_PROVEEDOR}._id": 0}},
        {"$sort": {CAMPO_ID_PRODUCTO: 1}},
    ]

    cursor = db[COLECCION_PRODUCTOS].aggregate(pipeline)
    return list(cursor)


if __name__ == "__main__":
    config = Config.from_env()
    client = create_client(config)
    try:
        database = get_database(client, config)
        resultado = q01(database)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        client.close()
