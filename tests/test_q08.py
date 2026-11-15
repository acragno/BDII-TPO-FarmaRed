"""Tests para la consulta Q08: Lotes con menos de 50 unidades."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.loaders.mongodb_loader import load_dataset
from src.loaders.validate import validate_data
from src.queries.q08 import UMBRAL_STOCK_BAJO, q08
from tests.support import DATA_DIR


@pytest.mark.integration
def test_q08_dataset_real(mongo_test_db) -> None:
    """Test A: Verifica Q08 contra el dataset real cargado en MongoDB."""
    result = validate_data(DATA_DIR)
    assert result.ok, [str(issue) for issue in result.issues]

    load_dataset(mongo_test_db, result.records)

    # Mapas de entidades para verificar referencias resueltas
    productos_por_id = {p["id_producto"]: p for p in result.records["productos"]}
    sucursales_por_id = {s["id_sucursal"]: s for s in result.records["sucursales"]}
    proveedores_por_id = {p["id_proveedor"]: p for p in result.records["proveedores"]}

    # Lotes esperados filtrados por unidades < 50 y ordenados por (unidades, id_lote)
    lotes_esperados = [
        l for l in result.records["stock_lotes"] if l["unidades"] < UMBRAL_STOCK_BAJO
    ]
    lotes_esperados.sort(key=lambda l: (l["unidades"], l["id_lote"]))
    expected_ids = [l["id_lote"] for l in lotes_esperados]

    assert expected_ids, "El dataset real debe tener lotes con menos de 50 unidades"

    actual = q08(mongo_test_db)
    actual_ids = [l["id_lote"] for l in actual]

    assert actual_ids == expected_ids

    # Verificación de contenido detallado de cada resultado
    for lote in actual:
        # Sin campo _id en ningún nivel
        assert "_id" not in lote

        # Producto
        assert lote["producto"] is not None
        assert "_id" not in lote["producto"]
        prod_esperado = productos_por_id[lote["producto"]["id_producto"]]
        assert lote["producto"]["nombre"] == prod_esperado["nombre"]

        # Sucursal
        assert lote["sucursal"] is not None
        assert "_id" not in lote["sucursal"]
        suc_esperada = sucursales_por_id[lote["sucursal"]["id_sucursal"]]
        assert lote["sucursal"]["nombre"] == suc_esperada["nombre"]
        assert lote["sucursal"]["tipo"] == suc_esperada["tipo"]

        # Proveedor (obtenido a través del producto)
        assert lote["proveedor"] is not None
        assert "_id" not in lote["proveedor"]
        prov_esperado = proveedores_por_id[prod_esperado["id_proveedor"]]
        assert lote["proveedor"]["id_proveedor"] == prov_esperado["id_proveedor"]
        assert lote["proveedor"]["razon_social"] == prov_esperado["razon_social"]


@pytest.mark.integration
def test_q08_casos_borde(mongo_test_db) -> None:
    """Test B: Casos borde armados a mano en base limpia."""
    fecha_futura = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    fecha_pasada = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

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

    sucursales = [
        {
            "_id": "SUC_FARMACIA",
            "id_sucursal": "SUC_FARMACIA",
            "nombre": "Farmacia Central",
            "tipo": "Farmacia",
            "direccion": "Calle 1",
            "ciudad": "CABA",
            "provincia": "Buenos Aires",
            "telefono": "11112222",
            "activo": True,
        },
        {
            "_id": "SUC_DROGUERIA",
            "id_sucursal": "SUC_DROGUERIA",
            "nombre": "Depósito Distribución",
            "tipo": "Droguería",
            "direccion": "Ruta 2",
            "ciudad": "Avellaneda",
            "provincia": "Buenos Aires",
            "telefono": "11333344",
            "activo": True,
        },
        {
            "_id": "SUC_OTRA",
            "id_sucursal": "SUC_OTRA",
            "nombre": "Farmacia Norte",
            "tipo": "Farmacia",
            "direccion": "Av. Norte 100",
            "ciudad": "CABA",
            "provincia": "Buenos Aires",
            "telefono": "11555566",
            "activo": True,
        },
    ]

    productos = [
        {
            "_id": "P_ACTIVO",
            "id_producto": "P_ACTIVO",
            "nombre": "Producto Regular",
            "principio_activo": "Droga A",
            "categoria": "Analgésico",
            "presentacion": "Comprimidos x10",
            "condicion_venta": "Venta libre",
            "precio_unit": 1000,
            "id_proveedor": "PRV_ACTIVO",
            "activo": True,
        },
        {
            "_id": "P_PROV_INACTIVO",
            "id_producto": "P_PROV_INACTIVO",
            "nombre": "Producto Con Proveedor Inactivo",
            "principio_activo": "Droga B",
            "categoria": "Analgésico",
            "presentacion": "Comprimidos x10",
            "condicion_venta": "Venta libre",
            "precio_unit": 2000,
            "id_proveedor": "PRV_INACTIVO",
            "activo": True,
        },
        {
            "_id": "P_INACTIVO",
            "id_producto": "P_INACTIVO",
            "nombre": "Producto Descontinuado",
            "principio_activo": "Droga C",
            "categoria": "Analgésico",
            "presentacion": "Comprimidos x10",
            "condicion_venta": "Venta libre",
            "precio_unit": 3000,
            "id_proveedor": "PRV_ACTIVO",
            "activo": False,
        },
        {
            "_id": "P_PROV_ROTO",
            "id_producto": "P_PROV_ROTO",
            "nombre": "Producto Sin Proveedor Valido",
            "principio_activo": "Droga D",
            "categoria": "Analgésico",
            "presentacion": "Comprimidos x10",
            "condicion_venta": "Venta libre",
            "precio_unit": 4000,
            "id_proveedor": "PRV_INEXISTENTE",
            "activo": True,
        },
    ]

    lotes = [
        # Umbral estricto (< 50)
        {
            "_id": "L_49",
            "id_lote": "L_49",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_49",
            "unidades": 49,
            "vencimiento": fecha_futura,
        },
        {
            "_id": "L_50",
            "id_lote": "L_50",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_50",
            "unidades": 50,
            "vencimiento": fecha_futura,
        },
        {
            "_id": "L_51",
            "id_lote": "L_51",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_51",
            "unidades": 51,
            "vencimiento": fecha_futura,
        },
        {
            "_id": "L_0",
            "id_lote": "L_0",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_0",
            "unidades": 0,
            "vencimiento": fecha_futura,
        },
        # Lote vencido anterior a hoy
        {
            "_id": "L_VENCIDO",
            "id_lote": "L_VENCIDO",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_VENC",
            "unidades": 10,
            "vencimiento": fecha_pasada,
        },
        # Lote en sucursal tipo Droguería
        {
            "_id": "L_DROGUERIA",
            "id_lote": "L_DROGUERIA",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_DROGUERIA",
            "nro_lote": "NL_DROG",
            "unidades": 20,
            "vencimiento": fecha_futura,
        },
        # Lote de producto con activo: False
        {
            "_id": "L_PROD_INACTIVO",
            "id_lote": "L_PROD_INACTIVO",
            "id_producto": "P_INACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_PINACT",
            "unidades": 5,
            "vencimiento": fecha_futura,
        },
        # Lote de producto cuyo proveedor tiene activo: False
        {
            "_id": "L_PROV_INACTIVO",
            "id_lote": "L_PROV_INACTIVO",
            "id_producto": "P_PROV_INACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_PRVINACT",
            "unidades": 6,
            "vencimiento": fecha_futura,
        },
        # Lote cuyo producto tiene id_proveedor inexistente
        {
            "_id": "L_PROV_ROTO",
            "id_lote": "L_PROV_ROTO",
            "id_producto": "P_PROV_ROTO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_PRVROTO",
            "unidades": 7,
            "vencimiento": fecha_futura,
        },
        # Lote con id_producto inexistente
        {
            "_id": "L_PROD_ROTO",
            "id_lote": "L_PROD_ROTO",
            "id_producto": "P_INEXISTENTE",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_PRODROTO",
            "unidades": 8,
            "vencimiento": fecha_futura,
        },
        # Lote con id_sucursal inexistente
        {
            "_id": "L_SUC_ROTO",
            "id_lote": "L_SUC_ROTO",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_INEXISTENTE",
            "nro_lote": "NL_SUCROTO",
            "unidades": 9,
            "vencimiento": fecha_futura,
        },
        # Dos lotes del mismo producto en distintas sucursales
        {
            "_id": "L_MISMO_PROD_1",
            "id_lote": "L_MISMO_PROD_1",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_MISMO1",
            "unidades": 25,
            "vencimiento": fecha_futura,
        },
        {
            "_id": "L_MISMO_PROD_2",
            "id_lote": "L_MISMO_PROD_2",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_OTRA",
            "nro_lote": "NL_MISMO2",
            "unidades": 25,
            "vencimiento": fecha_futura,
        },
        # Dos lotes con las mismas unidades insertados fuera de orden (B antes que A)
        {
            "_id": "L_MISMA_CANT_B",
            "id_lote": "L_MISMA_CANT_B",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_MC_B",
            "unidades": 30,
            "vencimiento": fecha_futura,
        },
        {
            "_id": "L_MISMA_CANT_A",
            "id_lote": "L_MISMA_CANT_A",
            "id_producto": "P_ACTIVO",
            "id_sucursal": "SUC_FARMACIA",
            "nro_lote": "NL_MC_A",
            "unidades": 30,
            "vencimiento": fecha_futura,
        },
    ]

    mongo_test_db["proveedores"].insert_many(proveedores)
    mongo_test_db["sucursales"].insert_many(sucursales)
    mongo_test_db["productos"].insert_many(productos)
    mongo_test_db["stock_lotes"].insert_many(lotes)

    resultado = q08(mongo_test_db)
    ids_obtenidos = [l["id_lote"] for l in resultado]

    # 1. Umbral 49 y 0 entran; 50 y 51 no entran
    assert "L_0" in ids_obtenidos
    assert "L_49" in ids_obtenidos
    assert "L_50" not in ids_obtenidos, "Lote con 50 unidades no debe entrar (< 50)"
    assert "L_51" not in ids_obtenidos

    # 2. Lote con 10 unidades vencido anterior a hoy entra
    assert "L_VENCIDO" in ids_obtenidos

    # 3. Lote en sucursal tipo Droguería entra con sucursal.tipo == "Droguería"
    assert "L_DROGUERIA" in ids_obtenidos
    lote_drog = next(l for l in resultado if l["id_lote"] == "L_DROGUERIA")
    assert lote_drog["sucursal"] is not None
    assert lote_drog["sucursal"]["tipo"] == "Droguería"

    # 4. Lote de producto inactivo entra
    assert "L_PROD_INACTIVO" in ids_obtenidos

    # 5. Lote de producto cuyo proveedor tiene activo: False entra con datos del proveedor
    assert "L_PROV_INACTIVO" in ids_obtenidos
    lote_prov_inact = next(l for l in resultado if l["id_lote"] == "L_PROV_INACTIVO")
    assert lote_prov_inact["proveedor"] is not None
    assert lote_prov_inact["proveedor"]["id_proveedor"] == "PRV_INACTIVO"

    # 6. Lote con id_proveedor inexistente: producto presente y proveedor: None
    assert "L_PROV_ROTO" in ids_obtenidos
    lote_prov_roto = next(l for l in resultado if l["id_lote"] == "L_PROV_ROTO")
    assert lote_prov_roto["producto"] is not None
    assert lote_prov_roto["proveedor"] is None

    # 7. Lote con id_producto inexistente: producto: None y proveedor: None
    assert "L_PROD_ROTO" in ids_obtenidos
    lote_prod_roto = next(l for l in resultado if l["id_lote"] == "L_PROD_ROTO")
    assert lote_prod_roto["producto"] is None
    assert lote_prod_roto["proveedor"] is None

    # 8. Lote con id_sucursal inexistente: sucursal: None
    assert "L_SUC_ROTO" in ids_obtenidos
    lote_suc_roto = next(l for l in resultado if l["id_lote"] == "L_SUC_ROTO")
    assert lote_suc_roto["sucursal"] is None

    # 9. Dos lotes del mismo producto en distintas sucursales aparecen ambos
    assert "L_MISMO_PROD_1" in ids_obtenidos
    assert "L_MISMO_PROD_2" in ids_obtenidos

    # 10. Desempate por id_lote ascendente en igualdad de unidades
    idx_a = ids_obtenidos.index("L_MISMA_CANT_A")
    idx_b = ids_obtenidos.index("L_MISMA_CANT_B")
    assert idx_a < idx_b, "En empate de unidades deben desempatar por id_lote ascendente"

    # 11. Ningún _id en ningún nivel
    for l in resultado:
        assert "_id" not in l
        if l["producto"] is not None:
            assert "_id" not in l["producto"]
        if l["sucursal"] is not None:
            assert "_id" not in l["sucursal"]
        if l["proveedor"] is not None:
            assert "_id" not in l["proveedor"]
