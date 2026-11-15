"""Consulta 12: Clientes sin ventas registradas en el último año (Neo4j)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from neo4j import Session, Transaction

from src.config import Config
from src.db.neo4j import NEO4J_DATABASE, create_driver

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")


def q12(
    session: Session | Transaction, hoy: date | None = None,
) -> list[dict[str, Any]]:
    """Obtiene en Neo4j los clientes sin ventas durante el último año calendario.

    Recibe una sesión o transacción del llamador y no la cierra. hoy es una fecha
    opcional para pruebas; por defecto se usa la fecha actual de Argentina.
    La ventana es [misma fecha del año anterior, mañana). Para el 29 de febrero
    se toma el 28 de febrero del año anterior. No equivale siempre a 365 días.

    Cualquier venta dentro del intervalo excluye al cliente, sin filtrar estados.
    Incluye clientes que nunca compraron y clientes inactivos. Las ventas futuras
    no los excluyen. Retorna cliente con todas sus propiedades, ordenado por
    id_cliente ascendente; sin coincidencias, devuelve [].
    """
    if hoy is None:
        hoy = datetime.now(ZONA_HORARIA).date()
    try:
        inicio = hoy.replace(year=hoy.year - 1)
    except ValueError:
        # El 29 de febrero no existe en el año anterior.
        inicio = hoy.replace(year=hoy.year - 1, day=28)
    fin = hoy + timedelta(days=1)
    query = """
        MATCH (c:Cliente)
        WHERE NOT EXISTS {
            MATCH (c)-[:REALIZO]->(v:Venta)
            WHERE v.fecha >= $inicio AND v.fecha < $fin
        }
        RETURN properties(c) AS cliente
        ORDER BY cliente.id_cliente
    """
    return session.run(query, inicio=inicio, fin=fin).data()


if __name__ == "__main__":
    config = Config.from_env()
    driver = create_driver(config)
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            resultado = q12(session)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        driver.close()
