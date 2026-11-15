"""Tests para la consulta Q09: Ventas de tipo 'Venta libre' con total menor a $5.000."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.loaders.mongodb_loader import load_dataset
from src.loaders.validate import validate_data
from src.queries.q09 import UMBRAL_VENTA_LIBRE, q09
from tests.support import DATA_DIR


@pytest.mark.integration
def test_q09_dataset_real(mongo_test_db) -> None:
    """Test A: Verifica Q09 contra el dataset real cargado en MongoDB."""
    result = validate_data(DATA_DIR)
    assert result.ok, [str(issue) for issue in result.issues]

    load_dataset(mongo_test_db, result.records)

    # Cálculo esperado en Python puro sobre los registros validados
    ventas_filtradas = [
        v
        for v in result.records["ventas"]
        if v["tipo"] == "Venta libre"
        and v["total"] < UMBRAL_VENTA_LIBRE
        and v["estado"] != "Anulada"
    ]
    ventas_filtradas.sort(key=lambda v: (v["fecha"], v["id_venta"]))
    expected_ids = [v["id_venta"] for v in ventas_filtradas]

    assert expected_ids, "El conjunto esperado con el dataset real no debería estar vacío"

    actual = q09(mongo_test_db)
    actual_ids = [v["id_venta"] for v in actual]

    assert actual_ids == expected_ids
    # Ningún documento devuelto debe contener el campo _id
    assert all("_id" not in v for v in actual)


@pytest.mark.integration
def test_q09_casos_borde(mongo_test_db) -> None:
    """Test B: Casos borde armados a mano en base limpia."""
    fecha_base = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    fecha_misma = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc)

    documentos = [
        # Umbral estricto (< 5000)
        {
            "_id": "V_4999",
            "id_venta": "V_4999",
            "id_cliente": "C001",
            "id_farmaceutico": "F001",
            "fecha": fecha_base,
            "tipo": "Venta libre",
            "medio_pago": "Efectivo",
            "total": 4999,
            "estado": "Completada",
            "items": [],
        },
        {
            "_id": "V_5000",
            "id_venta": "V_5000",
            "id_cliente": "C001",
            "id_farmaceutico": "F001",
            "fecha": fecha_base,
            "tipo": "Venta libre",
            "medio_pago": "Efectivo",
            "total": 5000,
            "estado": "Completada",
            "items": [],
        },
        {
            "_id": "V_5001",
            "id_venta": "V_5001",
            "id_cliente": "C001",
            "id_farmaceutico": "F001",
            "fecha": fecha_base,
            "tipo": "Venta libre",
            "medio_pago": "Efectivo",
            "total": 5001,
            "estado": "Completada",
            "items": [],
        },
        # Estado de venta
        {
            "_id": "V_PENDIENTE",
            "id_venta": "V_PENDIENTE",
            "id_cliente": "C001",
            "id_farmaceutico": "F001",
            "fecha": fecha_base,
            "tipo": "Venta libre",
            "medio_pago": "Efectivo",
            "total": 2000,
            "estado": "Pendiente",
            "items": [],
        },
        {
            "_id": "V_ANULADA",
            "id_venta": "V_ANULADA",
            "id_cliente": "C001",
            "id_farmaceutico": "F001",
            "fecha": fecha_base,
            "tipo": "Venta libre",
            "medio_pago": "Efectivo",
            "total": 2000,
            "estado": "Anulada",
            "items": [],
        },
        # Tipo de venta
        {
            "_id": "V_RECETA",
            "id_venta": "V_RECETA",
            "id_cliente": "C001",
            "id_farmaceutico": "F001",
            "id_receta": "RC001",
            "fecha": fecha_base,
            "tipo": "Con receta",
            "medio_pago": "Efectivo",
            "total": 2000,
            "estado": "Completada",
            "items": [],
        },
        # Empate en fecha: deben ordenarse por id_venta asc (V_MISMA_A antes que V_MISMA_B)
        {
            "_id": "V_MISMA_B",
            "id_venta": "V_MISMA_B",
            "id_cliente": "C001",
            "id_farmaceutico": "F001",
            "fecha": fecha_misma,
            "tipo": "Venta libre",
            "medio_pago": "Efectivo",
            "total": 1500,
            "estado": "Completada",
            "items": [],
        },
        {
            "_id": "V_MISMA_A",
            "id_venta": "V_MISMA_A",
            "id_cliente": "C001",
            "id_farmaceutico": "F001",
            "fecha": fecha_misma,
            "tipo": "Venta libre",
            "medio_pago": "Efectivo",
            "total": 1500,
            "estado": "Completada",
            "items": [],
        },
    ]

    mongo_test_db["ventas"].insert_many(documentos)

    resultado = q09(mongo_test_db)
    ids_obtenidos = [v["id_venta"] for v in resultado]

    # Asserts explícitos por caso borde:
    # 1. Total 4999 entra; 5000 y 5001 no entran
    assert "V_4999" in ids_obtenidos, "Venta libre total 4999 debe entrar"
    assert "V_5000" not in ids_obtenidos, "Venta libre total 5000 no debe entrar (umbral estricto < 5000)"
    assert "V_5001" not in ids_obtenidos, "Venta libre total 5001 no debe entrar"

    # 2. Pendiente entra; Anulada no entra
    assert "V_PENDIENTE" in ids_obtenidos, "Venta libre pendiente con total < 5000 debe entrar"
    assert "V_ANULADA" not in ids_obtenidos, "Venta anulada no debe entrar"

    # 3. Con receta no entra aunque cumpla monto y estado
    assert "V_RECETA" not in ids_obtenidos, "Venta 'Con receta' no debe entrar"

    # 4. Desempate determinista por id_venta en misma fecha
    idx_a = ids_obtenidos.index("V_MISMA_A")
    idx_b = ids_obtenidos.index("V_MISMA_B")
    assert idx_a < idx_b, "En misma fecha deben ordenarse por id_venta ascendente"

    # Verificación de exclusión de _id
    assert all("_id" not in v for v in resultado)
