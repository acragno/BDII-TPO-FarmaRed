"""Compartidos por los tests"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from neo4j.exceptions import DriverError, Neo4jError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from src.config import Config
from src.db.mongo import create_client
from src.db.neo4j import NEO4J_DATABASE, create_driver
from tests.support import DATA_DIR, TEST_DB, DatasetEditor


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
