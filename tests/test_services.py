"""Servicios levantados por Docker"""

from __future__ import annotations

import pytest

from src.db.mongo import get_database, wait_for_mongo
from src.db.neo4j import wait_for_neo4j


@pytest.mark.integration
def test_mongodb_is_reachable(mongo_client) -> None:
    hello = mongo_client.admin.command("hello")

    assert hello.get("isWritablePrimary") is True
    assert hello.get("setName") == "rs0"


@pytest.mark.integration
def test_neo4j_is_reachable(neo4j_driver) -> None:
    with neo4j_driver.session() as session:
        value = session.run("RETURN 1 AS ok").single()["ok"]

    assert value == 1


@pytest.mark.integration
def test_wait_helpers_return_working_clients(
    config, mongo_client, neo4j_driver
) -> None:
    mongo = wait_for_mongo(config, timeout=5, interval=0.5)
    try:
        assert get_database(mongo, config).command("ping")["ok"] == 1
    finally:
        mongo.close()

    driver = wait_for_neo4j(config, timeout=5, interval=0.5)
    try:
        with driver.session() as session:
            assert session.run("RETURN 1 AS ok").single()["ok"] == 1
    finally:
        driver.close()
