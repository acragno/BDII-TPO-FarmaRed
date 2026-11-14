"""Lectura de CSV"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class CsvStructureError(Exception):
    def __init__(self, filename: str, message: str, line: int | None = None) -> None:
        self.filename = filename
        self.message = message
        self.line = line
        super().__init__(str(self))

    def __str__(self) -> str:
        location = self.filename if self.line is None else f"{self.filename}:{self.line}"
        return f"{location}: {self.message}"


@dataclass(frozen=True)
class CsvRow:
    line: int
    values: dict[str, str]


def read_table(path: Path, filename: str, headers: Sequence[str]) -> list[CsvRow]:
    """No se aceptan columnas faltantes, sobrantes ni repetidas"""
    if not path.is_file():
        raise CsvStructureError(filename, "no existe")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise CsvStructureError(filename, "no tiene encabezado")

        repeated = _repeated(fieldnames)
        if repeated:
            raise CsvStructureError(
                filename, f"encabezados repetidos: {', '.join(repeated)}"
            )

        missing = [header for header in headers if header not in fieldnames]
        unexpected = [header for header in fieldnames if header not in headers]
        if missing or unexpected:
            details = []
            if missing:
                details.append("faltan: " + ", ".join(missing))
            if unexpected:
                details.append("sobran: " + ", ".join(unexpected))
            raise CsvStructureError(
                filename, "encabezado incorrecto (" + "; ".join(details) + ")"
            )

        rows: list[CsvRow] = []
        for values in reader:
            if not values or all(
                (value or "").strip() == "" for value in values.values()
            ):
                continue

            if None in values:
                raise CsvStructureError(
                    filename,
                    "la fila tiene más columnas que el encabezado",
                    reader.line_num,
                )

            missing_values = [
                header for header in headers if values.get(header) is None
            ]
            if missing_values:
                raise CsvStructureError(
                    filename,
                    "faltan valores para: " + ", ".join(missing_values),
                    reader.line_num,
                )

            rows.append(
                CsvRow(
                    line=reader.line_num,
                    values={header: values[header] for header in headers},
                )
            )

    return rows


def _repeated(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    repeated: list[str] = []
    for value in values:
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    return repeated
