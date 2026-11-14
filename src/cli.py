"""Punto de entrada del cliente de FarmaRed"""

from __future__ import annotations

import argparse
import sys

from neo4j.exceptions import DriverError, Neo4jError
from pymongo.errors import PyMongoError

from src import __version__
from src.config import Config
from src.db.mongo import MongoUnavailableError, get_database, wait_for_mongo
from src.db.neo4j import Neo4jUnavailableError, wait_for_neo4j
from src.loaders.mongodb_loader import ensure_indexes, load_dataset
from src.loaders.neo4j_projection import ProjectionError, build_projection
from src.loaders.validate import ValidationResult, validate_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<comando>")
    subparsers.required = True

    show_config = subparsers.add_parser(
        "show-config",
    )
    show_config.set_defaults(handler=_show_config)

    validate = subparsers.add_parser(
        "validate-data",
    )
    validate.set_defaults(handler=_validate_data)

    load_mongodb = subparsers.add_parser(
        "load-mongodb",
    )
    load_mongodb.set_defaults(handler=_load_mongodb)

    build_neo4j = subparsers.add_parser(
        "build-neo4j",
    )
    build_neo4j.set_defaults(handler=_build_neo4j)

    return parser


def _show_config(_: argparse.Namespace) -> int:
    config = Config.from_env()
    print(f"MONGO_URI={config.mongo_uri}")
    print(f"MONGO_DB={config.mongo_db}")
    print(f"NEO4J_URI={config.neo4j_uri}")
    print(f"NEO4J_USER={config.neo4j_user}")
    print("NEO4J_PASSWORD=" + ("*" * 8 if config.neo4j_password else ""))
    print(f"DATA_DIR={config.data_dir}")
    return 0


def _validate_data(_: argparse.Namespace) -> int:
    config = Config.from_env()
    result = validate_data(config.data_dir)

    if not result.ok:
        _print_validation_issues(result)
        return 1

    print(f"Datos válidos en {config.data_dir}:")
    for table, count in result.counts().items():
        print(f"  {table}: {count} registros")
    return 0


def _load_mongodb(_: argparse.Namespace) -> int:
    config = Config.from_env()
    result = validate_data(config.data_dir)

    if not result.ok:
        _print_validation_issues(result)
        return 1

    try:
        client = wait_for_mongo(config)
    except MongoUnavailableError as error:
        print(f"No se pudo conectar a MongoDB: {error}", file=sys.stderr)
        print("Verificá el entorno con 'docker compose up -d'.", file=sys.stderr)
        return 1

    try:
        database = get_database(client, config)
        report = load_dataset(database, result.records)
        indexes = ensure_indexes(database)
    except PyMongoError as error:
        print(f"Error al cargar MongoDB: {error}", file=sys.stderr)
        return 1
    finally:
        client.close()

    print(f"Datos cargados en MongoDB ('{config.mongo_db}'):")
    for table, count in report.collections.items():
        print(f"  {table}: {count} documentos")
    print(f"  ventas.items: {report.items} detalles embebidos")
    print("Índices:")
    for table, names in indexes.items():
        print(f"  {table}: {', '.join(names)}")
    return 0


def _print_validation_issues(result: ValidationResult) -> None:
    print(
        f"Se encontraron {len(result.issues)} errores de validación:",
        file=sys.stderr,
    )
    for issue in result.issues:
        print(f"  - {issue}", file=sys.stderr)


def _build_neo4j(_: argparse.Namespace) -> int:
    config = Config.from_env()
    mongo_client = None
    neo4j_driver = None

    try:
        mongo_client = wait_for_mongo(config, timeout=30)
        neo4j_driver = wait_for_neo4j(config, timeout=30)
        report = build_projection(
            get_database(mongo_client, config), neo4j_driver
        )
    except (
        MongoUnavailableError,
        Neo4jUnavailableError,
        ProjectionError,
    ) as error:
        print(f"No se pudo construir la proyección: {error}", file=sys.stderr)
        return 1
    except PyMongoError as error:
        print(f"Error leyendo MongoDB: {error}", file=sys.stderr)
        return 1
    except (DriverError, Neo4jError) as error:
        print(f"Error escribiendo en Neo4j: {error}", file=sys.stderr)
        return 1
    finally:
        if mongo_client is not None:
            mongo_client.close()
        if neo4j_driver is not None:
            neo4j_driver.close()

    print("Proyección de Neo4j reconstruida desde MongoDB:")
    print(f"  restricciones de unicidad: {len(report.constraints)}")
    for label, count in report.nodes.items():
        print(f"  {label}: {count} nodos")
    for name, count in report.relationships.items():
        print(f"  {name}: {count} relaciones")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
