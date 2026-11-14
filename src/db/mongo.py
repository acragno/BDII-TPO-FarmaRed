"""Conexión a MongoDB"""

from __future__ import annotations

import time

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from src.config import Config

DEFAULT_TIMEOUT = 60.0
DEFAULT_INTERVAL = 2.0
DEFAULT_SERVER_SELECTION_MS = 5000


class MongoUnavailableError(RuntimeError):
    """MongoDB no quedó disponible dentro del tiempo esperado."""


def create_client(
    config: Config,
    server_selection_timeout_ms: int = DEFAULT_SERVER_SELECTION_MS,
) -> MongoClient:
    return MongoClient(
        config.mongo_uri,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
        tz_aware=True,
        appname="farmared-cli",
    )


def get_database(client: MongoClient, config: Config) -> Database:
    return client[config.mongo_db]


def wait_for_mongo(
    config: Config,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
) -> MongoClient:
    """Espera hasta que MongoDB tenga un primario que acepte escrituras"""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        client = create_client(config, server_selection_timeout_ms=3000)
        try:
            hello = client.admin.command("hello")
            if hello.get("isWritablePrimary"):
                return client
            last_error = MongoUnavailableError(
                "MongoDB está disponible pero no tiene un primario que acepte escrituras"
            )
        except PyMongoError as error:
            last_error = error
        client.close()
        time.sleep(interval)

    message = "No se pudo conectar a MongoDB dentro del tiempo esperado"
    if last_error is not None:
        message = f"{message}: {last_error}"
    raise MongoUnavailableError(message)
