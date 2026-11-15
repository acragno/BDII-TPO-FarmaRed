"""Consulta 02: Ventas pendientes con farmacéutico y sucursal."""

from __future__ import annotations

import json
from typing import Any

from neo4j import Session, Transaction

from src.config import Config
from src.db.neo4j import NEO4J_DATABASE, create_driver

ESTADO_PENDIENTE = "Pendiente"


def q02(session: Session | Transaction) -> list[dict[str, Any]]:
    """Obtiene ventas pendientes con los datos del profesional y su sucursal.

    Retorna id_venta, total, nombre_farmaceutico (nombre y apellido), matricula
    y sucursal (objeto con todas sus propiedades), ordenados por id_venta.
    No filtra por actividad del farmacéutico ni de la sucursal.

    La sucursal se obtiene a través de TRABAJA_EN: corresponde a la asociación
    actual del profesional en la proyección, no a una ubicación histórica de venta.
    La sesión o transacción recibida pertenece al llamador y no se cierra aquí.
    """
    query = """
        MATCH (v:Venta)<-[:REGISTRO]-(f:Farmaceutico)-[:TRABAJA_EN]->(s:Sucursal)
        WHERE v.estado = $estado
        RETURN v.id_venta AS id_venta,
               v.total AS total_venta,
               trim(f.nombre + ' ' + coalesce(f.apellido, '')) AS nombre_farmaceutico,
               f.matricula AS matricula_farmaceutico,
               properties(s) AS sucursal
        ORDER BY id_venta
    """
    return session.run(query, estado=ESTADO_PENDIENTE).data()


if __name__ == "__main__":
    config = Config.from_env()
    driver = create_driver(config)
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            resultado = q02(session)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        driver.close()
