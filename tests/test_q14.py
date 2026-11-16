"""Integración de venta, FEFO, receta y outbox en una única transacción."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch

import pytest
from pymongo.errors import OperationFailure

from src.outbox import register_event
from src.queries.q14 import q14

pytestmark = pytest.mark.integration


@pytest.fixture
def sale_data(mongo_test_db):
    db = mongo_test_db
    now = db.command("hello")["localTime"]
    today = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    db["clientes"].insert_one({"_id": "C001", "activo": True})
    db["farmaceuticos"].insert_one({"_id": "F001", "activo": True, "id_sucursal": "S001"})
    db["sucursales"].insert_one({"_id": "S001", "tipo": "Farmacia"})
    db["productos"].insert_many([
        {"_id": "P001", "activo": True, "precio_unit": 100, "condicion_venta": "Bajo receta"},
        {"_id": "P002", "activo": True, "precio_unit": 350, "condicion_venta": "Venta libre"},
    ])
    db["stock_lotes"].insert_many([
        {"_id": lot, "id_producto": product, "id_sucursal": "S001", "unidades": units,
         "vencimiento": today + timedelta(days=1)}
        for lot, product, units in (("L001", "P001", 5), ("L002", "P002", 10))
    ])
    db["recetas"].insert_one({
        "_id": "R001", "id_cliente": "C001", "tipo": "Simple", "estado": "Vigente",
        "dispensas_realizadas": 0, "dispensas_autorizadas": 1, "proxima_dispensa": today,
    })
    sale = {
        "id_venta": "V001", "id_cliente": "C001", "id_farmaceutico": "F001",
        "id_receta": "R001", "fecha": today.date().isoformat(),
        "tipo": "Con receta", "medio_pago": "Efectivo",
        "items": [
            {"id_detalle": "D001", "id_producto": "P001", "cantidad": 1},
            {"id_detalle": "D002", "id_producto": "P001", "cantidad": 2},
        ],
    }
    return db, sale


@pytest.mark.parametrize("recipe_type,used,authorized,state", [
    ("Simple", 0, 1, "Completada"),
    ("Archivada", 0, 1, "Completada"),
    ("Tratamiento prolongado", 0, 3, "Vigente"),
    ("Tratamiento prolongado", 2, 3, "Completada"),
])
def test_sale_updates_recipe_once_and_emits_final_payload(sale_data, recipe_type, used, authorized, state):
    db, sale = sale_data
    original = deepcopy(sale)
    db["recetas"].update_one({"_id": "R001"}, {"$set": {
        "tipo": recipe_type, "dispensas_realizadas": used, "dispensas_autorizadas": authorized,
    }})
    created = q14(db, db.client, sale)
    assert sale == original
    assert created == db["ventas"].find_one({"_id": "V001"})
    assert created["total"] == 300 and created["estado"] == "Completada"
    assert all(item["precio_unit"] == 100 for item in created["items"])
    assert created["stock_aplicado"] is True
    assert created["lotes_consumidos"] == [{"id_lote": "L001", "id_producto": "P001", "cantidad": 3}]
    assert db["stock_lotes"].find_one({"_id": "L001"})["unidades"] == 2
    recipe = db["recetas"].find_one({"_id": "R001"})
    next_date = created["fecha"] + timedelta(days=30) if state == "Vigente" else None
    assert recipe["dispensas_realizadas"] == used + 1
    assert recipe["estado"] == state and recipe["proxima_dispensa"] == next_date
    event = db["outbox"].find_one()
    assert db["outbox"].count_documents({}) == 1
    assert event["type"] == "VentaCompletada" and event["entity_id"] == "V001"
    assert event["state"] == "Pending" and event["attempts"] == 0
    assert event["payload"] == {
        key: value for key, value in created.items()
        if key not in {"_id", "stock_aplicado", "lotes_consumidos"}
    } | {"receta": {"dispensas_realizadas": used + 1, "estado": state, "proxima_dispensa": next_date}}


def test_free_sale_does_not_change_recipe(sale_data):
    db, sale = sale_data
    before = db["recetas"].find_one()
    sale.pop("id_receta")
    sale["tipo"] = "Venta libre"
    sale["items"] = [{"id_detalle": "D001", "id_producto": "P002", "cantidad": 2}]
    assert q14(db, db.client, sale)["total"] == 700
    assert db["recetas"].find_one() == before
    assert "receta" not in db["outbox"].find_one()["payload"]


@pytest.mark.parametrize("failure", ["stock", "outbox"])
def test_failure_leaves_no_sale_recipe_stock_or_event_changes(sale_data, failure):
    db, sale = sale_data
    before = {name: list(db[name].find().sort("_id")) for name in ("stock_lotes", "recetas", "ventas", "outbox")}
    if failure == "stock":
        sale["items"].append({"id_detalle": "D003", "id_producto": "P002", "cantidad": 11})
        with pytest.raises(ValueError, match="insuficiente"):
            q14(db, db.client, sale)
    else:
        with patch("src.queries.q14.register_event", side_effect=RuntimeError("Falló outbox")):
            with pytest.raises(RuntimeError, match="Falló outbox"):
                q14(db, db.client, sale)
    for name, records in before.items():
        assert list(db[name].find().sort("_id")) == records


def test_transaction_retry_starts_from_clean_sale(sale_data):
    db, sale = sale_data
    attempts = 0

    def retry_first(db, *, event, session):
        nonlocal attempts
        register_event(db, event=event, session=session)
        attempts += 1
        if attempts == 1:
            raise OperationFailure("Conflicto transitorio", 112, {"errorLabels": ["TransientTransactionError"]})

    with patch("src.queries.q14.register_event", side_effect=retry_first):
        created = q14(db, db.client, sale)
    assert attempts == 2
    assert created == db["ventas"].find_one({"_id": "V001"})
    assert db["stock_lotes"].find_one({"_id": "L001"})["unidades"] == 2
    assert db["recetas"].find_one()["dispensas_realizadas"] == 1
    assert db["outbox"].count_documents({}) == 1


def test_concurrent_sales_cannot_use_same_final_dispense(sale_data):
    db, sale = sale_data
    sale["items"] = [{"id_detalle": "D001", "id_producto": "P001", "cantidad": 1}]

    def attempt(sale_id):
        try:
            q14(db, db.client, {**sale, "id_venta": sale_id})
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, ["V001", "V002"])) == [False, True]
    assert db["ventas"].count_documents({}) == db["outbox"].count_documents({}) == 1
    assert db["recetas"].find_one()["dispensas_realizadas"] == 1
    assert db["stock_lotes"].find_one({"_id": "L001"})["unidades"] == 4
