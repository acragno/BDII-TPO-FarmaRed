"""Sincroniza eventos de outbox con Neo4j usando un único consumidor."""

import logging
import signal
from datetime import datetime, timezone
from threading import Event
from typing import Any

from neo4j import Driver, Transaction
from neo4j.exceptions import DriverError, Neo4jError
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from src.config import Config
from src.db.mongo import create_client, get_database
from src.db.neo4j import NEO4J_DATABASE, create_driver

BATCH_SIZE = 50
IDLE_SECONDS = 1
INITIAL_RETRY_SECONDS = 2
MAX_RETRY_SECONDS = 30
SALE_NODE_FIELDS = ("id_venta", "fecha", "tipo", "medio_pago", "total", "estado")
SALE_ITEM_FIELDS = ("id_producto", "id_detalle", "cantidad", "precio_unit")
RECIPE_UPDATE_FIELDS = ("dispensas_realizadas", "estado", "proxima_dispensa")
logger = logging.getLogger(__name__)


def _client_properties(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    client_id = event["entity_id"]
    payload = event["payload"]
    if not isinstance(client_id, str) or not client_id:
        raise ValueError("El evento necesita un entity_id de cliente")
    if not isinstance(payload, dict):
        raise ValueError("El payload del cliente debe ser un objeto")
    if payload.get("id_cliente", client_id) != client_id:
        raise ValueError("El id_cliente del payload no coincide con entity_id")
    return client_id, {key: value for key, value in payload.items() if key != "_id"}


def insert_client(tx: Transaction, event: dict[str, Any]) -> None:
    client_id, properties = _client_properties(event)
    tx.run(
        "MERGE (c:Cliente {id_cliente: $id_cliente}) SET c += $properties",
        id_cliente=client_id,
        properties=properties,
    ).consume()


def update_client(tx: Transaction, event: dict[str, Any]) -> None:
    client_id, properties = _client_properties(event)
    result = tx.run(
        "MATCH (c:Cliente {id_cliente: $id_cliente}) "
        "SET c += $properties RETURN c.id_cliente AS id_cliente",
        id_cliente=client_id,
        properties=properties,
    ).single()
    if result is None:
        raise ValueError(f"El cliente {client_id} todavía no existe en Neo4j")


def delete_client(tx: Transaction, event: dict[str, Any]) -> None:
    client_id, _ = _client_properties(event)
    result = tx.run(
        "MATCH (c:Cliente {id_cliente: $id_cliente}) "
        "SET c.activo = false RETURN c.id_cliente AS id_cliente",
        id_cliente=client_id,
    ).single()
    if result is None:
        raise ValueError(f"El cliente {client_id} todavía no existe en Neo4j")


def completed_sale(tx: Transaction, event: dict[str, Any]) -> None:
    """Proyectar venta, detalles y receta en la transacción del consumidor."""
    payload = event["payload"]
    if not isinstance(payload, dict) or payload.get("id_venta") != event["entity_id"]:
        raise ValueError("El payload debe contener el id_venta de entity_id")
    properties = {field: payload[field] for field in SALE_NODE_FIELDS}
    if properties["estado"] != "Completada":
        raise ValueError("VentaCompletada requiere estado 'Completada'")
    if isinstance(properties["fecha"], datetime):
        properties["fecha"] = properties["fecha"].date()
    items = [{field: item[field] for field in SALE_ITEM_FIELDS} for item in payload["items"]]
    if not items:
        raise ValueError("La venta necesita al menos un ítem")

    sale_id = event["entity_id"]
    result = tx.run(
        """
        MATCH (c:Cliente {id_cliente: $id_cliente})
        MATCH (f:Farmaceutico {id_farmaceutico: $id_farmaceutico})
        MERGE (v:Venta {id_venta: $id_venta})
        SET v += $properties
        MERGE (c)-[:REALIZO]->(v)
        MERGE (f)-[:REGISTRO]->(v)
        RETURN v.id_venta AS id_venta
        """,
        id_venta=sale_id,
        id_cliente=payload["id_cliente"],
        id_farmaceutico=payload["id_farmaceutico"],
        properties=properties,
    ).single()
    if result is None:
        raise ValueError("El cliente o farmacéutico todavía no existe en Neo4j")

    result = tx.run(
        """
        MATCH (v:Venta {id_venta: $id_venta})
        UNWIND $items AS item
        MATCH (p:Producto {id_producto: item.id_producto})
        MERGE (v)-[r:INCLUYE {id_detalle: item.id_detalle}]->(p)
        SET r.cantidad = item.cantidad, r.precio_unit = item.precio_unit
        RETURN count(r) AS proyectados
        """,
        id_venta=sale_id,
        items=items,
    ).single()
    if result is None or result["proyectados"] != len(items):
        raise ValueError("Algún producto de la venta todavía no existe en Neo4j")

    if payload.get("id_receta"):
        recipe = payload["receta"]
        properties = {field: recipe[field] for field in RECIPE_UPDATE_FIELDS}
        if isinstance(properties["proxima_dispensa"], datetime):
            properties["proxima_dispensa"] = properties["proxima_dispensa"].date()
        result = tx.run(
            """
            MATCH (c:Cliente {id_cliente: $id_cliente})-[:TIENE_RECETA]->
                  (r:Receta {id_receta: $id_receta})
            MATCH (v:Venta {id_venta: $id_venta})
            SET r += $properties
            MERGE (v)-[:UTILIZA]->(r)
            RETURN r.id_receta AS id_receta
            """,
            id_cliente=payload["id_cliente"],
            id_receta=payload["id_receta"],
            id_venta=sale_id,
            properties=properties,
        ).single()
        if result is None:
            raise ValueError("La receta del cliente todavía no existe en Neo4j")


EVENT_HANDLERS = {
    "InsertClient": insert_client,
    "UpdateClient": update_client,
    "DeleteClient": delete_client,
    "VentaCompletada": completed_sale,
}


def process_batch(outbox: Collection, driver: Driver) -> int:
    events = list(
        outbox.find({"state": "Pending"})
        .sort([("created_at", 1), ("_id", 1)])
        .limit(BATCH_SIZE)
    )
    for event in events:
        event_filter = {"_id": event["_id"]}
        outbox.update_one(event_filter, {"$inc": {"attempts": 1}})
        try:
            handler = EVENT_HANDLERS.get(event.get("type"))
            if handler is None:
                raise ValueError(f"Tipo de evento no soportado: {event.get('type')}")

            with driver.session(database=NEO4J_DATABASE) as session:
                with session.begin_transaction() as tx:
                    handler(tx, event)
                    tx.commit()
        except (DriverError, Neo4jError, ValueError, KeyError, TypeError) as error:
            outbox.update_one(event_filter, {"$set": {"last_error": str(error)}})
            raise

        outbox.update_one(
            event_filter,
            {
                "$set": {
                    "state": "Processed",
                    "processed_at": datetime.now(timezone.utc),
                },
                "$unset": {"last_error": ""},
            },
        )
    return len(events)


def run_worker(outbox: Collection, driver: Driver, stop: Event) -> None:
    retry_seconds = INITIAL_RETRY_SECONDS
    while not stop.is_set():
        try:
            count = process_batch(outbox, driver)
        except (PyMongoError, DriverError, Neo4jError, ValueError, KeyError, TypeError):
            logger.exception("Falló el intento; se reintentará en %s segundos", retry_seconds)
            stop.wait(retry_seconds)
            retry_seconds = min(retry_seconds * 2, MAX_RETRY_SECONDS)
        else:
            retry_seconds = INITIAL_RETRY_SECONDS
            if count:
                logger.info("Procesados %s eventos", count)
            else:
                stop.wait(IDLE_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())

    config = Config.from_env()
    mongo_client = create_client(config)
    try:
        with create_driver(config) as driver:
            logger.info("Worker iniciado")
            run_worker(get_database(mongo_client, config)["outbox"], driver, stop)
    finally:
        mongo_client.close()


if __name__ == "__main__":
    main()
