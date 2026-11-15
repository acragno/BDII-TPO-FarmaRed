"""Tests para la consulta Q07: Top 5 productos más vendidos."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import pytest

from src.loaders.mongodb_loader import load_dataset
from src.loaders.validate import validate_data
from src.queries.q07 import TOP_N, q07
from tests.support import DATA_DIR


@pytest.mark.integration
def test_q07_dataset_real(mongo_test_db) -> None:
    """Test A: Verifica Q07 contra el dataset real cargado en MongoDB."""
    result = validate_data(DATA_DIR)
    assert result.ok, [str(issue) for issue in result.issues]

    load_dataset(mongo_test_db, result.records)

    # Identificar ventas completadas desde result.records["ventas"]
    ventas_completadas_ids = {
        v["id_venta"]
        for v in result.records["ventas"]
        if v.get("estado") == "Completada"
    }

    # Sumar cantidades con Counter uniendo con detalle_ventas (sin usar items)
    conteo_unidades = Counter()
    for detalle in result.records["detalle_ventas"]:
        if detalle["id_venta"] in ventas_completadas_ids:
            conteo_unidades[detalle["id_producto"]] += detalle["cantidad"]

    # Ordenar por (-unidades, id_producto) y tomar el top 5
    ranking_esperado = sorted(
        conteo_unidades.items(), key=lambda x: (-x[1], x[0])
    )[:TOP_N]

    productos_map = {
        p["id_producto"]: p["nombre"] for p in result.records["productos"]
    }

    actual = q07(mongo_test_db)

    assert len(actual) == len(ranking_esperado)

    actual_tuplas = [(p["id_producto"], p["unidades"]) for p in actual]
    assert actual_tuplas == ranking_esperado

    for p in actual:
        assert "_id" not in p
        assert p["nombre"] == productos_map[p["id_producto"]]


@pytest.mark.integration
def test_q07_casos_borde(mongo_test_db) -> None:
    """Test B: Casos borde armados a mano en base limpia."""
    fecha = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)

    # Catálogo de productos:
    # - P_TOP: activo
    # - P_INACTIVO: activo = False (debe figurar si se vendió)
    # - P1..P6: para pruebas de ranking y empates
    # - P_FANTASMA: no existe en la colección de productos
    productos = [
        {"_id": "P_TOP", "id_producto": "P_TOP", "nombre": "Producto Top", "activo": True},
        {"_id": "P_INACTIVO", "id_producto": "P_INACTIVO", "nombre": "Producto Inactivo", "activo": False},
        {"_id": "P1", "id_producto": "P1", "nombre": "Producto 1", "activo": True},
        {"_id": "P2", "id_producto": "P2", "nombre": "Producto 2", "activo": True},
        {"_id": "P3", "id_producto": "P3", "nombre": "Producto 3", "activo": True},
        {"_id": "P4", "id_producto": "P4", "nombre": "Producto 4", "activo": True},
        {"_id": "P5_A", "id_producto": "P5_A", "nombre": "Producto 5A", "activo": True},
        {"_id": "P5_B", "id_producto": "P5_B", "nombre": "Producto 5B", "activo": True},
        {"_id": "P_EXPENSIVE", "id_producto": "P_EXPENSIVE", "nombre": "Producto Caro", "activo": True},
        {"_id": "P_CHEAP", "id_producto": "P_CHEAP", "nombre": "Producto Barato", "activo": True},
    ]
    mongo_test_db["productos"].insert_many(productos)

    # Caso 1: Sin ventas completadas devuelve []
    assert q07(mongo_test_db) == []

    # Caso 2: Menos de 5 productos con ventas completadas (ej. 3 productos)
    mongo_test_db["ventas"].insert_many([
        {
            "_id": "V_TRES_1",
            "id_venta": "V_TRES_1",
            "estado": "Completada",
            "fecha": fecha,
            "items": [
                {"id_detalle": "D1", "id_producto": "P1", "cantidad": 10, "precio_unit": 100},
                {"id_detalle": "D2", "id_producto": "P2", "cantidad": 5, "precio_unit": 100},
                {"id_detalle": "D3", "id_producto": "P3", "cantidad": 2, "precio_unit": 100},
            ],
        }
    ])
    res_tres = q07(mongo_test_db)
    assert len(res_tres) == 3
    assert [p["id_producto"] for p in res_tres] == ["P1", "P2", "P3"]

    # Limpiar ventas para el escenario completo de casos borde
    mongo_test_db["ventas"].delete_many({})

    # Escenario completo con múltiples ventas:
    # 1. P_NON_COMPLETED: 100 unidades en Pendiente y 100 en Anulada -> 0 en Completada (no entra)
    # 2. P_MULTI: repartido en 2 ventas completadas y 2 ítems en una misma venta:
    #    Venta 1: 5 u. + 3 u. (dos items) = 8 u.
    #    Venta 2: 7 u. = total 15 u.
    # 3. P_CHEAP vs P_EXPENSIVE (unidades vs cantidad de ventas vs ingresos):
    #    P_CHEAP: 1 venta de 10 u. a $100 (total $1.000, 1 venta, 10 unidades)
    #    P_EXPENSIVE: 3 ventas de 2 u. a $10.000 (total $60.000, 3 ventas, 6 unidades)
    #    -> P_CHEAP debe quedar arriba de P_EXPENSIVE por tener 10 > 6 unidades
    # 4. P_FANTASMA: producto no existente en 'productos', con 4 unidades -> entra con nombre: None
    # 5. P_INACTIVO: producto con activo: False con 3 unidades -> entra al ranking
    # 6. Empate en el 5.º puesto con 2 productos (P5_A y P5_B) que tienen 2 unidades cada uno:
    #    Insertados fuera de orden para verificar que se desempata por id_producto ascendente (P5_A entra, P5_B queda afuera)
    ventas_escenario = [
        # Ventas no completadas (no deben sumar)
        {
            "_id": "V_PEND",
            "id_venta": "V_PEND",
            "estado": "Pendiente",
            "fecha": fecha,
            "items": [{"id_detalle": "D_P1", "id_producto": "P_TOP", "cantidad": 100, "precio_unit": 10}],
        },
        {
            "_id": "V_ANUL",
            "id_venta": "V_ANUL",
            "estado": "Anulada",
            "fecha": fecha,
            "items": [{"id_detalle": "D_A1", "id_producto": "P_TOP", "cantidad": 100, "precio_unit": 10}],
        },
        # P_MULTI repartido en dos ventas y en dos ítems de una misma venta
        {
            "_id": "V_MULTI_1",
            "id_venta": "V_MULTI_1",
            "estado": "Completada",
            "fecha": fecha,
            "items": [
                {"id_detalle": "D_M1", "id_producto": "P1", "cantidad": 5, "precio_unit": 10},
                {"id_detalle": "D_M2", "id_producto": "P1", "cantidad": 3, "precio_unit": 10},
            ],
        },
        {
            "_id": "V_MULTI_2",
            "id_venta": "V_MULTI_2",
            "estado": "Completada",
            "fecha": fecha,
            "items": [
                {"id_detalle": "D_M3", "id_producto": "P1", "cantidad": 7, "precio_unit": 10},
            ],
        },
        # P_CHEAP: 1 venta, 10 unidades, precio bajo
        {
            "_id": "V_CHEAP",
            "id_venta": "V_CHEAP",
            "estado": "Completada",
            "fecha": fecha,
            "items": [{"id_detalle": "D_C1", "id_producto": "P_CHEAP", "cantidad": 10, "precio_unit": 10}],
        },
        # P_EXPENSIVE: 3 ventas de 2 unidades, precio alto
        {
            "_id": "V_EXP_1",
            "id_venta": "V_EXP_1",
            "estado": "Completada",
            "fecha": fecha,
            "items": [{"id_detalle": "D_E1", "id_producto": "P_EXPENSIVE", "cantidad": 2, "precio_unit": 1000}],
        },
        {
            "_id": "V_EXP_2",
            "id_venta": "V_EXP_2",
            "estado": "Completada",
            "fecha": fecha,
            "items": [{"id_detalle": "D_E2", "id_producto": "P_EXPENSIVE", "cantidad": 2, "precio_unit": 1000}],
        },
        {
            "_id": "V_EXP_3",
            "id_venta": "V_EXP_3",
            "estado": "Completada",
            "fecha": fecha,
            "items": [{"id_detalle": "D_E3", "id_producto": "P_EXPENSIVE", "cantidad": 2, "precio_unit": 1000}],
        },
        # P_FANTASMA (inexistente en catalogo): 4 unidades
        {
            "_id": "V_FANTASMA",
            "id_venta": "V_FANTASMA",
            "estado": "Completada",
            "fecha": fecha,
            "items": [{"id_detalle": "D_F1", "id_producto": "P_FANTASMA", "cantidad": 4, "precio_unit": 50}],
        },
        # P_INACTIVO: 3 unidades
        {
            "_id": "V_INACTIVO",
            "id_venta": "V_INACTIVO",
            "estado": "Completada",
            "fecha": fecha,
            "items": [{"id_detalle": "D_I1", "id_producto": "P_INACTIVO", "cantidad": 3, "precio_unit": 50}],
        },
        # Candidatos para 5.º puesto con 2 unidades (empate P5_B vs P5_A, insertando B antes)
        {
            "_id": "V_P5_B",
            "id_venta": "V_P5_B",
            "estado": "Completada",
            "fecha": fecha,
            "items": [{"id_detalle": "D_5B", "id_producto": "P5_B", "cantidad": 2, "precio_unit": 50}],
        },
        {
            "_id": "V_P5_A",
            "id_venta": "V_P5_A",
            "estado": "Completada",
            "fecha": fecha,
            "items": [{"id_detalle": "D_5A", "id_producto": "P5_A", "cantidad": 2, "precio_unit": 50}],
        },
    ]

    mongo_test_db["ventas"].insert_many(ventas_escenario)

    resultado = q07(mongo_test_db)
    ids_obtenidos = [p["id_producto"] for p in resultado]

    # 1. Devuelve exactamente cinco productos (a pesar de haber más de cinco con ventas)
    assert len(resultado) == 5

    # 2. Las ventas Pendiente y Anulada no sumaron (P_TOP no aparece)
    assert "P_TOP" not in ids_obtenidos

    # 3. Suma correcta de ítems múltiples: P1 con 5 + 3 + 7 = 15 unidades (1.º lugar)
    assert resultado[0]["id_producto"] == "P1"
    assert resultado[0]["unidades"] == 15

    # 4. Unidades vs ventas vs ingresos: P_CHEAP (10 u., 1 venta) > P_EXPENSIVE (6 u., 3 ventas)
    idx_cheap = ids_obtenidos.index("P_CHEAP")
    idx_expensive = ids_obtenidos.index("P_EXPENSIVE")
    assert idx_cheap < idx_expensive
    assert resultado[1]["id_producto"] == "P_CHEAP"
    assert resultado[1]["unidades"] == 10
    assert resultado[2]["id_producto"] == "P_EXPENSIVE"
    assert resultado[2]["unidades"] == 6

    # 5. Producto no existente en productos entra al ranking con nombre: None (4 unidades, 4.º puesto)
    assert "P_FANTASMA" in ids_obtenidos
    p_fantasma = next(p for p in resultado if p["id_producto"] == "P_FANTASMA")
    assert p_fantasma["unidades"] == 4
    assert p_fantasma["nombre"] is None
    assert resultado[3]["id_producto"] == "P_FANTASMA"

    # 6. Producto inactivo con 3 unidades entra en el 5.º puesto
    assert resultado[4]["id_producto"] == "P_INACTIVO"
    assert resultado[4]["unidades"] == 3
    assert resultado[4]["nombre"] == "Producto Inactivo"

    # En este escenario, P1(15), P_CHEAP(10), P_EXPENSIVE(6), P_FANTASMA(4), P_INACTIVO(3).
    # P_INACTIVO es el 5.º! P5_A y P5_B quedaron 6.º y 7.º.
    # Para probar el desempate en el 5.º puesto con 6 productos, agregamos una prueba dedicada abajo:
    assert ids_obtenidos == ["P1", "P_CHEAP", "P_EXPENSIVE", "P_FANTASMA", "P_INACTIVO"]

    # 7. Ningún _id en el resultado
    assert all("_id" not in p for p in resultado)


@pytest.mark.integration
def test_q07_desempate_quinto_puesto(mongo_test_db) -> None:
    """Verifica específicamente el desempate por id_producto en el 5.º puesto."""
    fecha = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    mongo_test_db["ventas"].delete_many({})

    # 4 productos claros arriba (10, 8, 6, 4 unidades)
    # 2 productos empatados en el 5.º puesto con 2 unidades: P5_B y P5_A
    # Insertados fuera de orden (P5_B antes que P5_A)
    ventas = [
        {"_id": "V1", "id_venta": "V1", "estado": "Completada", "fecha": fecha, "items": [{"id_detalle": "D1", "id_producto": "P1", "cantidad": 10, "precio_unit": 10}]},
        {"_id": "V2", "id_venta": "V2", "estado": "Completada", "fecha": fecha, "items": [{"id_detalle": "D2", "id_producto": "P2", "cantidad": 8, "precio_unit": 10}]},
        {"_id": "V3", "id_venta": "V3", "estado": "Completada", "fecha": fecha, "items": [{"id_detalle": "D3", "id_producto": "P3", "cantidad": 6, "precio_unit": 10}]},
        {"_id": "V4", "id_venta": "V4", "estado": "Completada", "fecha": fecha, "items": [{"id_detalle": "D4", "id_producto": "P4", "cantidad": 4, "precio_unit": 10}]},
        {"_id": "V5_B", "id_venta": "V5_B", "estado": "Completada", "fecha": fecha, "items": [{"id_detalle": "D5B", "id_producto": "P5_B", "cantidad": 2, "precio_unit": 10}]},
        {"_id": "V5_A", "id_venta": "V5_A", "estado": "Completada", "fecha": fecha, "items": [{"id_detalle": "D5A", "id_producto": "P5_A", "cantidad": 2, "precio_unit": 10}]},
    ]
    mongo_test_db["ventas"].insert_many(ventas)

    resultado = q07(mongo_test_db)
    ids = [p["id_producto"] for p in resultado]

    assert len(resultado) == 5
    assert ids == ["P1", "P2", "P3", "P4", "P5_A"]
    assert "P5_B" not in ids, "P5_B debe quedar excluido por desempate de id_producto ascendente"
