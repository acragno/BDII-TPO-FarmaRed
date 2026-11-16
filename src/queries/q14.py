"""Consulta 14: registro de una venta completada."""

import argparse
import json
from copy import deepcopy
from typing import Any
from uuid import uuid4
from datetime import date, datetime, timezone

from pymongo import MongoClient, ReadPreference, ReturnDocument
from pymongo.database import Database
from pymongo.client_session import ClientSession
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from src.outbox import register_event
from src.config import Config
from src.db.mongo import create_client, get_database
from src.loaders.validate import MEDIOS_PAGO, VENTA_TIPOS
from src.queries.q15 import q15

SALE_REQUIRED_FIELDS = ("id_venta", "id_cliente", "id_farmaceutico", "fecha", "tipo", "medio_pago")
SALE_ALLOWED_FIELDS = SALE_REQUIRED_FIELDS + ("id_receta", "items")
SALE_EVENT_FIELDS = SALE_ALLOWED_FIELDS + ("estado", "total")
ITEM_REQUIRED_FIELDS = ("id_detalle", "id_producto")
ITEM_ALLOWED_FIELDS = ITEM_REQUIRED_FIELDS + ("id_venta", "cantidad")
PRESCRIPTION_CONDITIONS = ("Bajo receta", "Bajo receta archivada")
DISPENSE_INTERVAL_DAYS = 30
RECIPE_EVENT_FIELDS = ("dispensas_realizadas", "estado", "proxima_dispensa")


def q14(db: Database, mongo_client: MongoClient, venta: dict[str, Any]) -> dict[str, Any]:
    """Registrar en MongoDB venta, stock, dispensa y evento de forma atómica.

    Recibe la venta con ítems sin precios y retorna el documento persistido.
    Propaga errores de validación o persistencia sin dejar cambios parciales.
    """
    documento = _validate_sale(venta)
    event = {
        "_id": str(uuid4()),
        "type": "VentaCompletada",
        "entity_id": documento["id_venta"],
        "created_at": datetime.now(timezone.utc),
        "payload": {field: documento[field] for field in SALE_EVENT_FIELDS if field in documento},
        "state": "Pending",
        "attempts": 0,
    }

    def callback(session: ClientSession) -> dict[str, Any]:
        # with_transaction puede repetir el callback: cada intento usa una copia limpia.
        sale = deepcopy(documento)
        context = _validate_sale_references(db, sale, session=session)

        total = 0
        for item in sale["items"]:
            producto = context["productos"][item["id_producto"]]
            item["precio_unit"] = producto["precio_unit"]
            total += item["precio_unit"] * item["cantidad"]

        sale["total"] = total
        db["ventas"].insert_one(sale, session=session)

        # Q15 persiste los consumos y stock_aplicado en esta misma transacción.
        sale["lotes_consumidos"] = q15(db, sale["id_venta"], session=session)
        sale["stock_aplicado"] = True
        recipe = context["receta"]
        if recipe is not None:
            recipe = _dispense_recipe(db, recipe, sale["fecha"], session=session)

        event["payload"] = {field: sale[field] for field in SALE_EVENT_FIELDS if field in sale}
        if recipe is not None:
            event["payload"]["receta"] = {field: recipe.get(field) for field in RECIPE_EVENT_FIELDS}
        register_event(db, event=event, session=session)
        return sale

    with mongo_client.start_session() as session:
        return session.with_transaction(
            callback,
            read_preference=ReadPreference.PRIMARY,
            read_concern=ReadConcern("snapshot"),
            write_concern=WriteConcern(w="majority"),
        )


def _dispense_recipe(db: Database, recipe: dict[str, Any], fecha: datetime, *, session: ClientSession) -> dict[str, Any]:
    performed = recipe["dispensas_realizadas"] + 1
    pending = recipe["tipo"] == "Tratamiento prolongado" and performed < recipe["dispensas_autorizadas"]
    changes = {
        "dispensas_realizadas": performed,
        "estado": "Vigente" if pending else "Completada",
        "proxima_dispensa": {
            "$dateAdd": {"startDate": fecha, "unit": "day", "amount": DISPENSE_INTERVAL_DAYS},
        } if pending else None,
    }
    updated = db["recetas"].find_one_and_update(
        {"_id": recipe["_id"], "estado": "Vigente", "dispensas_realizadas": recipe["dispensas_realizadas"]},
        [{"$set": changes}],
        return_document=ReturnDocument.AFTER,
        session=session,
    )
    if updated is None:
        raise ValueError("La receta ya no está disponible para esta dispensa")
    return updated


def _validate_sale_references(db: Database, venta: dict[str, Any], *, session: ClientSession) -> dict[str, Any]:
    client = db["clientes"].find_one({"_id": venta["id_cliente"]}, session=session)
    if client is None:
        raise ValueError(f"No existe el cliente con id {venta['id_cliente']}")
    if client.get("activo") is not True:
        raise ValueError(f"El cliente de id {venta['id_cliente']} no está activo")

    pharmacist = db["farmaceuticos"].find_one({"_id": venta["id_farmaceutico"]}, session=session)
    if pharmacist is None:
        raise ValueError(f"No existe el farmacéutico con id {venta['id_farmaceutico']}")
    if pharmacist.get("activo") is not True:
        raise ValueError(f"El farmacéutico de id {venta['id_farmaceutico']} no está activo")

    branch = db["sucursales"].find_one({"_id": pharmacist["id_sucursal"]}, session=session)
    if branch is None:
        raise ValueError(f"No existe la sucursal con id {pharmacist['id_sucursal']}")
    if branch["tipo"] != "Farmacia":
        raise ValueError("Solo se registran ventas en sucursales de tipo 'Farmacia'")

    product_ids = sorted({item["id_producto"] for item in venta["items"]})
    products = {
        product["_id"]: product
        for product in db["productos"].find({"_id": {"$in": product_ids}}, session=session)
    }
    for product_id in product_ids:
        product = products.get(product_id)
        if product is None:
            raise ValueError(f"No existe el producto con id {product_id}")
        if product.get("activo") is not True:
            raise ValueError(f"El producto de id {product_id} no está activo")

    recipe_id = venta.get("id_receta")
    requires_recipe = any(
        product["condicion_venta"] in PRESCRIPTION_CONDITIONS for product in products.values()
    )
    if requires_recipe and not recipe_id:
        raise ValueError("Los productos bajo receta requieren una receta del cliente")

    recipe = None
    if recipe_id:
        recipe = db["recetas"].find_one({"_id": recipe_id}, session=session)
        if recipe is None:
            raise ValueError(f"No existe la receta con id {recipe_id}")
        if recipe["id_cliente"] != venta["id_cliente"]:
            raise ValueError("La receta debe pertenecer al cliente de la venta")
        if recipe["estado"] != "Vigente":
            raise ValueError("La receta debe estar en estado 'Vigente'")
        if recipe["dispensas_realizadas"] >= recipe["dispensas_autorizadas"]:
            raise ValueError("La receta no tiene dispensas disponibles")

    return {"sucursal": branch, "productos": products, "receta": recipe}


def _validate_sale(venta: dict[str, Any]) -> dict[str, Any]:

    if not isinstance(venta, dict):
        raise ValueError("La venta debe ser un objeto JSON")

    for campo in venta:
        if campo not in SALE_ALLOWED_FIELDS:
            raise ValueError(f"El campo '{campo}' no está permitido en la venta")

    documento: dict[str, Any] = {}
    for campo in SALE_REQUIRED_FIELDS:
        documento[campo] = _required_text(venta, campo)

    try:
        fecha = date.fromisoformat(documento["fecha"])
        if fecha.isoformat() != documento["fecha"]:
            raise ValueError
    except ValueError:
        raise ValueError("'fecha' debe ser una fecha válida en formato AAAA-MM-DD") from None
    documento["fecha"] = datetime(fecha.year, fecha.month, fecha.day, tzinfo=timezone.utc)

    if documento["tipo"] not in VENTA_TIPOS:
        raise ValueError(f"'tipo' debe ser uno de: {', '.join(VENTA_TIPOS)}")
    if documento["medio_pago"] not in MEDIOS_PAGO:
        raise ValueError(f"'medio_pago' debe ser uno de: {', '.join(MEDIOS_PAGO)}")
    documento["estado"] = "Completada"

    receta = venta.get("id_receta")
    if receta is not None:
        if not isinstance(receta, str):
            raise ValueError("'id_receta' debe ser un texto o null")
        receta = receta.strip()
    if documento["tipo"] == "Con receta" and not receta:
        raise ValueError("Una venta 'Con receta' requiere 'id_receta'")
    if documento["tipo"] == "Venta libre" and receta:
        raise ValueError("Una venta 'Venta libre' no debe tener 'id_receta'")
    if receta:
        documento["id_receta"] = receta

    documento["items"] = _validate_sale_items(venta.get("items"), documento["id_venta"])
    documento["_id"] = documento["id_venta"]
    return documento


def _validate_sale_items(items: Any, id_venta: str) -> list[dict[str, Any]]:
    """Validar detalles embebidos sin precios y con IDs de detalle distintos."""
    if not isinstance(items, list) or not items:
        raise ValueError("'items' debe ser una lista con al menos un detalle")

    detalles: list[dict[str, Any]] = []
    identificadores: set[str] = set()
    for indice, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{indice}] debe ser un objeto JSON")
        for campo in item:
            if campo not in ITEM_ALLOWED_FIELDS:
                raise ValueError(f"El campo 'items[{indice}].{campo}' no está permitido")

        detalle = {
            campo: _required_text(item, campo, prefijo=f"items[{indice}].")
            for campo in ITEM_REQUIRED_FIELDS
        }
        if "id_venta" in item:
            referencia = _required_text(item, "id_venta", prefijo=f"items[{indice}].")
            if referencia != id_venta:
                raise ValueError(f"'items[{indice}].id_venta' no coincide con la cabecera")
        if detalle["id_detalle"] in identificadores:
            raise ValueError(f"id_detalle duplicado: '{detalle['id_detalle']}'")
        identificadores.add(detalle["id_detalle"])

        cantidad = item.get("cantidad")
        if type(cantidad) is not int or cantidad <= 0:
            raise ValueError(f"'items[{indice}].cantidad' debe ser un entero mayor que cero")
        detalle["cantidad"] = cantidad
        detalles.append(detalle)
    return detalles


def _required_text(datos: dict[str, Any], campo: str, *, prefijo: str = "") -> str:
    valor = datos.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"'{prefijo}{campo}' es obligatorio y debe ser un texto no vacío")
    return valor.strip()


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    documento: dict[str, Any] = {}
    for campo, valor in pairs:
        if campo in documento:
            raise ValueError(f"El campo '{campo}' está repetido")
        documento[campo] = valor
    return documento


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Q14: registrar una venta completada")
    parser.add_argument("--archivo", required=True, help="Archivo JSON con los datos de la venta")
    args = parser.parse_args()

    try:
        with open(args.archivo, encoding="utf-8") as archivo:
            datos = json.load(archivo, object_pairs_hook=_reject_duplicate_fields)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    config = Config.from_env()
    mongo_client = create_client(config)
    try:
        database = get_database(mongo_client, config)
        resultado = q14(database, mongo_client, datos)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    except (ValueError, NotImplementedError, PyMongoError) as error:
        parser.exit(1, f"Error: {error}\n")
    finally:
        mongo_client.close()

