"""Tests para la consulta Q01: Productos activos con todos los datos de su proveedor."""

from __future__ import annotations

import pytest

from src.loaders.mongodb_loader import load_dataset
from src.loaders.validate import validate_data
from src.queries.q01 import q01
from tests.support import DATA_DIR


@pytest.mark.integration
def test_q01_dataset_real(mongo_test_db) -> None:
    """Test A: Verifica Q01 contra el dataset real cargado en MongoDB."""
    result = validate_data(DATA_DIR)
    assert result.ok, [str(issue) for issue in result.issues]

    load_dataset(mongo_test_db, result.records)

    # Mapa de proveedores desde los registros validados, omitiendo campos None
    proveedores_por_id = {
        p["id_proveedor"]: {k: v for k, v in p.items() if v is not None}
        for p in result.records["proveedores"]
    }

    # Productos activos esperados ordenados por id_producto
    productos_activos = [
        p for p in result.records["productos"] if p.get("activo") is True
    ]
    productos_activos.sort(key=lambda p: p["id_producto"])
    expected_ids = [p["id_producto"] for p in productos_activos]

    assert expected_ids, "El dataset real debe tener productos activos"

    actual = q01(mongo_test_db)
    actual_ids = [p["id_producto"] for p in actual]

    assert actual_ids == expected_ids

    for prod in actual:
        # Sin campo _id ni a nivel raíz ni en proveedor
        assert "_id" not in prod
        assert "proveedor" in prod
        proveedor_actual = prod["proveedor"]
        assert "_id" not in proveedor_actual

        # Comprobación de campos exactos del proveedor
        id_prov = prod["id_proveedor"]
        proveedor_esperado = proveedores_por_id[id_prov]
        assert proveedor_actual == proveedor_esperado


@pytest.mark.integration
def test_q01_casos_borde(mongo_test_db) -> None:
    """Test B: Casos borde armados a mano en base limpia."""
    # 1. Proveedores: uno activo y uno inactivo
    proveedores = [
        {
            "_id": "PRV_ACTIVO",
            "id_proveedor": "PRV_ACTIVO",
            "razon_social": "Laboratorio Activo S.A.",
            "cuit": "30-11111111-1",
            "tipo": "Laboratorio",
            "ciudad": "CABA",
            "provincia": "Buenos Aires",
            "telefono": "11111111",
            "activo": True,
        },
        {
            "_id": "PRV_INACTIVO",
            "id_proveedor": "PRV_INACTIVO",
            "razon_social": "Droguería Inactiva S.A.",
            "cuit": "30-22222222-2",
            "tipo": "Droguería",
            "ciudad": "Rosario",
            "provincia": "Santa Fe",
            "telefono": "22222222",
            "activo": False,
        },
    ]

    # 2. Productos:
    # - Insertados desordenados (PRD003, PRD001, PRD002) para probar ordenamiento
    # - P_PROV_INACTIVO: activo con proveedor inactivo (debe aparecer con datos de proveedor)
    # - P_INACTIVO: activo=False con proveedor activo (no debe aparecer)
    # - P_ROTO: activo con id_proveedor inexistente (debe aparecer con proveedor: None)
    # - PRD001 y PRD002: dos productos activos del mismo proveedor (ambos deben aparecer)
    productos = [
        {
            "_id": "PRD003",
            "id_producto": "PRD003",
            "nombre": "Producto Con Proveedor Inactivo",
            "principio_activo": "Droga C",
            "categoria": "Analgésico",
            "presentacion": "Comprimidos x10",
            "condicion_venta": "Venta libre",
            "precio_unit": 1000,
            "id_proveedor": "PRV_INACTIVO",
            "activo": True,
        },
        {
            "_id": "PRD001",
            "id_producto": "PRD001",
            "nombre": "Producto A Proveedor Activo",
            "principio_activo": "Droga A",
            "categoria": "Analgésico",
            "presentacion": "Comprimidos x10",
            "condicion_venta": "Venta libre",
            "precio_unit": 2000,
            "id_proveedor": "PRV_ACTIVO",
            "activo": True,
        },
        {
            "_id": "PRD002",
            "id_producto": "PRD002",
            "nombre": "Producto B Mismo Proveedor Activo",
            "principio_activo": "Droga B",
            "categoria": "Analgésico",
            "presentacion": "Comprimidos x10",
            "condicion_venta": "Venta libre",
            "precio_unit": 3000,
            "id_proveedor": "PRV_ACTIVO",
            "activo": True,
        },
        {
            "_id": "PRD004_INACTIVO",
            "id_producto": "PRD004_INACTIVO",
            "nombre": "Producto Inactivo",
            "principio_activo": "Droga D",
            "categoria": "Analgésico",
            "presentacion": "Comprimidos x10",
            "condicion_venta": "Venta libre",
            "precio_unit": 4000,
            "id_proveedor": "PRV_ACTIVO",
            "activo": False,
        },
        {
            "_id": "PRD005_ROTO",
            "id_producto": "PRD005_ROTO",
            "nombre": "Producto Con Proveedor Inexistente",
            "principio_activo": "Droga E",
            "categoria": "Analgésico",
            "presentacion": "Comprimidos x10",
            "condicion_venta": "Venta libre",
            "precio_unit": 5000,
            "id_proveedor": "PRV_FANTASMA",
            "activo": True,
        },
    ]

    mongo_test_db["proveedores"].insert_many(proveedores)
    mongo_test_db["productos"].insert_many(productos)

    resultado = q01(mongo_test_db)
    ids_obtenidos = [p["id_producto"] for p in resultado]

    # Asserts explícitos por caso borde:

    # 1. Producto activo con proveedor activo: False -> aparece con datos del proveedor
    prod3 = next(p for p in resultado if p["id_producto"] == "PRD003")
    assert prod3["proveedor"] is not None
    assert prod3["proveedor"]["id_proveedor"] == "PRV_INACTIVO"
    assert prod3["proveedor"]["activo"] is False

    # 2. Producto activo: False con proveedor activo -> no aparece
    assert "PRD004_INACTIVO" not in ids_obtenidos

    # 3. Producto activo con id_proveedor inexistente -> aparece con proveedor: None
    prod_roto = next(p for p in resultado if p["id_producto"] == "PRD005_ROTO")
    assert prod_roto["proveedor"] is None

    # 4. Dos productos activos del mismo proveedor -> aparecen ambos
    assert "PRD001" in ids_obtenidos
    assert "PRD002" in ids_obtenidos
    prod1 = next(p for p in resultado if p["id_producto"] == "PRD001")
    prod2 = next(p for p in resultado if p["id_producto"] == "PRD002")
    assert prod1["proveedor"]["id_proveedor"] == "PRV_ACTIVO"
    assert prod2["proveedor"]["id_proveedor"] == "PRV_ACTIVO"

    # 5. Orden determinista por id_producto ascendente a pesar de inserción desordenada
    assert ids_obtenidos == ["PRD001", "PRD002", "PRD003", "PRD005_ROTO"]

    # 6. Ningún _id en el resultado (ni arriba ni dentro de proveedor)
    for p in resultado:
        assert "_id" not in p
        if p["proveedor"] is not None:
            assert "_id" not in p["proveedor"]
