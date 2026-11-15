"""Consulta 11: Vista agregada: ingresos totales por farmacéutico en el mes actual (solo ventas 'Completada')."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pymongo.database import Database

from src.config import Config
from src.db.mongo import create_client, get_database

ZONA_HORARIA_ARG = timezone(timedelta(hours=-3))
ESTADO_COMPLETADA = "Completada"

COLECCION_VENTAS = "ventas"
COLECCION_FARMACEUTICOS = "farmaceuticos"


def _calcular_ventana_mes(
    ahora: datetime | None,
) -> tuple[datetime, datetime]:
    """Calcula la ventana [inicio_mes, inicio_mes_siguiente) en datetime UTC a medianoche.

    Si 'ahora' es None, toma la fecha/hora actual del sistema en UTC-3.
    Si 'ahora' es naive (sin tzinfo), se interpreta como hora local UTC-3.
    Si 'ahora' es aware (con tzinfo), se convierte a UTC-3.
    """
    if ahora is None:
        fecha_ref = datetime.now(ZONA_HORARIA_ARG)
    elif ahora.tzinfo is None:
        fecha_ref = ahora.replace(tzinfo=ZONA_HORARIA_ARG)
    else:
        fecha_ref = ahora.astimezone(ZONA_HORARIA_ARG)

    año = fecha_ref.year
    mes = fecha_ref.month

    # Inicio del mes a las 00:00:00 UTC
    inicio_mes = datetime(año, mes, 1, 0, 0, 0, tzinfo=timezone.utc)

    # Inicio del mes siguiente a las 00:00:00 UTC (manejando fin de año)
    if mes == 12:
        año_sig = año + 1
        mes_sig = 1
    else:
        año_sig = año
        mes_sig = mes + 1
    inicio_mes_siguiente = datetime(año_sig, mes_sig, 1, 0, 0, 0, tzinfo=timezone.utc)

    return inicio_mes, inicio_mes_siguiente


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
            Si es None, se utiliza la fecha actual del sistema en zona horaria UTC-3.

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
        1. Vista agregada como función: se resuelve como una función sobre 'ventas'
           mediante un aggregation pipeline con cálculo dinámico de ventana temporal
           en UTC-3, evitando vistas estáticas de MongoDB que requerirían $$NOW y
           gestión compleja de zonas horarias en la base.
        2. Sin ceros (decisión de diseño): solo aparecen los profesionales que hayan
           registrado al menos una venta completada en el mes.
        3. Relación N:1 por referencia: tras agrupar y sumar 'total' por id_farmaceutico,
           se realiza $lookup hacia 'farmaceuticos._id' para completar los datos
           personales y profesionales.
        4. Referencias rotas: si el id_farmaceutico no existe en 'farmaceuticos', se
           devuelve el documento con nombre, apellido, matricula y activo en None,
           sin perder el registro de los ingresos correspondientes.
    """
    inicio_mes, inicio_mes_siguiente = _calcular_ventana_mes(ahora)

    pipeline = [
        {
            "$match": {
                "estado": ESTADO_COMPLETADA,
                "fecha": {"$gte": inicio_mes, "$lt": inicio_mes_siguiente},
            }
        },
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
        help="Fecha de referencia en formato AAAA-MM-DD (hora local UTC-3)",
    )
    args = parser.parse_args()

    ahora_dt: datetime | None = None
    if args.ahora:
        d = date.fromisoformat(args.ahora)
        ahora_dt = datetime(d.year, d.month, d.day, tzinfo=ZONA_HORARIA_ARG)

    config = Config.from_env()
    client = create_client(config)
    try:
        database = get_database(client, config)
        resultado = q11(database, ahora=ahora_dt)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        client.close()
