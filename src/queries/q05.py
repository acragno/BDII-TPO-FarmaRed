"""Consulta 05: Farmacéuticos activos y ventas de los últimos 60 días (Neo4j)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from neo4j import Session, Transaction

from src.config import Config
from src.db.neo4j import NEO4J_DATABASE, create_driver


def q05(
    session: Session | Transaction, hoy: date | None = None,
) -> list[dict[str, Any]]:
    """Cuenta ventas distintas no anuladas para cada farmacéutico activo.

    Motor: Neo4j. Recibe una sesión o transacción del llamador y no la cierra.
    hoy permite fijar la fecha de referencia en pruebas; por defecto se obtiene
    del sistema mediante date.today(), sin convertir la zona horaria.
    La ventana abarca 60 fechas calendario incluyendo hoy:
    [hoy - 59 días, mañana). La proyección almacena Venta.fecha como Date.

    Retorna farmaceutico (todas sus propiedades) y cantidad_ventas, incluyendo
    cero si no tiene ventas o ninguna cumple el filtro. Cuentan pendientes y
    completadas. Ordena por cantidad descendente e id_farmaceutico ascendente
    como desempate. Sin profesionales activos, devuelve [].
    """
    if hoy is None:
        hoy = date.today()
    inicio = hoy - timedelta(days=59)
    fin = hoy + timedelta(days=1)
    query = """
        MATCH (f:Farmaceutico {activo: true})
        OPTIONAL MATCH (f)-[:REGISTRO]->(v:Venta)
        WHERE v.fecha >= $inicio AND v.fecha < $fin
          AND v.estado <> 'Anulada'
        WITH f, count(DISTINCT v) AS cantidad_ventas
        RETURN properties(f) AS farmaceutico, cantidad_ventas
        ORDER BY cantidad_ventas DESC, farmaceutico.id_farmaceutico
    """
    return session.run(query, inicio=inicio, fin=fin).data()


if __name__ == "__main__":
    config = Config.from_env()
    driver = create_driver(config)
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            resultado = q05(session)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        driver.close()
