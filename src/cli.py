"""Punto de entrada del cliente de FarmaRed"""

from __future__ import annotations

import argparse
import sys

from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from src import __version__
from src.config import Config
from src.db.mongo import (
    DEFAULT_TIMEOUT,
    MongoUnavailableError,
    get_database,
    wait_for_mongo,
)
from src.db.neo4j import Neo4jUnavailableError, wait_for_neo4j
from src.loaders.mongodb_loader import (
    LoadReport,
    clear_database,
    ensure_indexes,
    load_dataset,
)
from src.loaders.neo4j_projection import (
    ProjectionError,
    ProjectionReport,
    build_projection,
    clear_projection,
)
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
    _add_timeout(build_neo4j)

    wait_for_services = subparsers.add_parser(
        "wait-for-services",
    )
    wait_for_services.set_defaults(handler=_wait_for_services)
    _add_timeout(wait_for_services)

    seed = subparsers.add_parser(
        "seed",
    )
    seed.set_defaults(handler=_seed)
    _add_timeout(seed)

    reset = subparsers.add_parser(
        "reset",
    )
    reset.set_defaults(handler=_reset)
    _add_timeout(reset)

    return parser


def _add_timeout(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="<segundos>",
    )


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

    _print_load_report(config, report, indexes)
    return 0


def _build_neo4j(args: argparse.Namespace) -> int:
    config = Config.from_env()
    mongo_client = None
    neo4j_driver = None

    try:
        mongo_client, neo4j_driver = _connect_services(config, args.timeout)
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
        _close_services(mongo_client, neo4j_driver)

    _print_projection_report(report)
    return 0


def _wait_for_services(args: argparse.Namespace) -> int:
    config = Config.from_env()
    mongo_client = None
    neo4j_driver = None

    try:
        mongo_client, neo4j_driver = _connect_services(config, args.timeout)
    except (MongoUnavailableError, Neo4jUnavailableError) as error:
        print(f"Servicios no disponibles: {error}", file=sys.stderr)
        print("Verificá el entorno con 'docker compose up -d'.", file=sys.stderr)
        return 1
    finally:
        _close_services(mongo_client, neo4j_driver)

    print("Servicios disponibles:")
    print(f"  MongoDB: {config.mongo_uri} ('{config.mongo_db}')")
    print(f"  Neo4j: {config.neo4j_uri}")
    return 0


def _seed(args: argparse.Namespace) -> int:
    config = Config.from_env()
    result = validate_data(config.data_dir)

    if not result.ok:
        _print_validation_issues(result)
        return 1

    mongo_client = None
    neo4j_driver = None

    try:
        mongo_client, neo4j_driver = _connect_services(config, args.timeout)
        database = get_database(mongo_client, config)
        load_report = load_dataset(database, result.records)
        indexes = ensure_indexes(database)
        projection_report = build_projection(database, neo4j_driver)
    except (
        MongoUnavailableError,
        Neo4jUnavailableError,
        ProjectionError,
    ) as error:
        print(f"No se pudo inicializar el entorno: {error}", file=sys.stderr)
        return 1
    except PyMongoError as error:
        print(f"Error trabajando con MongoDB: {error}", file=sys.stderr)
        return 1
    except (DriverError, Neo4jError) as error:
        print(f"Error trabajando con Neo4j: {error}", file=sys.stderr)
        return 1
    finally:
        _close_services(mongo_client, neo4j_driver)

    print(f"Datos válidos en {config.data_dir}:")
    for table, count in result.counts().items():
        print(f"  {table}: {count} registros")
    print()
    _print_load_report(config, load_report, indexes)
    print()
    _print_projection_report(projection_report)
    return 0


def _reset(args: argparse.Namespace) -> int:
    config = Config.from_env()
    mongo_client = None
    neo4j_driver = None

    try:
        mongo_client, neo4j_driver = _connect_services(config, args.timeout)
        removed = clear_database(get_database(mongo_client, config))
        cleared = clear_projection(neo4j_driver)
    except (MongoUnavailableError, Neo4jUnavailableError) as error:
        print(f"No se pudo reiniciar el entorno: {error}", file=sys.stderr)
        return 1
    except PyMongoError as error:
        print(f"Error limpiando MongoDB: {error}", file=sys.stderr)
        return 1
    except (DriverError, Neo4jError) as error:
        print(f"Error limpiando Neo4j: {error}", file=sys.stderr)
        return 1
    finally:
        _close_services(mongo_client, neo4j_driver)

    print(f"MongoDB limpio ('{config.mongo_db}'):")
    if removed:
        for name, count in removed.items():
            print(f"  {name}: {count} documentos eliminados")
    else:
        print("  no había colecciones")
    print("Neo4j limpio:")
    print(f"  {cleared.nodes} nodos y {cleared.relationships} relaciones eliminados")
    print("  restricciones de unicidad conservadas")
    return 0


def _connect_services(
    config: Config, timeout: float
) -> tuple[MongoClient, Driver]:
    mongo_client = wait_for_mongo(config, timeout=timeout)
    try:
        neo4j_driver = wait_for_neo4j(config, timeout=timeout)
    except Exception:
        mongo_client.close()
        raise
    return mongo_client, neo4j_driver


def _close_services(
    mongo_client: MongoClient | None,
    neo4j_driver: Driver | None,
) -> None:
    if mongo_client is not None:
        mongo_client.close()
    if neo4j_driver is not None:
        neo4j_driver.close()


def _print_load_report(
    config: Config,
    report: LoadReport,
    indexes: dict[str, list[str]],
) -> None:
    print(f"Datos cargados en MongoDB ('{config.mongo_db}'):")
    for table, count in report.collections.items():
        print(f"  {table}: {count} documentos")
    print(f"  ventas.items: {report.items} detalles embebidos")
    print("Índices:")
    for table, names in indexes.items():
        print(f"  {table}: {', '.join(names)}")


def _print_projection_report(report: ProjectionReport) -> None:
    print("Proyección de Neo4j reconstruida desde MongoDB:")
    print(f"  restricciones de unicidad: {len(report.constraints)}")
    for label, count in report.nodes.items():
        print(f"  {label}: {count} nodos")
    for name, count in report.relationships.items():
        print(f"  {name}: {count} relaciones")


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
