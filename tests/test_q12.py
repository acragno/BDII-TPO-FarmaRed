"""Integración de Q12 contra el Neo4j aislado de pruebas."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.db.neo4j import NEO4J_DATABASE
from src.queries.q12 import q12


@pytest.mark.integration
@pytest.mark.parametrize(("hoy", "inicio"), [
    (date(2026, 11, 15), date(2025, 11, 15)),
    (date(2024, 2, 29), date(2023, 2, 28)),
    (date(2025, 2, 28), date(2024, 2, 28)),
])
def test_q12_intervalo_anual_estados_y_clientes_sin_compras(
    neo4j_test_driver, hoy, inicio,
) -> None:
    clientes = [
        {"id_cliente": "C2", "nombre": "Ana", "activo": True},
        {"id_cliente": "C1", "nombre": "Luis", "activo": True},
        {
            "id_cliente": "C3", "nombre": "Eva", "apellido": "Pérez",
            "dni": "12345678", "email": "eva@example.com", "telefono": "123",
            "ciudad": "La Plata", "provincia": "Buenos Aires",
            "obra_social": "OSDE", "nro_afiliado": "456", "activo": False,
        },
        {"id_cliente": "C4", "activo": True},
        {"id_cliente": "C5", "activo": True},
        {"id_cliente": "C6", "activo": True},
        {"id_cliente": "C7", "activo": True},
        {"id_cliente": "C8", "activo": True},
    ]
    ventas = [
        {"id": "V1", "cliente": "C1", "fecha": inicio - timedelta(days=1), "estado": "Completada"},
        {"id": "V2", "cliente": "C4", "fecha": inicio, "estado": "Completada"},
        {"id": "V3", "cliente": "C5", "fecha": hoy, "estado": "Pendiente"},
        {"id": "V4", "cliente": "C6", "fecha": hoy, "estado": "Anulada"},
        {"id": "V5", "cliente": "C7", "fecha": hoy + timedelta(days=1), "estado": "Completada"},
        {"id": "V6", "cliente": "C8", "fecha": inicio - timedelta(days=1), "estado": "Completada"},
        {"id": "V7", "cliente": "C8", "fecha": hoy, "estado": "Completada"},
    ]
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("""
            UNWIND $clientes AS datos
            CREATE (c:Cliente) SET c = datos
        """, clientes=clientes).consume()
        session.run("""
            UNWIND $ventas AS row
            MATCH (c:Cliente {id_cliente: row.cliente})
            CREATE (c)-[:REALIZO]->(:Venta {
                id_venta: row.id, fecha: row.fecha, estado: row.estado})
        """, ventas=ventas).consume()
        with session.begin_transaction() as tx:
            assert q12(tx, hoy=hoy) == [
                {"cliente": clientes[1]},
                {"cliente": clientes[0]},
                {"cliente": clientes[2]},
                {"cliente": clientes[6]},
            ]


@pytest.mark.integration
def test_q12_sin_coincidencias_y_fecha_actual(neo4j_test_driver) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        assert q12(session) == []
        session.run("""
            CREATE (c:Cliente {id_cliente: 'C1'})
            CREATE (c)-[:REALIZO]->(:Venta {id_venta: 'V1', estado: 'Anulada',
                fecha: $hoy})
        """, hoy=date.today()).consume()
        assert q12(session) == []
