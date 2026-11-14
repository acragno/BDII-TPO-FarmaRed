from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
TEST_DB = "farmared_pytest"

EXPECTED_COUNTS = {
    "proveedores": 5,
    "sucursales": 5,
    "clientes": 8,
    "farmaceuticos": 7,
    "productos": 13,
    "stock_lotes": 18,
    "recetas": 9,
    "ventas": 16,
    "detalle_ventas": 22,
}


class DatasetEditor:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def read(self, filename: str) -> tuple[list[str], list[dict[str, str]]]:
        with (self.directory / filename).open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            return list(reader.fieldnames or ()), list(reader)

    def write(
        self,
        filename: str,
        fieldnames: list[str],
        rows: list[dict[str, str]],
    ) -> None:
        with (self.directory / filename).open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fieldnames, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)

    def edit(
        self, filename: str, change: Callable[[list[dict[str, str]]], None]
    ) -> None:
        fieldnames, rows = self.read(filename)
        change(rows)
        self.write(filename, fieldnames, rows)

    def drop_column(self, filename: str, column: str) -> None:
        fieldnames, rows = self.read(filename)
        fieldnames.remove(column)
        for row in rows:
            row.pop(column, None)
        self.write(filename, fieldnames, rows)

    def find(self, filename: str, field: str, value: str) -> dict[str, str]:
        _, rows = self.read(filename)
        for row in rows:
            if row[field] == value:
                return row
        raise AssertionError(f"no se encontró {field}={value} en {filename}")

    def set_value(
        self,
        filename: str,
        field: str,
        value: str,
        column: str,
        new_value: str,
    ) -> None:
        def change(rows: list[dict[str, str]]) -> None:
            for row in rows:
                if row[field] == value:
                    row[column] = new_value
                    return
            raise AssertionError(f"no se encontró {field}={value} en {filename}")

        self.edit(filename, change)
