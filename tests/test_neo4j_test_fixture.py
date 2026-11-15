"""Validaciones que protegen el Neo4j de la aplicación durante las pruebas."""

from __future__ import annotations

import pytest

from tests.conftest import _neo4j_endpoint, _validate_test_neo4j_endpoint


@pytest.mark.parametrize(
    "application_uri",
    [
        "bolt://localhost:7687",
        "neo4j://localhost:7687",
        "bolt://127.0.0.1:7687",
    ],
)
def test_application_uri_aliases_are_distinct_from_test_endpoint(
    application_uri: str,
) -> None:
    assert _validate_test_neo4j_endpoint("bolt://localhost:7688") != _neo4j_endpoint(
        application_uri
    )


@pytest.mark.parametrize(
    "unsafe_test_uri",
    [
        "bolt://localhost:7687",
        "neo4j://localhost:7687",
        "bolt://127.0.0.1:7687",
        "bolt://neo4j:7688",
    ],
)
def test_test_endpoint_rejects_application_or_nonlocal_endpoints(
    unsafe_test_uri: str,
) -> None:
    with pytest.raises(ValueError, match="puerto 7688"):
        _validate_test_neo4j_endpoint(unsafe_test_uri)
