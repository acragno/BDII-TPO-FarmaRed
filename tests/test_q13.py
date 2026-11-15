"""Casos habituales y bordes del ABM, sobre MongoDB de pruebas."""

from unittest.mock import patch

import pytest
from pymongo.errors import DuplicateKeyError

from src.loaders.mongodb_loader import ensure_indexes
from src.queries.q13 import q13Delete, q13Insert, q13Update

pytestmark = pytest.mark.integration


@pytest.fixture
def cliente():
    return {
        "id_cliente": "C001", "nombre": "Ana", "apellido": "Perez",
        "dni": "12345678", "email": "ana@example.com", "telefono": "1145678900",
        "ciudad": "Buenos Aires", "provincia": "Buenos Aires",
        "obra_social": "OSDE", "nro_afiliado": "OS-123", "activo": True,
    }


@pytest.fixture
def db(mongo_test_db):
    ensure_indexes(mongo_test_db)
    return mongo_test_db


def test_alta_y_dni_unico(db, cliente):
    creado = q13Insert(db, db.client, cliente)
    assert creado == db["clientes"].find_one({"_id": "C001"})
    assert creado == {"_id": "C001", **cliente}
    evento = db["outbox"].find_one({"type": "InsertClient"})
    assert evento["payload"] == creado
    assert evento["entity_id"] == "C001" and evento["state"] == "Pending"

    with pytest.raises(DuplicateKeyError):
        q13Insert(db, db.client, {**cliente, "id_cliente": "C002"})
    assert db["clientes"].count_documents({}) == 1
    assert db["outbox"].count_documents({}) == 1


@pytest.mark.parametrize("cambios", [
    {"nombre": " "}, {"activo": "True"},
    {"obra_social": "Otra"}, {"nro_afiliado": ""},
])
def test_alta_invalida_no_deja_datos(db, cliente, cambios):
    with pytest.raises(ValueError):
        q13Insert(db, db.client, {**cliente, **cambios})
    assert db["clientes"].count_documents({}) == 0
    assert db["outbox"].count_documents({}) == 0


@pytest.mark.parametrize("cambios", [
    {"email": "nuevo@example.com"}, {"telefono": "1198765432"},
    {"obra_social": "PAMI"}, {"nro_afiliado": "AF-456"},
])
def test_modificacion_parcial_y_repetida(db, cliente, cambios):
    original = q13Insert(db, db.client, cliente)
    assert q13Update(db, db.client, "C001", cambios)["modificado"] is True
    assert db["clientes"].find_one({"_id": "C001"}) == {**original, **cambios}
    evento = db["outbox"].find_one({"type": "UpdateClient"})
    assert evento["payload"] == cambios and evento["entity_id"] == "C001"
    assert q13Update(db, db.client, "C001", cambios)["modificado"] is False
    assert db["outbox"].count_documents({}) == 2


@pytest.mark.parametrize("cambios", [
    {}, {"dni": "87654321"}, {"email": ""},
    {"telefono": None}, {"obra_social": "Otra"},
])
def test_modificacion_invalida_no_cambia_cliente(db, cliente, cambios):
    original = q13Insert(db, db.client, cliente)
    with pytest.raises(ValueError):
        q13Update(db, db.client, "C001", cambios)
    assert db["clientes"].find_one({"_id": "C001"}) == original
    assert db["outbox"].count_documents({}) == 1


def test_cobertura_valida_el_estado_resultante(db, cliente):
    cliente.pop("nro_afiliado")
    cliente["obra_social"] = "Sin cobertura"
    original = q13Insert(db, db.client, cliente)
    assert "nro_afiliado" not in original

    with pytest.raises(ValueError, match="solo puede estar vacío"):
        q13Update(db, db.client, "C001", {"obra_social": "OSDE"})
    assert db["clientes"].find_one({"_id": "C001"}) == original
    assert db["outbox"].count_documents({}) == 1

    cambios = {"obra_social": "OSDE", "nro_afiliado": "OS-456"}
    q13Update(db, db.client, "C001", cambios)
    with pytest.raises(ValueError, match="solo puede estar vacío"):
        q13Update(db, db.client, "C001", {"nro_afiliado": ""})
    assert db["clientes"].find_one({"_id": "C001"}) == {**original, **cambios}

    q13Update(db, db.client, "C001", {"obra_social": "Sin cobertura"})
    q13Update(db, db.client, "C001", {"nro_afiliado": ""})
    assert db["clientes"].find_one({"_id": "C001"}) == {**original, "nro_afiliado": ""}
    assert db["outbox"].count_documents({}) == 4


def test_baja_logica_y_repetida(db, cliente):
    original = q13Insert(db, db.client, cliente)
    assert q13Delete(db, db.client, "C001")["modificado"] is True
    assert db["clientes"].find_one({"_id": "C001"}) == {**original, "activo": False}
    evento = db["outbox"].find_one({"type": "DeleteClient"})
    assert evento["payload"] == {"id_cliente": "C001", "activo": False}
    assert q13Delete(db, db.client, "C001")["modificado"] is False
    assert db["outbox"].count_documents({}) == 2


@pytest.mark.parametrize("operacion, argumentos", [
    (q13Delete, ()), (q13Update, ({"email": "nuevo@example.com"},)),
])
def test_cliente_inexistente(db, operacion, argumentos):
    with pytest.raises(ValueError, match="No existe el cliente"):
        operacion(db, db.client, "INEXISTENTE", *argumentos)
    assert db["clientes"].count_documents({}) == 0
    assert db["outbox"].count_documents({}) == 0


@pytest.mark.parametrize("accion", ["alta", "modificacion", "baja"])
def test_error_outbox_revierte_la_operacion(db, cliente, accion):
    original = q13Insert(db, db.client, cliente)
    operaciones = {
        "alta": lambda: q13Insert(db, db.client, {**cliente, "id_cliente": "C002", "dni": "87654321"}),
        "modificacion": lambda: q13Update(db, db.client, "C001", {"email": "nuevo@example.com"}),
        "baja": lambda: q13Delete(db, db.client, "C001"),
    }
    with patch("src.queries.q13.register_event", side_effect=RuntimeError("Falló outbox")):
        with pytest.raises(RuntimeError, match="Falló outbox"):
            operaciones[accion]()
    assert list(db["clientes"].find()) == [original]
    assert db["outbox"].count_documents({}) == 1
