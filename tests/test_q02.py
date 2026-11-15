"""Integración de Q02 contra el Neo4j aislado de pruebas."""

from __future__ import annotations

import pytest

from src.db.neo4j import NEO4J_DATABASE
from src.queries.q02 import q02


@pytest.mark.integration
def test_q02_pendientes_con_profesional_y_sucursal(neo4j_test_driver) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("""
                CREATE (s:Sucursal {id_sucursal: 'S1', nombre: 'Centro',
                                    direccion: 'Calle 123', activo: false})
                CREATE (f:Farmaceutico {id_farmaceutico: 'F1', nombre: 'Ana',
                                       apellido: 'Pérez', matricula: 'MN-123',
                                       activo: false})
                CREATE (f)-[:TRABAJA_EN]->(s)
                CREATE (a:Farmaceutico {id_farmaceutico: 'F2', nombre: 'Luis',
                                       apellido: 'Díaz', matricula: 'MN-456',
                                       activo: true})
                CREATE (a)-[:TRABAJA_EN]->(s)
                WITH f, a
                UNWIND [
                    {id: 'V02', estado: 'Pendiente', total: 200, profesional: 'F1'},
                    {id: 'V01', estado: 'Pendiente', total: 100, profesional: 'F2'},
                    {id: 'V03', estado: 'Completada', total: 300, profesional: 'F1'},
                    {id: 'V04', estado: 'Anulada', total: 400, profesional: 'F1'}
                ] AS row
                CREATE (v:Venta {
                    id_venta: row.id, estado: row.estado, total: row.total
                })
                WITH f, a, row, v
                WITH CASE row.profesional
                    WHEN 'F1' THEN f ELSE a
                END AS profesional, v
                CREATE (profesional)-[:REGISTRO]->(v)
            """).consume()

        sucursal = {
            "id_sucursal": "S1",
            "nombre": "Centro",
            "direccion": "Calle 123",
            "activo": False,
        }
        assert q02(session) == [
            {
                "id_venta": "V01",
                "total_venta": 100,
                "nombre_farmaceutico": "Luis Díaz",
                "matricula_farmaceutico": "MN-456",
                "sucursal": sucursal,
            },
            {
                "id_venta": "V02",
                "total_venta": 200,
                "nombre_farmaceutico": "Ana Pérez",
                "matricula_farmaceutico": "MN-123",
                "sucursal": sucursal,
            },
        ]


@pytest.mark.integration
def test_q02_sin_ventas_pendientes(neo4j_test_driver) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("""
            CREATE (s:Sucursal {id_sucursal: 'S1', nombre: 'Centro',
                                direccion: 'Calle 123', activo: true})
            CREATE (f:Farmaceutico {id_farmaceutico: 'F1', nombre: 'Ana',
                                    matricula: 'MN-123', activo: true})
            CREATE (f)-[:TRABAJA_EN]->(s)
            CREATE (v1:Venta {id_venta: 'V01', estado: 'Completada', total: 100})
            CREATE (v2:Venta {id_venta: 'V02', estado: 'Anulada', total: 200})
            CREATE (f)-[:REGISTRO]->(v1)
            CREATE (f)-[:REGISTRO]->(v2)
        """).consume()

        assert q02(session) == []