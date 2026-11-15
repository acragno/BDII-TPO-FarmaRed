"""Consulta 11: Vista agregada: ingresos totales por farmacéutico en el mes actual (solo ventas 'Completada')."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from typing import Any

from pymongo.database import Database

from src.config import Config
from src.db.mongo import create_client, get_database

ESTADO_COMPLETADA = "Completada"

COLECCION_VENTAS = "ventas"
COLECCION_FARMACEUTICOS = "farmaceuticos"


def q11(
    db: Database, ahora: datetime | None = None
) -> list[dict[str, Any]]:
    """Obtiene los ingresos totales por farmacéutico en el mes actual para ventas completadas.

    Propósito:
        Construir una vista agregada que totalice la facturación generada por cada
        farmacéutico durante el mes calendario en curso (o el mes inyectado en 'ahora').
        Solo se computan operaciones con estado 'Completada' (las pendientes y anuladas
        se excluyen). No se excluyen farmacéuticos inactivos: si registraron ventas
        completadas en el período, se informan junto con sus ingresos y activo = False.

    Parámetros:
        db (Database): Instancia de la base de datos operativa de MongoDB.
        ahora (datetime | None): Fecha/hora de referencia para determinar el mes calendario.
            Si es None, se evalúa directamente el año y mes actual en el servidor de MongoDB
            utilizando la variable de sistema $$NOW en UTC. Si se provee, se interpreta
            en UTC (asumiendo UTC si es naive o convirtiendo a UTC si es aware).

    Retorna:
        list[dict[str, Any]]: Lista de documentos con la estructura exacta:
        {
            "id_farmaceutico": str,
            "nombre": str | None,
            "apellido": str | None,
            "matricula": str | None,
            "activo": bool | None,
            "ingresos": int,
        }
        Sin campo '_id', ordenados por ingresos descendente y por id_farmaceutico
        ascendente como desempate. Si no hay ventas en el mes, devuelve [].

    Motor:
        MongoDB.

    Resolución de relaciones:
        1. Vista agregada dinámica con $$NOW: se resuelve como una función sobre 'ventas'
           mediante un aggregation pipeline. Cuando 'ahora' es None, evalúa el año
           y mes actual directamente en el motor utilizando la variable de sistema
           $$NOW en UTC dentro de $expr, respetando la fecha del sistema del servidor.
        2. Sin ceros (decisión de diseño): solo aparecen los profesionales que hayan
           registrado al menos una venta completada en el mes.
        3. Relación N:1 por referencia: tras agrupar y sumar 'total' por id_farmaceutico,
           se realiza $lookup hacia 'farmaceuticos._id' para completar los datos
           personales y profesionales.
        4. Referencias rotas: si el id_farmaceutico no existe en 'farmaceuticos', se
           devuelve el documento con nombre, apellido, matricula y activo en None,
           sin perder el registro de los ingresos correspondientes.
    """
    filtro_match: dict[str, Any]
    if ahora is None:
        filtro_match = {
            "estado": ESTADO_COMPLETADA,
            "$expr": {
                "$and": [
                    {"$eq": [{"$year": "$fecha"}, {"$year": "$$NOW"}]},
                    {"$eq": [{"$month": "$fecha"}, {"$month": "$$NOW"}]},
                ]
            },
        }
    else:
        if ahora.tzinfo is None:
            ahora_utc = ahora.replace(tzinfo=timezone.utc)
        else:
            ahora_utc = ahora.astimezone(timezone.utc)

        año = ahora_utc.year
        mes = ahora_utc.month
        inicio_mes = datetime(año, mes, 1, 0, 0, 0, tzinfo=timezone.utc)
        inicio_mes_siguiente = (
            datetime(año + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            if mes == 12
            else datetime(año, mes + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        )
        filtro_match = {
            "estado": ESTADO_COMPLETADA,
            "fecha": {"$gte": inicio_mes, "$lt": inicio_mes_siguiente},
        }

    pipeline = [
        {"$match": filtro_match},
        {"$group": {"_id": "$id_farmaceutico", "ingresos": {"$sum": "$total"}}},
        {
            "$lookup": {
                "from": COLECCION_FARMACEUTICOS,
                "localField": "_id",
                "foreignField": "_id",
                "as": "f",
            }
        },
        {"$unwind": {"path": "$f", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "_id": 0,
                "id_farmaceutico": "$_id",
                "nombre": {"$ifNull": ["$f.nombre", None]},
                "apellido": {"$ifNull": ["$f.apellido", None]},
                "matricula": {"$ifNull": ["$f.matricula", None]},
                "activo": {"$ifNull": ["$f.activo", None]},
                "ingresos": 1,
            }
        },
        {"$sort": {"ingresos": -1, "id_farmaceutico": 1}},
    ]

    cursor = db[COLECCION_VENTAS].aggregate(pipeline)
    return list(cursor)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Q11: Ingresos totales por farmacéutico en el mes actual"
    )
    parser.add_argument(
        "--ahora",
        type=str,
        help="Fecha de referencia en formato AAAA-MM-DD (interpretada en UTC)",
    )
    args = parser.parse_args()

    ahora_dt: datetime | None = None
    if args.ahora:
        d = date.fromisoformat(args.ahora)
        ahora_dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

    config = Config.from_env()
    client = create_client(config)
    try:
        database = get_database(client, config)
        if ahora_dt is None:
            server_info = database.command("hello")
            server_time = server_info.get("localTime")
            if server_time is None:
                server_time = datetime.now(timezone.utc)
            elif server_time.tzinfo is None:
                server_time = server_time.replace(tzinfo=timezone.utc)
            print(
                f"[Q11] Fecha/hora del servidor MongoDB ($$NOW en UTC): {server_time.isoformat()} "
                f"| Mes evaluado: {server_time.strftime('%Y-%m')}",
                file=sys.stderr,
            )
        else:
            print(
                f"[Q11] Fecha/hora inyectada (--ahora en UTC): {ahora_dt.isoformat()} "
                f"| Mes evaluado: {ahora_dt.strftime('%Y-%m')}",
                file=sys.stderr,
            )

        resultado = q11(database, ahora=ahora_dt)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        client.close()
