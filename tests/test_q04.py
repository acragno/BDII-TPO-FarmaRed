"""Integración de Q04 contra el Neo4j aislado de pruebas."""

from __future__ import annotations

import pytest

from src.db.neo4j import NEO4J_DATABASE
from src.queries.q04 import q04


@pytest.mark.integration
def test_q04_cuenta_recetas_distintas_sin_filtrar(neo4j_test_driver) -> None:
    clientes = [
        {"id_cliente": "C2", "nombre": "Ana", "activo": False},
        {"id_cliente": "C1", "nombre": "Luis", "activo": True},
        {"id_cliente": "C3", "nombre": "Eva", "activo": True},
        {"id_cliente": "C4", "nombre": "Juan", "activo": True},
        {"id_cliente": "C5", "nombre": "Paz", "activo": True},
    ]
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("""
            UNWIND $clientes AS datos
            CREATE (c:Cliente) SET c = datos
        """, clientes=clientes).consume()
        session.run("""
            UNWIND [
                {cliente: 'C2', id: 'R21', estado: 'Vencida'},
                {cliente: 'C2', id: 'R22', estado: 'Completada'},
                {cliente: 'C1', id: 'R11', estado: 'Vigente'},
                {cliente: 'C1', id: 'R12', estado: 'Completada'},
                {cliente: 'C3', id: 'R31', estado: 'Vigente'},
                {cliente: 'C3', id: 'R32', estado: 'Vencida'},
                {cliente: 'C3', id: 'R33', estado: 'Completada'},
                {cliente: 'C4', id: 'R41', estado: 'Vigente'}
            ] AS row
            MATCH (c:Cliente {id_cliente: row.cliente})
            CREATE (r:Receta {id_receta: row.id, estado: row.estado})
            CREATE (c)-[:TIENE_RECETA]->(r)
        """).consume()
        # Una relación repetida no aumenta el conteo ni hace entrar a C4.
        session.run("""
            MATCH (c:Cliente)-[:TIENE_RECETA]->(r:Receta)
            WHERE c.id_cliente IN ['C2', 'C4']
            CREATE (c)-[:TIENE_RECETA]->(r)
        """).consume()
        # Varias ventas de una receta no representan recetas adicionales.
        session.run("""
            MATCH (r:Receta {id_receta: 'R41'})
            CREATE (:Venta {id_venta: 'V1'})-[:UTILIZA]->(r)
            CREATE (:Venta {id_venta: 'V2'})-[:UTILIZA]->(r)
        """).consume()

        with session.begin_transaction() as tx:
            assert q04(tx) == [
                {"cliente": clientes[2], "cantidad_recetas": 3},
                {"cliente": clientes[1], "cantidad_recetas": 2},
                {"cliente": clientes[0], "cantidad_recetas": 2},
            ]


@pytest.mark.integration
def test_q04_sin_clientes_con_mas_de_una_receta(neo4j_test_driver) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        assert q04(session) == []
        session.run("""
            CREATE (:Cliente {id_cliente: 'C0'})
            CREATE (c:Cliente {id_cliente: 'C1'})
            CREATE (c)-[:TIENE_RECETA]->(:Receta {id_receta: 'R1'})
        """).consume()
        assert q04(session) == []
