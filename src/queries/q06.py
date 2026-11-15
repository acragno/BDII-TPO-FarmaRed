"""Consulta 06: Tratamientos prolongados con próxima dispensa atrasada (Neo4j)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from neo4j import Session, Transaction

from src.config import Config
from src.db.neo4j import NEO4J_DATABASE, create_driver


def q06(
    session: Session | Transaction, hoy: date | None = None,
) -> list[dict[str, Any]]:
    """Obtiene recetas vigentes de tratamiento prolongado con dispensa atrasada.

    Motor: Neo4j. Recibe una sesión o transacción del llamador y no la cierra.
    hoy permite fijar la fecha de referencia en pruebas; por defecto se obtiene
    del sistema mediante date.today(), sin convertir la zona horaria.
    Exige proxima_dispensa no nula y estrictamente anterior a hoy: las dispensas
    previstas para hoy no están atrasadas. No filtra la actividad del cliente.

    Retorna receta y cliente, ambos con todas sus propiedades. La próxima fecha
    aparece dentro de receta, sin repetirla fuera del objeto. Ordena por próxima
    dispensa ascendente e id_receta como desempate. Sin coincidencias, devuelve [].
    """
    if hoy is None:
        hoy = date.today()
    query = """
        MATCH (c:Cliente)-[:TIENE_RECETA]->(r:Receta)
        WHERE r.tipo = 'Tratamiento prolongado'
          AND r.estado = 'Vigente'
          AND r.proxima_dispensa IS NOT NULL
          AND r.proxima_dispensa < $hoy
        RETURN DISTINCT properties(r) AS receta, properties(c) AS cliente
        ORDER BY receta.proxima_dispensa, receta.id_receta
    """
    return session.run(query, hoy=hoy).data()


if __name__ == "__main__":
    config = Config.from_env()
    driver = create_driver(config)
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            resultado = q06(session)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        driver.close()
