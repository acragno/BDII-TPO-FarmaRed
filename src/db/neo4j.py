"""Conexión a Neo4j"""

from __future__ import annotations

import time

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import AuthError, DriverError, Neo4jError

from src.config import Config

DEFAULT_TIMEOUT = 60.0
DEFAULT_INTERVAL = 2.0
NEO4J_DATABASE = "neo4j"


class Neo4jUnavailableError(RuntimeError):
    """Neo4j no quedó disponible dentro del tiempo esperado."""


def create_driver(config: Config) -> Driver:
    return GraphDatabase.driver(
        config.neo4j_uri,
        auth=(config.neo4j_user, config.neo4j_password),
        connection_timeout=5,
    )


def wait_for_neo4j(
    config: Config,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
) -> Driver:
    driver = create_driver(config)
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with driver.session(database=NEO4J_DATABASE) as session:
                session.run("RETURN 1 AS ok").consume()
            return driver
        except AuthError as error:
            driver.close()
            raise Neo4jUnavailableError(
                f"Neo4j rechazó las credenciales: {error}"
            ) from error
        except (DriverError, Neo4jError) as error:
            last_error = error
            time.sleep(interval)

    driver.close()
    message = "No se pudo conectar a Neo4j dentro del tiempo esperado"
    if last_error is not None:
        message = f"{message}: {last_error}"
    raise Neo4jUnavailableError(message)
