"""Tests para la consulta Q11: Ingresos totales por farmacéutico en el mes actual."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest

from src.loaders.mongodb_loader import load_dataset
from src.loaders.validate import validate_data
from src.queries.q11 import q11
from tests.support import DATA_DIR


@pytest.mark.integration
def test_q11_dataset_real(mongo_test_db) -> None:
    """Test A: Verifica Q11 contra el dataset real usando inyección de fecha."""
    result = validate_data(DATA_DIR)
    assert result.ok, [str(issue) for issue in result.issues]

    load_dataset(mongo_test_db, result.records)

    # Identificar el mes con más ventas completadas en el dataset
    conteo_por_mes = defaultdict(int)
    for v in result.records["ventas"]:
        if v.get("estado") == "Completada":
            f = v["fecha"]
            conteo_por_mes[(f.year, f.month)] += 1

    año_top, mes_top = max(conteo_por_mes.keys(), key=lambda k: conteo_por_mes[k])
    ahora_inyectado = datetime(año_top, mes_top, 15, 12, 0, 0)

    # Cálculo esperado en Python puro para ese mes
    ingresos_por_farm = defaultdict(int)
    for v in result.records["ventas"]:
        f = v["fecha"]
        if v.get("estado") == "Completada" and f.year == año_top and f.month == mes_top:
            ingresos_por_farm[v["id_farmaceutico"]] += v["total"]

    esperado = sorted(ingresos_por_farm.items(), key=lambda x: (-x[1], x[0]))

    actual = q11(mongo_test_db, ahora=ahora_inyectado)
    actual_tuplas = [(f["id_farmaceutico"], f["ingresos"]) for f in actual]

    assert actual_tuplas == esperado
    for f in actual:
        assert "_id" not in f

    # Segunda aserción: mes sin ventas completadas devuelve []
    ahora_vacio = datetime(2030, 1, 15)
    assert q11(mongo_test_db, ahora=ahora_vacio) == []


@pytest.mark.integration
def test_q11_casos_borde(mongo_test_db) -> None:
    """Test B: Batería exhaustiva de casos borde en base limpia."""
    farmaceuticos = [
        {
            "_id": "F001",
            "id_farmaceutico": "F001",
            "nombre": "Mariana",
            "apellido": "Quiroga",
            "matricula": "MN-18041",
            "cargo": "Director Técnico",
            "id_sucursal": "S001",
            "activo": True,
        },
        {
            "_id": "F002",
            "id_farmaceutico": "F002",
            "nombre": "Sebastián",
            "apellido": "Ledesma",
            "matricula": "MN-18078",
            "cargo": "Farmacéutico",
            "id_sucursal": "S001",
            "activo": True,
        },
        {
            "_id": "F_INACTIVO",
            "id_farmaceutico": "F_INACTIVO",
            "nombre": "Lucas",
            "apellido": "Morales",
            "matricula": "MN-18999",
            "cargo": "Farmacéutico",
            "id_sucursal": "S001",
            "activo": False,
        },
        {
            "_id": "F_SOLO_PEND",
            "id_farmaceutico": "F_SOLO_PEND",
            "nombre": "Paula",
            "apellido": "Gómez",
            "matricula": "MN-18555",
            "cargo": "Farmacéutico",
            "id_sucursal": "S001",
            "activo": True,
        },
    ]
    mongo_test_db["farmaceuticos"].insert_many(farmaceuticos)

    # 1. Ventana de octubre 2026:
    # 2026-10-01 (entra), 2026-10-31 (entra), 2026-09-30 (no entra), 2026-11-01 (no entra)
    d_sep_30 = datetime(2026, 9, 30, 0, 0, 0, tzinfo=timezone.utc)
    d_oct_01 = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    d_oct_15 = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
    d_oct_31 = datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc)
    d_nov_01 = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)

    ventas = [
        # Fuera de rango inferior (30 de septiembre)
        {
            "_id": "V_SEP_30",
            "id_venta": "V_SEP_30",
            "id_farmaceutico": "F001",
            "total": 500,
            "estado": "Completada",
            "fecha": d_sep_30,
        },
        # Límite inferior (1 de octubre)
        {
            "_id": "V_OCT_01",
            "id_venta": "V_OCT_01",
            "id_farmaceutico": "F001",
            "total": 1000,
            "estado": "Completada",
            "fecha": d_oct_01,
        },
        # Mitad de mes (15 de octubre) del mismo farmacéutico (se suma)
        {
            "_id": "V_OCT_15",
            "id_venta": "V_OCT_15",
            "id_farmaceutico": "F001",
            "total": 2000,
            "estado": "Completada",
            "fecha": d_oct_15,
        },
        # Límite superior inclusivo del mes (31 de octubre)
        {
            "_id": "V_OCT_31",
            "id_venta": "V_OCT_31",
            "id_farmaceutico": "F002",
            "total": 3000,
            "estado": "Completada",
            "fecha": d_oct_31,
        },
        # Límite superior exclusivo (1 de noviembre: no debe entrar en octubre)
        {
            "_id": "V_NOV_01",
            "id_venta": "V_NOV_01",
            "id_farmaceutico": "F002",
            "total": 5000,
            "estado": "Completada",
            "fecha": d_nov_01,
        },
        # Estados no completados en el mes
        {
            "_id": "V_OCT_PEND",
            "id_venta": "V_OCT_PEND",
            "id_farmaceutico": "F_SOLO_PEND",
            "total": 9000,
            "estado": "Pendiente",
            "fecha": d_oct_15,
        },
        {
            "_id": "V_OCT_ANUL",
            "id_venta": "V_OCT_ANUL",
            "id_farmaceutico": "F_SOLO_PEND",
            "total": 9000,
            "estado": "Anulada",
            "fecha": d_oct_15,
        },
        # Farmacéutico inactivo con venta completada
        {
            "_id": "V_OCT_INACT",
            "id_venta": "V_OCT_INACT",
            "id_farmaceutico": "F_INACTIVO",
            "total": 1500,
            "estado": "Completada",
            "fecha": d_oct_15,
        },
        # Venta completada con farmacéutico inexistente
        {
            "_id": "V_OCT_FANTASMA",
            "id_venta": "V_OCT_FANTASMA",
            "id_farmaceutico": "F_INEXISTENTE",
            "total": 800,
            "estado": "Completada",
            "fecha": d_oct_15,
        },
    ]
    mongo_test_db["ventas"].insert_many(ventas)

    ahora_octubre = datetime(2026, 10, 15)
    resultado = q11(mongo_test_db, ahora=ahora_octubre)
    ids_obtenidos = [f["id_farmaceutico"] for f in resultado]

    # F001 sumó V_OCT_01 ($1000) + V_OCT_15 ($2000) = $3000 (V_SEP_30 de $500 quedó afuera)
    f001 = next(f for f in resultado if f["id_farmaceutico"] == "F001")
    assert f001["ingresos"] == 3000
    assert f001["activo"] is True

    # F002 sumó V_OCT_31 ($3000) (V_NOV_01 de $5000 quedó afuera)
    f002 = next(f for f in resultado if f["id_farmaceutico"] == "F002")
    assert f002["ingresos"] == 3000

    # Desempate determinista: F001 y F002 empatan en $3000 -> F001 antes que F002
    assert ids_obtenidos.index("F001") < ids_obtenidos.index("F002")

    # F_INACTIVO: aparece en el ranking conservando activo = False (no convertido a None por $ifNull)
    assert "F_INACTIVO" in ids_obtenidos
    f_inact = next(f for f in resultado if f["id_farmaceutico"] == "F_INACTIVO")
    assert f_inact["activo"] is False
    assert f_inact["ingresos"] == 1500

    # F_SOLO_PEND: solo tuvo ventas Pendiente y Anulada -> no aparece (sin ceros)
    assert "F_SOLO_PEND" not in ids_obtenidos

    # F_INEXISTENTE: venta con referencia rota aparece con campos en None
    assert "F_INEXISTENTE" in ids_obtenidos
    f_fantasma = next(f for f in resultado if f["id_farmaceutico"] == "F_INEXISTENTE")
    assert f_fantasma["nombre"] is None
    assert f_fantasma["apellido"] is None
    assert f_fantasma["matricula"] is None
    assert f_fantasma["activo"] is None
    assert f_fantasma["ingresos"] == 800

    # Verificación de que no hay _id
    assert all("_id" not in f for f in resultado)


@pytest.mark.integration
def test_q11_cambio_de_anio_diciembre(mongo_test_db) -> None:
    """Verifica el cálculo de ventana en diciembre (transición de año a enero siguiente)."""
    mongo_test_db["ventas"].delete_many({})
    mongo_test_db["farmaceuticos"].delete_many({})

    mongo_test_db["farmaceuticos"].insert_one({
        "_id": "F001",
        "id_farmaceutico": "F001",
        "nombre": "Mariana",
        "apellido": "Quiroga",
        "matricula": "MN-18041",
        "activo": True,
    })

    ventas = [
        {"_id": "V_NOV", "id_venta": "V_NOV", "id_farmaceutico": "F001", "total": 100, "estado": "Completada", "fecha": datetime(2026, 11, 30, 0, 0, 0, tzinfo=timezone.utc)},
        {"_id": "V_DIC", "id_venta": "V_DIC", "id_farmaceutico": "F001", "total": 500, "estado": "Completada", "fecha": datetime(2026, 12, 31, 0, 0, 0, tzinfo=timezone.utc)},
        {"_id": "V_ENE", "id_venta": "V_ENE", "id_farmaceutico": "F001", "total": 200, "estado": "Completada", "fecha": datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)},
    ]
    mongo_test_db["ventas"].insert_many(ventas)

    ahora_diciembre = datetime(2026, 12, 20)
    resultado = q11(mongo_test_db, ahora=ahora_diciembre)

    assert len(resultado) == 1
    assert resultado[0]["id_farmaceutico"] == "F001"
    assert resultado[0]["ingresos"] == 500


def test_q11_usa_now_del_servidor_sin_inyectar() -> None:
    """Verifica que sin inyectar 'ahora' el $match use $$NOW y no una fecha de Python."""

    class _FakeCollection:
        def __init__(self) -> None:
            self.pipelines: list[list[dict]] = []

        def aggregate(self, pipeline):
            self.pipelines.append(pipeline)
            return []

    class _FakeDB:
        def __init__(self) -> None:
            self.collection = _FakeCollection()

        def __getitem__(self, name: str) -> _FakeCollection:
            return self.collection

    fake_db = _FakeDB()
    assert q11(fake_db) == []  # type: ignore[arg-type]

    filtro = fake_db.collection.pipelines[0][0]["$match"]
    assert filtro["estado"] == "Completada"
    assert "fecha" not in filtro
    assert filtro["$expr"] == {
        "$and": [
            {"$eq": [{"$year": "$fecha"}, {"$year": "$$NOW"}]},
            {"$eq": [{"$month": "$fecha"}, {"$month": "$$NOW"}]},
        ]
    }

    # Con 'ahora' inyectado no se usa $$NOW: se filtra por rango explícito en UTC.
    fake_db.collection.pipelines.clear()
    q11(fake_db, ahora=datetime(2026, 10, 15))  # type: ignore[arg-type]
    filtro_inyectado = fake_db.collection.pipelines[0][0]["$match"]
    assert "$expr" not in filtro_inyectado
    assert filtro_inyectado["fecha"] == {
        "$gte": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "$lt": datetime(2026, 11, 1, tzinfo=timezone.utc),
    }


@pytest.mark.integration
def test_q11_conversion_utc(mongo_test_db) -> None:
    """Verifica que 'ahora' se interprete y convierta a UTC (sin aplicar UTC-3)."""
    mongo_test_db["ventas"].delete_many({})
    mongo_test_db["farmaceuticos"].delete_many({})

    mongo_test_db["farmaceuticos"].insert_one({
        "_id": "F001",
        "id_farmaceutico": "F001",
        "nombre": "Mariana",
        "apellido": "Quiroga",
        "matricula": "MN-18041",
        "activo": True,
    })

    # Venta de octubre y venta de noviembre
    ventas = [
        {"_id": "V_OCT", "id_venta": "V_OCT", "id_farmaceutico": "F001", "total": 1000, "estado": "Completada", "fecha": datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc)},
        {"_id": "V_NOV", "id_venta": "V_NOV", "id_farmaceutico": "F001", "total": 2000, "estado": "Completada", "fecha": datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)},
    ]
    mongo_test_db["ventas"].insert_many(ventas)

    # Naive se interpreta como UTC: 2026-10-15 pertenece a octubre.
    res_naive_oct = q11(mongo_test_db, ahora=datetime(2026, 10, 15))
    assert len(res_naive_oct) == 1
    assert res_naive_oct[0]["ingresos"] == 1000

    # 2026-11-01 01:00 UTC sigue siendo noviembre en UTC (antes era octubre en UTC-3).
    res_utc_nov = q11(
        mongo_test_db, ahora=datetime(2026, 11, 1, 1, 0, 0, tzinfo=timezone.utc)
    )
    assert len(res_utc_nov) == 1
    assert res_utc_nov[0]["ingresos"] == 2000

    # Aware en UTC-3 se convierte a UTC: 2026-10-31 23:00-03 = 2026-11-01 02:00 UTC.
    zona_utc_menos_3 = timezone(timedelta(hours=-3))
    res_aware_nov = q11(
        mongo_test_db,
        ahora=datetime(2026, 10, 31, 23, 0, 0, tzinfo=zona_utc_menos_3),
    )
    assert len(res_aware_nov) == 1
    assert res_aware_nov[0]["ingresos"] == 2000

    # La misma fecha aware, pero antes de la medianoche UTC, pertenece a octubre.
    res_aware_oct = q11(
        mongo_test_db,
        ahora=datetime(2026, 10, 31, 20, 0, 0, tzinfo=zona_utc_menos_3),
    )
    assert len(res_aware_oct) == 1
    assert res_aware_oct[0]["ingresos"] == 1000


@pytest.mark.integration
def test_q11_fecha_sistema_sin_inyectar(mongo_test_db) -> None:
    """Verifica que sin inyectar ahora se use $$NOW (mes actual del servidor MongoDB)."""
    mongo_test_db["ventas"].delete_many({})
    mongo_test_db["farmaceuticos"].delete_many({})

    mongo_test_db["farmaceuticos"].insert_one({
        "_id": "F_HOY",
        "id_farmaceutico": "F_HOY",
        "nombre": "Farmaceutico",
        "apellido": "Hoy",
        "matricula": "MN-99999",
        "activo": True,
    })

    # Fecha/hora actual del servidor MongoDB (misma referencia que evalúa $$NOW).
    server_time = mongo_test_db.command("hello")["localTime"]
    if server_time.tzinfo is None:
        server_time = server_time.replace(tzinfo=timezone.utc)

    # Venta en el mes actual del servidor y otra en el mes anterior (debe quedar afuera).
    if server_time.month == 1:
        mes_anterior = datetime(server_time.year - 1, 12, 15, tzinfo=timezone.utc)
    else:
        mes_anterior = datetime(
            server_time.year, server_time.month - 1, 15, tzinfo=timezone.utc
        )

    mongo_test_db["ventas"].insert_many([
        {
            "_id": "V_HOY",
            "id_venta": "V_HOY",
            "id_farmaceutico": "F_HOY",
            "total": 4500,
            "estado": "Completada",
            "fecha": server_time.replace(
                day=15, hour=12, minute=0, second=0, microsecond=0
            ),
        },
        {
            "_id": "V_MES_ANTERIOR",
            "id_venta": "V_MES_ANTERIOR",
            "id_farmaceutico": "F_HOY",
            "total": 9999,
            "estado": "Completada",
            "fecha": mes_anterior,
        },
    ])

    res = q11(mongo_test_db)
    assert len(res) == 1
    assert res[0]["id_farmaceutico"] == "F_HOY"
    assert res[0]["ingresos"] == 4500
