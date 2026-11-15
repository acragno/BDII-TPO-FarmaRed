"""Integración de Q05 contra el Neo4j aislado de pruebas."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.db.neo4j import NEO4J_DATABASE
from src.queries.q05 import q05


@pytest.mark.integration
def test_q05_limites_estados_ceros_y_ventas_distintas(neo4j_test_driver) -> None:
    hoy = date(2026, 11, 15)
    profesionales = [
        {"id_farmaceutico": "F2", "nombre": "Ana", "activo": True},
        {"id_farmaceutico": "F1", "nombre": "Luis", "activo": True},
        {"id_farmaceutico": "F3", "nombre": "Eva", "activo": True},
        {"id_farmaceutico": "F4", "nombre": "Juan", "activo": False},
        {"id_farmaceutico": "F5", "nombre": "Paz", "activo": True},
    ]
    ventas = [
        {"id": "V1", "f": "F2", "fecha": hoy - timedelta(days=59), "estado": "Completada"},
        {"id": "V2", "f": "F2", "fecha": hoy, "estado": "Pendiente"},
        {"id": "V3", "f": "F2", "fecha": hoy - timedelta(days=60), "estado": "Completada"},
        {"id": "V4", "f": "F2", "fecha": hoy + timedelta(days=1), "estado": "Completada"},
        {"id": "V5", "f": "F2", "fecha": hoy, "estado": "Anulada"},
        {"id": "V6", "f": "F1", "fecha": hoy, "estado": "Completada"},
        {"id": "V7", "f": "F4", "fecha": hoy, "estado": "Completada"},
        {"id": "V8", "f": "F5", "fecha": hoy, "estado": "Anulada"},
        {"id": "V9", "f": "F5", "fecha": hoy - timedelta(days=60), "estado": "Pendiente"},
        {"id": "V10", "f": "F5", "fecha": hoy + timedelta(days=1), "estado": "Pendiente"},
    ]
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("""
            UNWIND $profesionales AS datos
            CREATE (f:Farmaceutico) SET f = datos
        """, profesionales=profesionales).consume()
        session.run("""
            UNWIND $ventas AS row
            MATCH (f:Farmaceutico {id_farmaceutico: row.f})
            CREATE (v:Venta {id_venta: row.id, fecha: row.fecha, estado: row.estado})
            CREATE (f)-[:REGISTRO]->(v)
        """, ventas=ventas).consume()
        session.run("""
            MATCH (f:Farmaceutico)-[:REGISTRO]->(v:Venta {id_venta: 'V1'})
            CREATE (f)-[:REGISTRO]->(v)
        """).consume()
        with session.begin_transaction() as tx:
            assert q05(tx, hoy=hoy) == [
                {"farmaceutico": profesionales[0], "cantidad_ventas": 2},
                {"farmaceutico": profesionales[1], "cantidad_ventas": 1},
                {"farmaceutico": profesionales[2], "cantidad_ventas": 0},
                {"farmaceutico": profesionales[4], "cantidad_ventas": 0},
            ]


@pytest.mark.integration
def test_q05_sin_profesionales_activos(neo4j_test_driver) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        assert q05(session) == []
        session.run("""
            CREATE (f:Farmaceutico {id_farmaceutico: 'F1', activo: false})
            CREATE (f)-[:REGISTRO]->(:Venta {id_venta: 'V1',
                fecha: date(), estado: 'Completada'})
        """).consume()
        assert q05(session) == []


@pytest.mark.integration
def test_q05_usa_fecha_actual_del_sistema(neo4j_test_driver) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("""
            CREATE (f:Farmaceutico {id_farmaceutico: 'F1', activo: true})
            CREATE (f)-[:REGISTRO]->(:Venta {id_venta: 'V1',
                fecha: $hoy, estado: 'Completada'})
        """, hoy=date.today()).consume()
        assert q05(session) == [{
            "farmaceutico": {"id_farmaceutico": "F1", "activo": True},
            "cantidad_ventas": 1,
        }]
