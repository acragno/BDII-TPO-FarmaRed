"""Consulta 04: Clientes con más de una receta registrada (Neo4j)."""

from __future__ import annotations

import json
from typing import Any

from neo4j import Session, Transaction

from src.config import Config
from src.db.neo4j import NEO4J_DATABASE, create_driver


def q04(session: Session | Transaction) -> list[dict[str, Any]]:
    """Obtiene clientes con más de una receta distinta mediante Neo4j.

    Recibe una sesión o transacción del llamador, que no se cierra aquí.
    Retorna cliente (todas sus propiedades) y cantidad_recetas, ordenados por
    cantidad descendente e id_cliente ascendente como desempate.
    Cuenta cada receta una vez, sin filtrar su estado ni la actividad del cliente.
    Si ningún cliente tiene más de una receta, devuelve [].
    """
    query = """
        MATCH (c:Cliente)-[:TIENE_RECETA]->(r:Receta)
        WITH c, count(DISTINCT r) AS cantidad_recetas
        WHERE cantidad_recetas > 1
        RETURN properties(c) AS cliente, cantidad_recetas
        ORDER BY cantidad_recetas DESC, cliente.id_cliente
    """
    return session.run(query).data()


if __name__ == "__main__":
    config = Config.from_env()
    driver = create_driver(config)
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            resultado = q04(session)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        driver.close()
