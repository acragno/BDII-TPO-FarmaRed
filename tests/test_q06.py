"""Integración de Q06 contra el Neo4j aislado de pruebas."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from neo4j.time import Date

from src.db.neo4j import NEO4J_DATABASE
from src.queries.q06 import q06


@pytest.mark.integration
def test_q06_filtros_limites_y_datos_completos(neo4j_test_driver) -> None:
    hoy = date(2026, 11, 15)
    cliente = {
        "id_cliente": "C1", "nombre": "Ana", "apellido": "Pérez",
        "dni": "12345678", "email": "ana@example.com", "telefono": "123",
        "ciudad": "La Plata", "provincia": "Buenos Aires",
        "obra_social": "OSDE", "nro_afiliado": "456", "activo": False,
    }
    base = {
        "id_cliente": "C1", "medico": "Dr. Díaz", "matricula_medico": "MP-123",
        "fecha_emision": Date(2026, 9, 1), "tipo": "Tratamiento prolongado",
        "dispensas_autorizadas": 3, "dispensas_realizadas": 1,
        "estado": "Vigente",
    }
    recetas = [
        {**base, "id_receta": "R2", "proxima_dispensa": Date(2026, 11, 14)},
        {**base, "id_receta": "R1", "proxima_dispensa": Date(2026, 11, 14)},
        {**base, "id_receta": "R0", "proxima_dispensa": Date(2026, 10, 1)},
        {**base, "id_receta": "HOY", "proxima_dispensa": hoy},
        {**base, "id_receta": "FUTURA", "proxima_dispensa": hoy + timedelta(days=1)},
        {**base, "id_receta": "SIN_FECHA"},
        {**base, "id_receta": "COMPLETADA", "estado": "Completada",
         "proxima_dispensa": hoy - timedelta(days=1)},
        {**base, "id_receta": "VENCIDA", "estado": "Vencida",
         "proxima_dispensa": hoy - timedelta(days=1)},
        {**base, "id_receta": "SIMPLE", "tipo": "Simple",
         "proxima_dispensa": hoy - timedelta(days=1)},
        {**base, "id_receta": "ARCHIVADA", "tipo": "Archivada",
         "proxima_dispensa": hoy - timedelta(days=1)},
    ]
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("CREATE (c:Cliente) SET c = $cliente", cliente=cliente).consume()
        session.run("""
            MATCH (c:Cliente {id_cliente: 'C1'})
            UNWIND $recetas AS datos
            CREATE (r:Receta) SET r = datos
            CREATE (c)-[:TIENE_RECETA]->(r)
        """, recetas=recetas).consume()
        session.run("""
            MATCH (c:Cliente)-[:TIENE_RECETA]->(r:Receta {id_receta: 'R1'})
            CREATE (c)-[:TIENE_RECETA]->(r)
        """).consume()

        with session.begin_transaction() as tx:
            assert q06(tx, hoy=hoy) == [
                {"receta": recetas[2], "cliente": cliente},
                {"receta": recetas[1], "cliente": cliente},
                {"receta": recetas[0], "cliente": cliente},
            ]
        assert q06(session, hoy=date(2026, 10, 1)) == []


@pytest.mark.integration
def test_q06_sin_recetas(neo4j_test_driver) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        assert q06(session) == []
        session.run("CREATE (:Cliente {id_cliente: 'C1', activo: true})").consume()
        assert q06(session) == []


@pytest.mark.integration
def test_q06_usa_fecha_actual_del_sistema(neo4j_test_driver) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("""
            CREATE (c:Cliente {id_cliente: 'C1', activo: true})
            CREATE (c)-[:TIENE_RECETA]->(r:Receta {id_receta: 'R1',
                tipo: 'Tratamiento prolongado', estado: 'Vigente',
                proxima_dispensa: $hoy - duration('P1D')})
            CREATE (c)-[:TIENE_RECETA]->(:Receta {id_receta: 'HOY',
                tipo: 'Tratamiento prolongado', estado: 'Vigente',
                proxima_dispensa: $hoy})
        """, hoy=date.today()).consume()
        resultado = q06(session)
        assert len(resultado) == 1
        assert resultado[0]["receta"]["id_receta"] == "R1"
        assert resultado[0]["cliente"] == {"id_cliente": "C1", "activo": True}
