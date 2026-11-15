"""Consulta 03: Historial cronológico de ventas y recetas de un cliente."""

from __future__ import annotations

import argparse
import json
from typing import Any

from neo4j import Session, Transaction

from src.config import Config
from src.db.neo4j import NEO4J_DATABASE, create_driver


def q03(session: Session | Transaction, id_cliente: str) -> list[dict[str, Any]]:
    """Retorna eventos con fecha, tipo_evento, id y datos sin id_cliente.

    Incluye todas las ventas y recetas, sin filtrar estados ni actividad del
    cliente. Ordena por fecha de venta o emisión, tipo_evento e id ascendentes.
    Cada receta aparece una vez, aunque no tenga ventas o se utilice en varias.
    Si el cliente no existe o no tiene historial, devuelve [].

    datos omite id_cliente y los campos ya expuestos como fecha e id:
    fecha e id_venta para ventas, fecha_emision e id_receta para recetas.
    Conserva el resto de las propiedades, incluido id_receta en las ventas.
    Las ventas contienen su cabecera, sin el detalle opcional (INCLUYE).
    Los campos nulos no se almacenan como propiedades en Neo4j y se omiten.
    La sesión o transacción pertenece al llamador y no se cierra aquí.
    """
    query = """
        CALL () {
            MATCH (:Cliente {id_cliente: $id_cliente})-[:REALIZO]->(v:Venta)
            RETURN v.fecha AS fecha, 'Venta' AS tipo_evento,
                   v.id_venta AS id, properties(v) AS datos
            UNION ALL
            MATCH (:Cliente {id_cliente: $id_cliente})-[:TIENE_RECETA]->(r:Receta)
            RETURN r.fecha_emision AS fecha, 'Receta' AS tipo_evento,
                   r.id_receta AS id, properties(r) AS datos
        }
        RETURN fecha, tipo_evento, id, datos
        ORDER BY fecha, tipo_evento, id
    """
    eventos = session.run(query, id_cliente=id_cliente).data()
    for evento in eventos:
        evento["datos"].pop("id_cliente", None)
        if evento["tipo_evento"] == "Venta":
            evento["datos"].pop("fecha", None)
            evento["datos"].pop("id_venta", None)
        else:
            evento["datos"].pop("fecha_emision", None)
            evento["datos"].pop("id_receta", None)
    return eventos


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id_cliente", help="Identificador del cliente (ej. C001)")
    args = parser.parse_args()
    config = Config.from_env()
    driver = create_driver(config)
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            resultado = q03(session, args.id_cliente)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    finally:
        driver.close()
