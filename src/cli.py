"""Punto de entrada del cliente de FarmaRed"""

from __future__ import annotations

import argparse
import sys

from src import __version__
from src.config import Config
from src.loaders.validate import validate_data


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
        print(
            f"Se encontraron {len(result.issues)} errores de validación:",
            file=sys.stderr,
        )
        for issue in result.issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    print(f"Datos válidos en {config.data_dir}:")
    for table, count in result.counts().items():
        print(f"  {table}: {count} registros")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
