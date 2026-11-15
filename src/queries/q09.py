"""Consulta 09: Ventas de tipo 'Venta libre' con total menor a $5.000 (excluyendo anuladas)."""

from __future__ import annotations

import json
from typing import Any

from pymongo.database import Database

from src.config import Config
from src.db.mongo import create_client, get_database

UMBRAL_VENTA_LIBRE = 5000
TIPO_VENTA_LIBRE = "Venta libre"
ESTADO_EXCLUIDO = "Anulada"


def q09(db: Database) -> list[dict[str, Any]]:
    """Obtiene las ventas de tipo 'Venta libre' con total menor a $5.000, excluyendo anuladas.

    Propósito:
        Identificar las operaciones de mostrador de bajo monto (menores a $5.000)
        que no hayan sido anuladas, incluyendo tanto ventas completadas como pendientes.

    Parámetros:
        db (Database): Instancia de la base de datos operativa de MongoDB.

    Retorna:
        list[dict[str, Any]]: Lista de documentos completos de venta (cabecera con
        array embebido de items), sin el campo '_id', ordenados de manera determinista
        por fecha ascendente y por id_venta ascendente.

    Motor:
        MongoDB.

    Resolución de relaciones:
        No aplica. La consulta se ejecuta de forma directa sobre la colección 'ventas'
        mediante find(). Los ítems del detalle de venta se encuentran embebidos en el
        array 'items' de cada documento de venta, por lo que no se requiere $lookup.
    """
    filtro = {
        "tipo": TIPO_VENTA_LIBRE,
        "total": {"$lt": UMBRAL_VENTA_LIBRE},
        "estado": {"$ne": ESTADO_EXCLUIDO},
    }
    proyeccion = {"_id": 0}

    cursor = db["ventas"].find(filtro, proyeccion).sort([("fecha", 1), ("id_venta", 1)])
    return list(cursor)


if __name__ == "__main__":
    config = Config.from_env()
    client = create_client(config)
    try:
        database = get_database(client, config)
        resultado = q09(database)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        client.close()
