"""Integración de Q03 contra el Neo4j aislado de pruebas."""

from __future__ import annotations

import pytest
from neo4j.time import Date

from src.db.neo4j import NEO4J_DATABASE
from src.queries.q03 import q03


@pytest.mark.integration
def test_q03_historial_completo_sin_duplicaciones(neo4j_test_driver) -> None:
    recetas = [
        {
            "id_receta": "RC2", "id_cliente": "C1", "medico": "Dra. Pérez",
            "matricula_medico": "MP-123", "fecha_emision": Date(2026, 7, 15),
            "tipo": "Tratamiento prolongado", "dispensas_autorizadas": 3,
            "dispensas_realizadas": 2, "proxima_dispensa": Date(2026, 9, 15),
            "estado": "Vigente",
        },
        {
            "id_receta": "RC1", "id_cliente": "C1", "medico": "Dr. Díaz",
            "matricula_medico": "MP-456", "fecha_emision": Date(2026, 7, 15),
            "tipo": "Simple", "dispensas_autorizadas": 1,
            "dispensas_realizadas": 0, "estado": "Vencida",
        },
    ]
    ventas = [
        {
            "id_venta": "V2", "id_cliente": "C1", "id_farmaceutico": "F1",
            "id_receta": "RC2", "fecha": Date(2026, 8, 15),
            "tipo": "Con receta", "medio_pago": "Obra social", "total": 200,
            "estado": "Pendiente",
        },
        {
            "id_venta": "V1", "id_cliente": "C1", "id_farmaceutico": "F1",
            "id_receta": "RC2", "fecha": Date(2026, 7, 15),
            "tipo": "Con receta", "medio_pago": "Obra social", "total": 100,
            "estado": "Completada",
        },
        {
            "id_venta": "V0", "id_cliente": "C1", "id_farmaceutico": "F2",
            "fecha": Date(2026, 7, 15), "tipo": "Venta libre",
            "medio_pago": "Efectivo", "total": 50, "estado": "Anulada",
        },
    ]
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("CREATE (:Cliente {id_cliente: 'C1', activo: false})").consume()
        session.run("""
            MATCH (c:Cliente {id_cliente: 'C1'})
            UNWIND $recetas AS datos
            CREATE (r:Receta) SET r = datos
            CREATE (c)-[:TIENE_RECETA]->(r)
        """, recetas=recetas).consume()
        session.run("""
            MATCH (c:Cliente {id_cliente: 'C1'})
            UNWIND $ventas AS datos
            CREATE (v:Venta) SET v = datos
            CREATE (c)-[:REALIZO]->(v)
        """, ventas=ventas).consume()
        session.run("""
            MATCH (v:Venta), (r:Receta {id_receta: 'RC2'})
            WHERE v.id_receta = r.id_receta
            CREATE (v)-[:UTILIZA]->(r)
        """).consume()
        session.run("""
            CREATE (c:Cliente {id_cliente: 'C2'})
            CREATE (c)-[:REALIZO]->(:Venta {id_venta: 'OTRA',
                fecha: date('2026-01-01')})
            CREATE (c)-[:TIENE_RECETA]->(:Receta {id_receta: 'OTRA',
                fecha_emision: date('2026-01-01')})
        """).consume()

        # Verifica también que la función acepte una transacción del llamador.
        with session.begin_transaction() as tx:
            actual = q03(tx, "C1")

    expected = []
    for tipo, campo_id, campo_fecha, documentos in [
        ("Receta", "id_receta", "fecha_emision", recetas),
        ("Venta", "id_venta", "fecha", ventas),
    ]:
        for documento in documentos:
            expected.append({
                "fecha": documento[campo_fecha], "tipo_evento": tipo,
                "id": documento[campo_id],
                "datos": {
                    k: v for k, v in documento.items()
                    if k not in {"id_cliente", campo_id, campo_fecha}
                },
            })
    expected.sort(key=lambda e: (e["fecha"], e["tipo_evento"], e["id"]))
    assert actual == expected


@pytest.mark.integration
@pytest.mark.parametrize("tipo", ["Venta", "Receta", "Vacio"])
def test_q03_historial_con_una_rama_vacia(neo4j_test_driver, tipo) -> None:
    with neo4j_test_driver.session(database=NEO4J_DATABASE) as session:
        session.run("CREATE (:Cliente {id_cliente: 'C1'})").consume()
        if tipo == "Venta":
            session.run("""
                MATCH (c:Cliente {id_cliente: 'C1'})
                CREATE (c)-[:REALIZO]->(:Venta {id_venta: 'V1',
                    fecha: date('2026-01-01')})
            """).consume()
        elif tipo == "Receta":
            session.run("""
                MATCH (c:Cliente {id_cliente: 'C1'})
                CREATE (c)-[:TIENE_RECETA]->(:Receta {id_receta: 'RC1',
                    fecha_emision: date('2026-01-01')})
            """).consume()

        actual = q03(session, "C1")
        assert [e["tipo_evento"] for e in actual] == (
            [] if tipo == "Vacio" else [tipo]
        )
        assert q03(session, "NO_EXISTE") == []
        assert q03(session, "C1' OR true //") == []
