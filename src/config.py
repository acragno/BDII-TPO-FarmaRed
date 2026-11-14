"""Configuración leída desde variables de entorno.

Los valores por defecto coinciden con los servicios definidos en
``docker-compose.yml`` y con ``.env.example``. Para ejecutar el cliente fuera de
la red de Docker se debe crear un ``.env`` con los hosts correspondientes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_MONGO_URI = "mongodb://mongo:27017/?replicaSet=rs0"
DEFAULT_MONGO_DB = "farmared"
DEFAULT_NEO4J_URI = "bolt://neo4j:7687"
DEFAULT_NEO4J_USER = "neo4j"
DEFAULT_NEO4J_PASSWORD = "password"


@dataclass(frozen=True)
class Config:
    mongo_uri: str
    mongo_db: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str = field(repr=False)
    data_dir: Path = DEFAULT_DATA_DIR

    @classmethod
    def from_env(cls, env_file: Path | None = ENV_FILE) -> "Config":
        if env_file is not None and env_file.is_file():
            load_dotenv(env_file)

        return cls(
            mongo_uri=os.getenv("MONGO_URI", DEFAULT_MONGO_URI),
            mongo_db=os.getenv("MONGO_DB", DEFAULT_MONGO_DB),
            neo4j_uri=os.getenv("NEO4J_URI", DEFAULT_NEO4J_URI),
            neo4j_user=os.getenv("NEO4J_USER", DEFAULT_NEO4J_USER),
            neo4j_password=os.getenv("NEO4J_PASSWORD", DEFAULT_NEO4J_PASSWORD),
            data_dir=_resolve_data_dir(os.getenv("DATA_DIR")),
        )


def _resolve_data_dir(raw_path: str | None) -> Path:
    """Path absoluto de ``DATA_DIR``"""
    if not raw_path:
        return DEFAULT_DATA_DIR

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()
