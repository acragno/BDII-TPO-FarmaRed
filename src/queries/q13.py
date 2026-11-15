"""Consulta 13: ABM completo de clientes"""

import argparse
import json
from typing import Any
from uuid import uuid4
from datetime import datetime, timezone

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.client_session import ClientSession
from pymongo.errors import PyMongoError

from src.outbox import register_event
from src.config import Config
from src.db.mongo import create_client, get_database

INSURANCES = ("OSDE", "Swiss Medical", "PAMI", "IOMA", "Galeno", "Sin cobertura")
INSERT_CLIENT = ("id_cliente", "nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia", "obra_social")
UPDATE_CLIENT = ("email", "telefono", "obra_social", "nro_afiliado")

def q13Insert(db: Database, mongo_client: MongoClient, client: dict[str, Any]) -> dict[str, Any]:
    document = _validate_client(client)
    event = {
        "_id": str(uuid4()),
        "type": "InsertClient",
        "entity_id": document["id_cliente"],
        "created_at": datetime.now(timezone.utc),
        "payload": document,
        "state": "Pending",
        "attempts": 0
    }

    def callback(session: ClientSession) -> dict[str, Any]:
        db["clientes"].insert_one(document, session=session)
        register_event(db, event=event, session=session)
        return document

    with mongo_client.start_session() as session:
        return session.with_transaction(callback)


def q13Delete(db: Database, mongo_client: MongoClient, client_id: str) -> dict[str, Any]:

    event = {
            "_id": str(uuid4()),
            "type": "DeleteClient",
            "entity_id": client_id,
            "created_at": datetime.now(timezone.utc),
            "payload": {
                "id_cliente": client_id,
                "activo": False
            },
            "state": "Pending",
            "attempts": 0
        }

    def callback(session: ClientSession) -> dict[str, Any]:
        result = db["clientes"].update_one(
            {"_id": client_id},
            {"$set": {"activo": False}},
            upsert=False,
            session=session)

        if result.matched_count == 0:
            raise ValueError(f"No existe el cliente con id {client_id}")

        if result.modified_count == 1:
            register_event(db, event=event, session=session)

        return {
            "id_cliente": client_id,
            "activo": False,
            "modificado": result.modified_count == 1
        }

    with mongo_client.start_session() as session:
        return session.with_transaction(callback)


def q13Update(db: Database, mongo_client: MongoClient, client_id: str, modifications: dict[str, Any]) -> dict[str, Any]:
    document = _validate_client_modifications(modifications)
    event = {
        "_id": str(uuid4()),
        "type": "UpdateClient",
        "entity_id": client_id,
        "created_at": datetime.now(timezone.utc),
        "payload": document,
        "state": "Pending",
        "attempts": 0
    }

    def callback(session: ClientSession) -> dict[str, Any]:
        current_client = db["clientes"].find_one({"_id": client_id}, session=session)
        if current_client is None:
            raise ValueError(f"No existe el cliente con id {client_id}")

        updated_client = {**current_client, **document}
        _validate_coverage(
            updated_client["obra_social"], updated_client.get("nro_afiliado", "")
        )

        result = db["clientes"].update_one(
            {"_id": client_id},
            {"$set": document},
            upsert=False,
            session=session)

        if result.modified_count == 1:
            register_event(db, event=event, session=session)
        
        return {
            "id_cliente": client_id,
            **document,
            "modificado": result.modified_count == 1
        }

    with mongo_client.start_session() as session:
        return session.with_transaction(callback)


# Validar el formato del cliente para insertar.
def _validate_client(client: dict[str, Any]) -> dict[str, Any]:
    documento: dict[str, Any] = {}

    for campo in INSERT_CLIENT:
        valor = client.get(campo)

        if not isinstance(valor, str) or not valor.strip():
            raise ValueError(
                f"'{campo}' es obligatorio y debe ser un texto no vacío"
            )

        documento[campo] = valor.strip()

    activo = client.get("activo")
    if not isinstance(activo, bool):
        raise ValueError("'activo' debe ser un booleano: True o False")

    documento["activo"] = activo

    afiliado = _validate_coverage(
        documento["obra_social"], client.get("nro_afiliado", "")
    )
    if afiliado:
        documento["nro_afiliado"] = afiliado

    # Mantiene la convención utilizada por el loader.
    documento["_id"] = documento["id_cliente"]

    return documento

# Validar únicamente los campos enviados para modificar.
def _validate_client_modifications(modifications: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(modifications, dict) or not modifications:
        raise ValueError("Las modificaciones deben ser un objeto con al menos un campo")

    documento: dict[str, Any] = {}

    for field, valor in modifications.items():
        if field not in UPDATE_CLIENT:
            raise ValueError(f"El campo {field} no es valido o modificable")

        if not isinstance(valor, str):
            raise ValueError(f"'{field}' debe ser un texto")

        if field != "nro_afiliado" and not valor.strip():
            raise ValueError(
                f"'{field}' debe ser un texto no vacío"
            )

        documento[field] = valor.strip()

    if "obra_social" in documento and documento["obra_social"] not in INSURANCES:
        raise ValueError(f"'obra_social' debe ser una de: {', '.join(INSURANCES)}")

    return documento


def _validate_coverage(obra_social: str, nro_afiliado: Any) -> str:
    if obra_social not in INSURANCES:
        raise ValueError(f"'obra_social' debe ser una de: {', '.join(INSURANCES)}")

    if not isinstance(nro_afiliado, str):
        raise ValueError("'nro_afiliado' debe ser un texto")

    afiliado = nro_afiliado.strip()
    if not afiliado and obra_social != "Sin cobertura":
        raise ValueError("'nro_afiliado' solo puede estar vacío con 'Sin cobertura'")
    return afiliado


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    documento: dict[str, Any] = {}
    for field, valor in pairs:
        if field in documento:
            raise ValueError(f"El campo '{field}' está repetido")
        documento[field] = valor
    return documento


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Q13: ABM de clientes")
    acciones = parser.add_subparsers(dest="accion", required=True)

    alta = acciones.add_parser("alta", help="Dar de alta un cliente")
    alta.add_argument("--archivo", required=True, help="Archivo JSON con los datos del cliente")

    baja = acciones.add_parser("baja", help="Dar de baja lógica un cliente")
    baja.add_argument("id_cliente", help="ID del cliente que se dará de baja")

    modificacion = acciones.add_parser("modificacion", help="Modificar un cliente")
    modificacion.add_argument("id_cliente", help="ID del cliente que se modificará")
    modificacion.add_argument("--archivo", required=True, help="Archivo JSON con los cambios")

    args = parser.parse_args()

    datos: dict[str, Any] = {}
    if args.accion in ("alta", "modificacion"):
        try:
            with open(args.archivo, encoding="utf-8") as archivo:
                datos = json.load(archivo, object_pairs_hook=_reject_duplicate_fields)
            if not isinstance(datos, dict):
                raise ValueError("El archivo JSON debe contener un objeto")
        except (OSError, ValueError) as error:
            parser.error(str(error))

    config = Config.from_env()
    mongo_client = create_client(config)
    try:
        database = get_database(mongo_client, config)
        match args.accion:
            case "alta":
                resultado = q13Insert(database, mongo_client, datos)
            case "baja":
                resultado = q13Delete(database, mongo_client, args.id_cliente)
            case "modificacion":
                resultado = q13Update(database, mongo_client, args.id_cliente, datos)
        print(json.dumps(resultado, default=str, indent=2, ensure_ascii=False))
    except (ValueError, NotImplementedError, PyMongoError) as error:
        parser.exit(1, f"Error: {error}\n")
    finally:
        mongo_client.close()
