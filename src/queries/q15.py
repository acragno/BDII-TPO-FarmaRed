"""Consulta 15: Actualizacion masiva de stock tras una venta"""

from typing import Any
from collections import defaultdict

from pymongo.database import Database
from pymongo.client_session import ClientSession

def q15(db: Database, id_venta: str, *, session: ClientSession) -> list[dict[str, Any]]:
    if not session.in_transaction:
        raise ValueError("Q15 requiere una transacción activa")

    sale = db["ventas"].find_one({"_id": id_venta}, session=session)
    if sale is None:
        raise ValueError(f"No existe la venta con id {id_venta}")
    if sale["estado"] != "Completada":
        raise ValueError("Solo se descuenta stock de ventas 'Completada'")
    if sale.get("stock_aplicado"):
        return sale["lotes_consumidos"]
    if not sale.get("items"):
        raise ValueError("La venta debe tener al menos un ítem")

    pharmacist = db["farmaceuticos"].find_one(
        {"_id": sale["id_farmaceutico"]}, session=session,
    )
    if pharmacist is None:
        raise ValueError(f"No existe el farmacéutico con id {sale['id_farmaceutico']}")

    remaining: dict[str, int] = defaultdict(int)
    for item in sale["items"]:
        if type(item["cantidad"]) is not int or item["cantidad"] <= 0:
            raise ValueError("Las cantidades deben ser enteros mayores que cero")
        remaining[item["id_producto"]] += item["cantidad"]

    # MongoDB calcula hoy en UTC, igual que las fechas de vencimiento almacenadas.
    today = {"$dateTrunc": {"date": "$$NOW", "unit": "day"}}
    lots = db["stock_lotes"].find(
        {
            "id_sucursal": pharmacist["id_sucursal"],
            "id_producto": {"$in": list(remaining)},
            "unidades": {"$gt": 0},
            "$expr": {"$gte": ["$vencimiento", today]},
        },
        session=session,
    ).sort([("vencimiento", 1), ("_id", 1)])

    consumptions: list[dict[str, Any]] = []
    for lot in lots:
        product_id = lot["id_producto"]
        quantity = min(remaining[product_id], lot["unidades"])
        if quantity:
            consumptions.append({
                "id_lote": lot["_id"], "id_producto": product_id, "cantidad": quantity,
            })
            remaining[product_id] -= quantity

    for product_id, quantity in remaining.items():
        if quantity:
            raise ValueError(f"Stock vigente insuficiente para el producto {product_id}")

    for consumption in consumptions:
        result = db["stock_lotes"].update_one(
            {"_id": consumption["id_lote"], "unidades": {"$gte": consumption["cantidad"]}},
            {"$inc": {"unidades": -consumption["cantidad"]}},
            session=session,
        )
        if result.matched_count != 1:
            raise ValueError(f"No se pudo descontar el lote {consumption['id_lote']}")

    result = db["ventas"].update_one(
        {"_id": id_venta, "stock_aplicado": {"$ne": True}},
        {"$set": {"stock_aplicado": True, "lotes_consumidos": consumptions}},
        session=session,
    )
    if result.matched_count != 1:
        raise ValueError("El stock de la venta ya fue aplicado o la venta no existe")
    return consumptions
