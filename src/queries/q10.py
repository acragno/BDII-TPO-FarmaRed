"""Consulta 10: Clientes atendidos en una sucursal determinada (Neo4j)."""

from __future__ import annotations

import argparse
import json
from typing import Any

from neo4j import Session, Transaction

from src.config import Config
from src.db.neo4j import NEO4J_DATABASE, create_driver


def q10(session: Session | Transaction, id_sucursal: str) -> list[dict[str, Any]]:
    """Obtiene clientes distintos atendidos en la sucursal indicada usando Neo4j.

    Recibe una sesión o transacción del llamador, que no se cierra aquí, y el
    id_sucursal a consultar. Sigue TRABAJA_EN, REGISTRO y REALIZO para encontrar
    los clientes de las ventas registradas por sus farmacéuticos.
    No filtra actividad del profesional, cliente o sucursal ni estado de venta.
    TRABAJA_EN representa la sucursal actual del profesional en la proyección.

    Retorna filas con cliente (todas sus propiedades), sin duplicados y ordenadas
    por id_cliente ascendente. Una sucursal inexistente o sin clientes atendidos
    devuelve [].
    """
    query = """
        MATCH (:Sucursal {id_sucursal: $id_sucursal})
              <-[:TRABAJA_EN]-(f:Farmaceutico)-[:REGISTRO]->(:Venta)
              <-[:REALIZO]-(c:Cliente)
        RETURN DISTINCT properties(c) AS cliente
        ORDER BY cliente.id_cliente
    """
    return session.run(query, id_sucursal=id_sucursal).data()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id_sucursal", help="Identificador de sucursal (ej. S001)")
    args = parser.parse_args()
    config = Config.from_env()
    driver = create_driver(config)
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            resultado = q10(session, args.id_sucursal)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        driver.close()
