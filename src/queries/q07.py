"""Consulta 07: Top 5 productos más vendidos (unidades), considerando solo ventas 'Completada'."""

from __future__ import annotations

import json
from typing import Any

from pymongo.database import Database

from src.config import Config
from src.db.mongo import create_client, get_database

TOP_N = 5
ESTADO_COMPLETADA = "Completada"

COLECCION_VENTAS = "ventas"
COLECCION_PRODUCTOS = "productos"


def q07(db: Database) -> list[dict[str, Any]]:
    """Obtiene el Top 5 de productos más vendidos en unidades en ventas completadas.

    Propósito:
        Construir el ranking de los 5 productos con mayor volumen de unidades vendidas,
        considerando exclusivamente operaciones con estado 'Completada' (las ventas
        pendientes o anuladas no suman). No aplica ventana temporal ni excluye
        productos inactivos.

    Parámetros:
        db (Database): Instancia de la base de datos operativa de MongoDB.

    Retorna:
        list[dict[str, Any]]: Lista de hasta cinco documentos con la estructura exacta:
        {
            "id_producto": str,
            "nombre": str | None,
            "unidades": int,
        }
        Sin campo '_id', ordenados por unidades descendente y por id_producto ascendente
        como criterio de desempate determinista. Si hay menos de cinco productos con
        ventas completadas se devuelven los existentes; si no hay ninguna, devuelve [].

    Motor:
        MongoDB.

    Resolución de relaciones:
        1. Detalle de ventas embebido: los ítems de venta están embebidos en el array
           'ventas.items', por lo que se desenrollan con $unwind sin necesidad de
           consultar una colección separada de detalles.
        2. Relación N:1 por referencia con productos: se realiza $lookup desde
           '_id' (id_producto agrupado) hacia 'productos._id' únicamente para
           incorporar el 'nombre' del producto.
        3. Convención de desempate: ante empates en unidades (incluyendo el 5.º puesto),
           se respeta estrictamente el límite de 5 elementos desempatando por
           'id_producto' ascendente.
        4. Referencias rotas: si un id_producto presente en los ítems no existe en
           'productos', el producto entra al ranking con 'nombre: None' gracias a
           $unwind con 'preserveNullAndEmptyArrays: True'.
    """
    pipeline = [
        {"$match": {"estado": ESTADO_COMPLETADA}},
        {"$unwind": "$items"},
        {
            "$group": {
                "_id": "$items.id_producto",
                "unidades": {"$sum": "$items.cantidad"},
            }
        },
        {"$sort": {"unidades": -1, "_id": 1}},
        {"$limit": TOP_N},
        {
            "$lookup": {
                "from": COLECCION_PRODUCTOS,
                "localField": "_id",
                "foreignField": "_id",
                "as": "producto",
            }
        },
        {"$unwind": {"path": "$producto", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "_id": 0,
                "id_producto": "$_id",
                "nombre": {"$ifNull": ["$producto.nombre", None]},
                "unidades": 1,
            }
        },
        {"$sort": {"unidades": -1, "id_producto": 1}},
    ]

    cursor = db[COLECCION_VENTAS].aggregate(pipeline)
    return list(cursor)


if __name__ == "__main__":
    config = Config.from_env()
    client = create_client(config)
    try:
        database = get_database(client, config)
        resultado = q07(database)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        client.close()
