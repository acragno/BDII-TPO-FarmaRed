"""Punto de entrada del cliente de FarmaRed"""

from __future__ import annotations

import argparse
import sys

from pymongo.errors import PyMongoError

from src import __version__
from src.config import Config
from src.db.mongo import MongoUnavailableError, get_database, wait_for_mongo
from src.loaders.mongodb_loader import ensure_indexes, load_dataset
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
