"""Compartidos por los tests"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from neo4j.exceptions import DriverError, Neo4jError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from src.config import Config
from src.db.mongo import create_client
from src.db.neo4j import NEO4J_DATABASE, create_driver
from tests.support import DATA_DIR, TEST_DB, DatasetEditor

TEST_NEO4J_URI = "bolt://localhost:7688"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    """Copia temporal de los datos"""
    target = tmp_path / "data"
    shutil.copytree(DATA_DIR, target)
    return target


@pytest.fixture
def editor(dataset: Path) -> DatasetEditor:
    return DatasetEditor(dataset)


@pytest.fixture(scope="session")
def config() -> Config:
    return Config.from_env()


@pytest.fixture(scope="session")
def mongo_client(config: Config) -> MongoClient:
    client = create_client(config, server_selection_timeout_ms=1000)
    try:
        client.admin.command("ping")
    except PyMongoError as error:
        client.close()
        pytest.skip(f"MongoDB no disponible: {error}")
    yield client
    client.close()


@pytest.fixture
def mongo_test_db(mongo_client: MongoClient):
    mongo_client.drop_database(TEST_DB)
    yield mongo_client[TEST_DB]
    mongo_client.drop_database(TEST_DB)


@pytest.fixture(scope="session")
def neo4j_driver(config: Config):
    driver = create_driver(config)
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            session.run("RETURN 1 AS ok").consume()
    except (DriverError, Neo4jError, OSError) as error:
        driver.close()
        pytest.skip(f"Neo4j no disponible: {error}")
    yield driver
    driver.close()


@pytest.fixture
def neo4j_test_driver():
    """Driver for the disposable, isolated Neo4j test service."""
    app_config = Config.from_env()
    test_uri = os.getenv("NEO4J_TEST_URI", TEST_NEO4J_URI)
    test_user = os.getenv("NEO4J_TEST_USER", "neo4j")
    test_password = os.getenv("NEO4J_TEST_PASSWORD", "test_password")

    if not test_user or not test_password:
        pytest.fail(
            "NEO4J_TEST_USER y NEO4J_TEST_PASSWORD deben estar configurados "
            "para el servicio Neo4j de pruebas."
        )
    try:
        test_endpoint = _validate_test_neo4j_endpoint(test_uri)
        same_endpoint = test_endpoint == _neo4j_endpoint(
            app_config.neo4j_uri
        )
    except ValueError as error:
        pytest.fail(f"NEO4J_TEST_URI no es válido ({test_uri}): {error}")
    if same_endpoint:
        pytest.fail(
            "NEO4J_TEST_URI apunta al mismo endpoint que NEO4J_URI "
            f"({test_uri}). Configure el servicio aislado en bolt://localhost:7688."
        )

    test_config = Config(
        mongo_uri=app_config.mongo_uri,
        mongo_db=app_config.mongo_db,
        neo4j_uri=test_uri,
        neo4j_user=test_user,
        neo4j_password=test_password,
        data_dir=app_config.data_dir,
    )
    try:
        driver = create_driver(test_config)
    except (DriverError, OSError, ValueError) as error:
        pytest.fail(
            "No se puede crear el driver para el Neo4j aislado de pruebas. "
            f"Verifique NEO4J_TEST_URI: {error}"
        )
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            session.run("RETURN 1 AS ok").consume()
            session.run("MATCH (n) DETACH DELETE n").consume()
    except (DriverError, Neo4jError, OSError) as error:
        driver.close()
        pytest.fail(
            "No se puede usar el Neo4j aislado de pruebas. Inicie "
            "neo4j-test con el perfil test y verifique NEO4J_TEST_URI, "
            f"NEO4J_TEST_USER y NEO4J_TEST_PASSWORD: {error}"
        )

    try:
        yield driver
    finally:
        try:
            with driver.session(database=NEO4J_DATABASE) as session:
                session.run("MATCH (n) DETACH DELETE n").consume()
        finally:
            driver.close()


def _neo4j_endpoint(uri: str) -> tuple[str, int]:
    parsed = urlsplit(uri)
    hostname = (parsed.hostname or "").lower()
    if hostname in _LOCAL_HOSTS:
        hostname = "local"
    return hostname, parsed.port or 7687


def _validate_test_neo4j_endpoint(uri: str) -> tuple[str, int]:
    if urlsplit(uri).scheme not in {"bolt", "neo4j"}:
        raise ValueError(f"esquema Neo4j no admitido en {uri}")
    endpoint = _neo4j_endpoint(uri)
    if endpoint != ("local", 7688):
        raise ValueError(
            "el fixture solo admite un endpoint local en el puerto 7688 "
            f"(se recibió {uri})"
        )
    return endpoint
