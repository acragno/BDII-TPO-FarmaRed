"""Integración de Q10 contra el Neo4j aislado de pruebas."""

from __future__ import annotations

import pytest

from src.db.neo4j import NEO4J_DATABASE
from src.queries.q10 import q10


@pytest.mark.integration
def test_q10_clientes_distintos_sin_filtrar_actividad_ni_estados(neo4j_test_driver) -> None:
    clientes = [
        {
            "id_cliente": "C2", "nombre": "Ana", "apellido": "Pérez",
            "dni": "12345678", "email": "ana@example.com", "telefono": "123",
            "ciudad": "La Plata", "provincia": "Buenos Aires",
            "obra_social": "OSDE", "nro_afiliado": "456", "activo": False,
        },
        {"id_cliente": "C1", "nombre": "Luis", "activo": True},
        {"id_cliente": "C3", "nombre": "Eva", "activo": True},
        {"id_cliente": "C4", "nombre": "Juan", "activo": True},
        {"id_cliente": "C5", "nombre": "Paz", "activo": True},
    ]
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("""
            CREATE (s1:Sucursal {id_sucursal: 'S1', activo: false})
            CREATE (s2:Sucursal {id_sucursal: 'S2', activo: true})
            CREATE (:Farmaceutico {id_farmaceutico: 'F1', activo: false})
                   -[:TRABAJA_EN]->(s1)
            CREATE (:Farmaceutico {id_farmaceutico: 'F2', activo: true})
                   -[:TRABAJA_EN]->(s1)
            CREATE (:Farmaceutico {id_farmaceutico: 'F3', activo: true})
                   -[:TRABAJA_EN]->(s2)
        """).consume()
        session.run("""
            UNWIND $clientes AS datos
            CREATE (c:Cliente) SET c = datos
        """, clientes=clientes).consume()
        session.run("""
            UNWIND [
                {id: 'V1', cliente: 'C2', profesional: 'F1', estado: 'Completada'},
                {id: 'V2', cliente: 'C2', profesional: 'F1', estado: 'Pendiente'},
                {id: 'V3', cliente: 'C2', profesional: 'F2', estado: 'Completada'},
                {id: 'V4', cliente: 'C1', profesional: 'F2', estado: 'Pendiente'},
                {id: 'V5', cliente: 'C3', profesional: 'F1', estado: 'Anulada'},
                {id: 'V6', cliente: 'C4', profesional: 'F3', estado: 'Completada'}
            ] AS row
            MATCH (c:Cliente {id_cliente: row.cliente})
            MATCH (f:Farmaceutico {id_farmaceutico: row.profesional})
            CREATE (c)-[:REALIZO]->(v:Venta {id_venta: row.id, estado: row.estado})
            CREATE (f)-[:REGISTRO]->(v)
        """).consume()

        with session.begin_transaction() as tx:
            assert q10(tx, "S1") == [
                {"cliente": clientes[1]},
                {"cliente": clientes[0]},
                {"cliente": clientes[2]},
            ]
        assert q10(session, "S2") == [{"cliente": clientes[3]}]
        assert q10(session, "NO_EXISTE") == []
        assert q10(session, "S1' OR true //") == []


@pytest.mark.integration
def test_q10_sucursal_sin_clientes_atendidos(neo4j_test_driver) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        assert q10(session, "S1") == []
        session.run("CREATE (:Sucursal {id_sucursal: 'S1'})").consume()
        assert q10(session, "S1") == []
        session.run("""
            MATCH (s:Sucursal {id_sucursal: 'S1'})
            CREATE (:Farmaceutico {id_farmaceutico: 'F1', activo: true})
                   -[:TRABAJA_EN]->(s)
        """).consume()
        assert q10(session, "S1") == []
