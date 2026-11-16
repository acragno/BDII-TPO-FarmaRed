"""Procesamiento, confirmación y reintentos del consumidor de outbox."""

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest
from neo4j.exceptions import ServiceUnavailable
from pymongo.errors import AutoReconnect

from src.outbox_worker import (
    completed_sale,
    delete_client,
    insert_client,
    process_batch,
    run_worker,
    update_client,
)


def event(index=0, event_type="InsertClient", payload=None):
    return {
        "_id": f"event-{index:03}",
        "entity_id": f"C{index:03}",
        "type": event_type,
        "created_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
        "payload": payload if payload is not None else {"nombre": "Ana", "activo": True},
        "state": "Pending",
        "attempts": 0,
    }


def outbox_with(events):
    records = deepcopy(events)
    outbox = MagicMock()
    cursor = outbox.find.return_value
    cursor.sort.return_value = cursor
    cursor.limit.side_effect = lambda limit: sorted(
        [row for row in records if row["state"] == "Pending"],
        key=lambda row: (row["created_at"], row["_id"]),
    )[:limit]

    def update(query, changes):
        row = next(row for row in records if row["_id"] == query["_id"])
        row.update(changes.get("$set", {}))
        for key, value in changes.get("$inc", {}).items():
            row[key] = row.get(key, 0) + value
        for key in changes.get("$unset", {}):
            row.pop(key, None)

    outbox.update_one.side_effect = update
    return outbox, records


def driver_with_transaction():
    driver = MagicMock()
    session = driver.session.return_value.__enter__.return_value
    tx = session.begin_transaction.return_value.__enter__.return_value
    return driver, tx


def test_empty_outbox_waits_without_accessing_neo4j():
    outbox, _ = outbox_with([])
    driver, _ = driver_with_transaction()
    stop = MagicMock()
    stop.is_set.side_effect = [False, True]

    run_worker(outbox, driver, stop)

    stop.wait.assert_called_once_with(1)
    driver.session.assert_not_called()


def test_200_pending_events_take_four_batches_without_pauses():
    outbox, records = outbox_with([event(index) for index in reversed(range(200))])
    driver, tx = driver_with_transaction()
    stop = MagicMock()
    stop.is_set.side_effect = [False] * 5 + [True]

    run_worker(outbox, driver, stop)

    assert outbox.find.call_count == 5  # Cuatro lotes y una lectura vacía.
    stop.wait.assert_called_once_with(1)
    assert tx.commit.call_count == 200
    assert all(row["state"] == "Processed" and row["attempts"] == 1 for row in records)
    assert [item.kwargs["id_cliente"] for item in tx.run.call_args_list] == [
        f"C{index:03}" for index in range(200)
    ]


def test_neo4j_failure_keeps_event_pending_and_does_not_advance():
    outbox, records = outbox_with([event(0), event(1)])
    driver, tx = driver_with_transaction()
    tx.run.side_effect = ServiceUnavailable("Neo4j no disponible")

    with pytest.raises(ServiceUnavailable):
        process_batch(outbox, driver)

    assert records[0]["state"] == "Pending"
    assert records[0]["attempts"] == 1
    assert "Neo4j no disponible" in records[0]["last_error"]
    assert records[1]["attempts"] == 0
    tx.commit.assert_not_called()

    tx.run.side_effect = None
    assert process_batch(outbox, driver) == 2
    assert [row["attempts"] for row in records] == [2, 1]
    assert all(row["state"] == "Processed" and "last_error" not in row for row in records)


def test_commit_failure_does_not_acknowledge_event():
    outbox, records = outbox_with([event()])
    driver, tx = driver_with_transaction()
    tx.commit.side_effect = ServiceUnavailable("Falló el commit")

    with pytest.raises(ServiceUnavailable):
        process_batch(outbox, driver)

    assert records[0]["state"] == "Pending"
    assert "processed_at" not in records[0]


def test_failed_mongo_acknowledgement_replays_the_event():
    outbox, records = outbox_with([event()])
    driver, tx = driver_with_transaction()
    update = outbox.update_one.side_effect

    def fail_ack(query, changes):
        if changes.get("$set", {}).get("state") == "Processed":
            raise AutoReconnect("Se perdió la confirmación")
        return update(query, changes)

    outbox.update_one.side_effect = fail_ack
    with pytest.raises(AutoReconnect):
        process_batch(outbox, driver)
    assert records[0]["state"] == "Pending"
    assert tx.commit.call_count == 1

    outbox.update_one.side_effect = update
    process_batch(outbox, driver)
    assert records[0]["state"] == "Processed"
    assert records[0]["attempts"] == 2
    assert tx.commit.call_count == 2
    assert all("MERGE" in item.args[0] for item in tx.run.call_args_list)


@pytest.mark.parametrize("error", [ServiceUnavailable("Neo4j"), AutoReconnect("Mongo"), ValueError("Evento")])
def test_backoff_caps_at_30_and_resets_after_success(error):
    stop = MagicMock()
    stop.is_set.side_effect = [False] * 9 + [True]
    with patch("src.outbox_worker.process_batch", side_effect=[error] * 6 + [1, error, 0]):
        run_worker(MagicMock(), MagicMock(), stop)

    assert stop.wait.call_args_list == [call(value) for value in (2, 4, 8, 16, 30, 30, 2, 1)]


def test_unknown_event_stays_pending_until_handler_exists():
    outbox, records = outbox_with([event(event_type="FutureEvent")])
    driver, _ = driver_with_transaction()

    with pytest.raises(ValueError, match="no soportado"):
        process_batch(outbox, driver)
    assert records[0]["state"] == "Pending"
    assert "FutureEvent" in records[0]["last_error"]
    driver.session.assert_not_called()


@pytest.mark.parametrize("handler", [update_client, delete_client])
def test_missing_neo4j_node_is_not_silently_acknowledged(handler):
    tx = MagicMock()
    tx.run.return_value.single.return_value = None
    with pytest.raises(ValueError, match="todavía no existe"):
        handler(tx, event())


def test_insert_removes_mongo_id_and_update_preserves_unsent_properties():
    tx = MagicMock()
    insert_client(tx, event(payload={"_id": "C000", "id_cliente": "C000", "nombre": "Ana"}))
    assert tx.run.call_args.kwargs["properties"] == {"id_cliente": "C000", "nombre": "Ana"}
    update_client(tx, event(payload={"email": "nuevo@example.com"}))
    assert tx.run.call_args.kwargs["properties"] == {"email": "nuevo@example.com"}
    assert "SET c += $properties" in tx.run.call_args.args[0]


def test_delete_is_logical_and_keeps_relationships():
    tx = MagicMock()
    delete_client(tx, event(payload={"id_cliente": "C000", "activo": False}))
    query = tx.run.call_args.args[0]
    assert "SET c.activo = false" in query
    assert "DELETE" not in query


def sale_event(with_recipe=False):
    payload = {
        "_id": "V001", "id_venta": "V001", "id_cliente": "C001",
        "id_farmaceutico": "F001", "fecha": datetime(2026, 11, 15, tzinfo=timezone.utc),
        "tipo": "Con receta" if with_recipe else "Venta libre",
        "medio_pago": "Efectivo", "total": 300, "estado": "Completada",
        "stock_aplicado": True, "lotes_consumidos": [{"id_lote": "L001", "cantidad": 3}],
        "items": [
            {"id_detalle": detail, "id_producto": "P001", "cantidad": quantity, "precio_unit": 100}
            for detail, quantity in (("D001", 1), ("D002", 2))
        ],
    }
    if with_recipe:
        payload["id_receta"] = "R001"
        payload["receta"] = {
            "_id": "R001", "dispensas_realizadas": 1,
            "estado": "Completada", "proxima_dispensa": None,
        }
    return {**event(event_type="VentaCompletada", payload=payload), "entity_id": "V001"}


@pytest.mark.parametrize("with_recipe", [False, True])
def test_sale_projects_only_graph_properties(with_recipe):
    tx = MagicMock()
    tx.run.return_value.single.return_value = {"proyectados": 2}
    created = sale_event(with_recipe)
    original = deepcopy(created)
    completed_sale(tx, created)

    properties = tx.run.call_args_list[0].kwargs["properties"]
    assert set(properties) == {"id_venta", "fecha", "tipo", "medio_pago", "total", "estado"}
    assert properties["fecha"] == created["payload"]["fecha"].date()
    assert tx.run.call_args_list[1].kwargs["items"] == created["payload"]["items"]
    assert tx.run.call_count == (3 if with_recipe else 2)
    if with_recipe:
        assert tx.run.call_args.kwargs["properties"] == {
            "dispensas_realizadas": 1, "estado": "Completada", "proxima_dispensa": None,
        }
    assert created == original


def test_sale_with_missing_product_keeps_event_pending():
    outbox, records = outbox_with([sale_event()])
    driver, tx = driver_with_transaction()
    tx.run.return_value.single.side_effect = [{"id_venta": "V001"}, {"proyectados": 0}]
    with pytest.raises(ValueError, match="producto"):
        process_batch(outbox, driver)
    tx.commit.assert_not_called()
    assert records[0]["state"] == "Pending"


@pytest.mark.integration
def test_sale_event_is_idempotent_and_completes_recipe(neo4j_test_driver):
    with neo4j_test_driver.session() as session:
        session.run(
            "CREATE (c:Cliente {id_cliente: 'C001'}), "
            "(:Farmaceutico {id_farmaceutico: 'F001'}), "
            "(:Producto {id_producto: 'P001'}), "
            "(r:Receta {id_receta: 'R001', estado: 'Vigente', dispensas_realizadas: 0, "
            "proxima_dispensa: date('2026-11-15')}), (c)-[:TIENE_RECETA]->(r)"
        ).consume()
        created = sale_event(with_recipe=True)
        session.execute_write(completed_sale, created)
        session.execute_write(completed_sale, created)
        record = session.run(
            "MATCH (v:Venta {id_venta: 'V001'}) "
            "RETURN properties(v) AS venta, "
            "COUNT { (:Cliente)-[:REALIZO]->(v) } AS clientes, "
            "COUNT { (:Farmaceutico)-[:REGISTRO]->(v) } AS farmaceuticos, "
            "COUNT { (v)-[:INCLUYE]->() } AS items, "
            "COUNT { (v)-[:UTILIZA]->() } AS recetas"
        ).single()
        assert record["clientes"] == record["farmaceuticos"] == record["recetas"] == 1
        assert record["items"] == 2
        assert set(record["venta"]) == {"id_venta", "fecha", "tipo", "medio_pago", "total", "estado"}
        recipe = session.run("MATCH (r:Receta) RETURN properties(r) AS receta").single()["receta"]
        assert recipe["estado"] == "Completada" and recipe["dispensas_realizadas"] == 1
        assert "proxima_dispensa" not in recipe


@pytest.mark.integration
def test_missing_sale_product_rolls_back_graph_changes(neo4j_test_driver):
    with neo4j_test_driver.session() as session:
        session.run(
            "CREATE (:Cliente {id_cliente: 'C001'}), "
            "(:Farmaceutico {id_farmaceutico: 'F001'})"
        ).consume()
        with pytest.raises(ValueError, match="producto"):
            session.execute_write(completed_sale, sale_event())
        assert session.run("MATCH (v:Venta) RETURN count(v) AS n").single()["n"] == 0


@pytest.mark.integration
def test_client_events_are_idempotent_in_neo4j(neo4j_test_driver):
    with neo4j_test_driver.session() as session:
        created = event(payload={"_id": "C000", "nombre": "Ana", "activo": True})
        session.execute_write(insert_client, created)
        session.execute_write(insert_client, created)
        session.run(
            "MATCH (c:Cliente {id_cliente: 'C000'}) "
            "CREATE (c)-[:REALIZO]->(:Venta {id_venta: 'V000'})"
        ).consume()
        changed = event(payload={"email": "nuevo@example.com"})
        session.execute_write(update_client, changed)
        session.execute_write(update_client, changed)
        session.execute_write(delete_client, event())
        session.execute_write(delete_client, event())
        record = session.run(
            "MATCH (c:Cliente {id_cliente: 'C000'}) "
            "RETURN properties(c) AS properties, "
            "COUNT { (c)-[:REALIZO]->() } AS ventas"
        ).single()
        assert record["properties"] == {
            "id_cliente": "C000", "nombre": "Ana", "activo": False,
            "email": "nuevo@example.com",
        }
        assert record["ventas"] == 1
        assert session.run("MATCH (c:Cliente) RETURN count(c) AS n").single()["n"] == 1
