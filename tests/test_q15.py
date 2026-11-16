"""FEFO, idempotencia y rollback sobre transacciones reales de MongoDB."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.queries.q15 import q15


def test_requires_active_transaction():
    session = MagicMock(in_transaction=False)
    db = MagicMock()
    with pytest.raises(ValueError, match="transacción activa"):
        q15(db, "V001", session=session)
    db.__getitem__.assert_not_called()


@pytest.fixture
def stock_db(mongo_test_db):
    db = mongo_test_db
    server_now = db.command("hello")["localTime"].replace(tzinfo=timezone.utc)
    today = datetime.combine(server_now.date(), time.min, tzinfo=timezone.utc)
    db["farmaceuticos"].insert_one({"_id": "F001", "id_sucursal": "S001"})
    db["ventas"].insert_one({
        "_id": "V001", "estado": "Completada", "id_farmaceutico": "F001",
        "items": [{"id_producto": "P001", "cantidad": 2}, {"id_producto": "P001", "cantidad": 3}],
    })
    db["stock_lotes"].insert_many([
        {"_id": lot_id, "id_producto": "P001", "id_sucursal": branch,
         "unidades": units, "vencimiento": today + timedelta(days=days)}
        for lot_id, branch, units, days in (
            ("L-vencido", "S001", 100, -1),
            ("L-otra", "S002", 100, 0),
            ("L002", "S001", 3, 0),
            ("L001", "S001", 3, 0),
            ("L003", "S001", 10, 1),
        )
    ])
    return db


def apply_stock(db, sale_id="V001"):
    with db.client.start_session() as session:
        return session.with_transaction(lambda tx: q15(db, sale_id, session=tx))


@pytest.mark.integration
def test_fefo_groups_items_and_skips_expired_and_other_branches(stock_db):
    db = stock_db
    consumed = apply_stock(db)
    assert consumed == [
        {"id_lote": "L001", "id_producto": "P001", "cantidad": 3},
        {"id_lote": "L002", "id_producto": "P001", "cantidad": 2},
    ]
    units = {lot["_id"]: lot["unidades"] for lot in db["stock_lotes"].find()}
    assert units == {"L-vencido": 100, "L-otra": 100, "L001": 0, "L002": 1, "L003": 10}
    assert apply_stock(db) == consumed
    assert {lot["_id"]: lot["unidades"] for lot in db["stock_lotes"].find()} == units
    sale = db["ventas"].find_one({"_id": "V001"})
    assert sale["stock_aplicado"] is True and sale["lotes_consumidos"] == consumed
    assert db["outbox"].count_documents({}) == 0


@pytest.mark.integration
def test_fefo_spans_later_expiry_when_needed(stock_db):
    db = stock_db
    db["ventas"].update_one({"_id": "V001"}, {"$set": {"items": [{"id_producto": "P001", "cantidad": 8}]}})
    consumed = apply_stock(db)
    assert [row["cantidad"] for row in consumed] == [3, 3, 2]
    assert [row["id_lote"] for row in consumed] == ["L001", "L002", "L003"]


@pytest.mark.integration
def test_shortage_rolls_back_new_sale_and_recipe(stock_db):
    db = stock_db
    before = list(db["stock_lotes"].find().sort("_id"))
    db["recetas"].insert_one({"_id": "R001", "dispensas_realizadas": 0})
    sale = db["ventas"].find_one({"_id": "V001"})
    sale["_id"] = "V002"
    sale["items"].append({"id_producto": "P002", "cantidad": 1})

    def callback(session):
        db["ventas"].insert_one(sale, session=session)
        db["recetas"].update_one({"_id": "R001"}, {"$inc": {"dispensas_realizadas": 1}}, session=session)
        q15(db, "V002", session=session)

    with db.client.start_session() as session:
        with pytest.raises(ValueError, match="insuficiente.*P002"):
            session.with_transaction(callback)
    assert db["ventas"].find_one({"_id": "V002"}) is None
    assert db["recetas"].find_one({"_id": "R001"})["dispensas_realizadas"] == 0
    assert list(db["stock_lotes"].find().sort("_id")) == before


@pytest.mark.integration
def test_abort_after_discount_restores_stock_and_marker(stock_db):
    db = stock_db
    before = list(db["stock_lotes"].find().sort("_id"))

    def callback(session):
        q15(db, "V001", session=session)
        raise RuntimeError("Falló un paso posterior")

    with db.client.start_session() as session:
        with pytest.raises(RuntimeError):
            session.with_transaction(callback)
    assert list(db["stock_lotes"].find().sort("_id")) == before
    assert "stock_aplicado" not in db["ventas"].find_one({"_id": "V001"})


@pytest.mark.integration
@pytest.mark.parametrize("state", ["Pendiente", "Anulada"])
def test_only_completed_sales_discount_stock(stock_db, state):
    stock_db["ventas"].update_one({"_id": "V001"}, {"$set": {"estado": state}})
    with pytest.raises(ValueError, match="Completada"):
        apply_stock(stock_db)


@pytest.mark.integration
@pytest.mark.parametrize("same_sale", [False, True])
def test_concurrent_sales_never_make_stock_negative(stock_db, same_sale):
    db = stock_db
    # Solo queda un lote vigente con tres unidades para dos ventas de dos unidades.
    db["stock_lotes"].update_many({}, {"$set": {"unidades": 0}})
    db["stock_lotes"].update_one({"_id": "L001"}, {"$set": {"unidades": 3}})
    sale = db["ventas"].find_one({"_id": "V001"})
    sale["items"] = [{"id_producto": "P001", "cantidad": 2}]
    db["ventas"].replace_one({"_id": "V001"}, sale)
    db["ventas"].insert_one({**sale, "_id": "V002"})

    def attempt(sale_id):
        try:
            apply_stock(db, sale_id)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        sale_ids = ["V001", "V001" if same_sale else "V002"]
        assert sorted(executor.map(attempt, sale_ids)) == ([True, True] if same_sale else [False, True])
    assert db["stock_lotes"].find_one({"_id": "L001"})["unidades"] == 1
    assert db["ventas"].count_documents({"stock_aplicado": True}) == 1
