"""Validación y normalización de los CSV de FarmaRed

El resultado se entrega con booleanos, números y fechas ya convertidos para que
la carga no repita conversiones.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.loaders.csv_reader import CsvRow, CsvStructureError, read_table

# Tipos de campo admitidos.
ID = "identifier"
TEXT = "text"
BOOL = "bool"
INT = "int"
NUMBER = "number"
DATE = "date"
ENUM = "enum"

PROVEEDOR_TIPOS = ("Laboratorio", "Droguería")
SUCURSAL_TIPOS = ("Farmacia", "Droguería")
FARMACEUTICO_CARGOS = ("Director Técnico", "Farmacéutico")
CONDICIONES_VENTA = ("Venta libre", "Bajo receta", "Bajo receta archivada")
RECETA_TIPOS = ("Simple", "Tratamiento prolongado", "Archivada")
RECETA_ESTADOS = ("Completada", "Vigente", "Vencida")
VENTA_TIPOS = ("Con receta", "Venta libre")
MEDIOS_PAGO = ("Obra social", "Débito", "Crédito", "Transferencia", "Efectivo")
VENTA_ESTADOS = ("Completada", "Pendiente", "Anulada")


@dataclass(frozen=True)
class FieldSpec:
    """Definición de una columna: tipo y restricciones."""

    name: str
    kind: str
    optional: bool = False
    choices: tuple[str, ...] = ()
    positive: bool = False
    non_negative: bool = False


@dataclass(frozen=True)
class TableSpec:
    """Definición de un archivo y su tabla destino."""

    filename: str
    id_field: str
    fields: tuple[FieldSpec, ...]
    references: tuple[tuple[str, str], ...] = ()
    unique_fields: tuple[str, ...] = ()

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)


TABLES: dict[str, TableSpec] = {
    "proveedores": TableSpec(
        filename="proveedores.csv",
        id_field="id_proveedor",
        fields=(
            FieldSpec("id_proveedor", ID),
            FieldSpec("razon_social", TEXT),
            FieldSpec("cuit", TEXT),
            FieldSpec("tipo", ENUM, choices=PROVEEDOR_TIPOS),
            FieldSpec("ciudad", TEXT),
            FieldSpec("provincia", TEXT),
            FieldSpec("telefono", TEXT),
            FieldSpec("activo", BOOL),
        ),
    ),
    "sucursales": TableSpec(
        filename="sucursales.csv",
        id_field="id_sucursal",
        fields=(
            FieldSpec("id_sucursal", ID),
            FieldSpec("nombre", TEXT),
            FieldSpec("tipo", ENUM, choices=SUCURSAL_TIPOS),
            FieldSpec("direccion", TEXT),
            FieldSpec("ciudad", TEXT),
            FieldSpec("provincia", TEXT),
            FieldSpec("telefono", TEXT),
            FieldSpec("activo", BOOL),
        ),
    ),
    "clientes": TableSpec(
        filename="clientes.csv",
        id_field="id_cliente",
        unique_fields=("dni",),
        fields=(
            FieldSpec("id_cliente", ID),
            FieldSpec("nombre", TEXT),
            FieldSpec("apellido", TEXT),
            FieldSpec("dni", TEXT),
            FieldSpec("email", TEXT),
            FieldSpec("telefono", TEXT),
            FieldSpec("ciudad", TEXT),
            FieldSpec("provincia", TEXT),
            FieldSpec("obra_social", TEXT),
            FieldSpec("nro_afiliado", TEXT, optional=True),
            FieldSpec("activo", BOOL),
        ),
    ),
    "farmaceuticos": TableSpec(
        filename="farmaceuticos.csv",
        id_field="id_farmaceutico",
        unique_fields=("matricula",),
        references=(("id_sucursal", "sucursales"),),
        fields=(
            FieldSpec("id_farmaceutico", ID),
            FieldSpec("nombre", TEXT),
            FieldSpec("apellido", TEXT),
            FieldSpec("matricula", TEXT),
            FieldSpec("cargo", ENUM, choices=FARMACEUTICO_CARGOS),
            FieldSpec("id_sucursal", ID),
            FieldSpec("activo", BOOL),
        ),
    ),
    "productos": TableSpec(
        filename="productos.csv",
        id_field="id_producto",
        references=(("id_proveedor", "proveedores"),),
        fields=(
            FieldSpec("id_producto", ID),
            FieldSpec("nombre", TEXT),
            FieldSpec("principio_activo", TEXT),
            FieldSpec("categoria", TEXT),
            FieldSpec("presentacion", TEXT),
            FieldSpec(
                "condicion_venta", ENUM, choices=CONDICIONES_VENTA
            ),
            FieldSpec("precio_unit", NUMBER, positive=True),
            FieldSpec("id_proveedor", ID),
            FieldSpec("activo", BOOL),
        ),
    ),
    "stock_lotes": TableSpec(
        filename="stock_lotes.csv",
        id_field="id_lote",
        references=(
            ("id_producto", "productos"),
            ("id_sucursal", "sucursales"),
        ),
        fields=(
            FieldSpec("id_lote", ID),
            FieldSpec("id_producto", ID),
            FieldSpec("id_sucursal", ID),
            FieldSpec("nro_lote", TEXT),
            FieldSpec("unidades", INT, non_negative=True),
            FieldSpec("vencimiento", DATE),
        ),
    ),
    "recetas": TableSpec(
        filename="recetas.csv",
        id_field="id_receta",
        references=(("id_cliente", "clientes"),),
        fields=(
            FieldSpec("id_receta", ID),
            FieldSpec("id_cliente", ID),
            FieldSpec("medico", TEXT),
            FieldSpec("matricula_medico", TEXT),
            FieldSpec("fecha_emision", DATE),
            FieldSpec("tipo", ENUM, choices=RECETA_TIPOS),
            FieldSpec("dispensas_autorizadas", INT, positive=True),
            FieldSpec("dispensas_realizadas", INT, non_negative=True),
            FieldSpec("proxima_dispensa", DATE, optional=True),
            FieldSpec("estado", ENUM, choices=RECETA_ESTADOS),
        ),
    ),
    "ventas": TableSpec(
        filename="ventas.csv",
        id_field="id_venta",
        references=(
            ("id_cliente", "clientes"),
            ("id_farmaceutico", "farmaceuticos"),
            ("id_receta", "recetas"),
        ),
        fields=(
            FieldSpec("id_venta", ID),
            FieldSpec("id_cliente", ID),
            FieldSpec("id_farmaceutico", ID),
            FieldSpec("id_receta", ID, optional=True),
            FieldSpec("fecha", DATE),
            FieldSpec("tipo", ENUM, choices=VENTA_TIPOS),
            FieldSpec("medio_pago", ENUM, choices=MEDIOS_PAGO),
            FieldSpec("total", NUMBER, non_negative=True),
            FieldSpec("estado", ENUM, choices=VENTA_ESTADOS),
        ),
    ),
    "detalle_ventas": TableSpec(
        filename="detalle_ventas.csv",
        id_field="id_detalle",
        references=(
            ("id_venta", "ventas"),
            ("id_producto", "productos"),
        ),
        fields=(
            FieldSpec("id_detalle", ID),
            FieldSpec("id_venta", ID),
            FieldSpec("id_producto", ID),
            FieldSpec("cantidad", INT, positive=True),
            FieldSpec("precio_unit", NUMBER, positive=True),
        ),
    ),
}


@dataclass(frozen=True)
class ValidationIssue:
    filename: str
    line: int | None
    message: str

    def __str__(self) -> str:
        location = self.filename if self.line is None else f"{self.filename}:{self.line}"
        return f"{location}: {self.message}"


@dataclass
class ValidationResult:
    """Filas normalizadas por tabla y errores encontrados."""

    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in self.records.items()}


@dataclass
class _ParsedRow:
    filename: str
    line: int
    data: dict[str, Any]


def validate_data(data_dir: Path, *extra_dirs: Path) -> ValidationResult:
    """Valida los directorios como un único dataset, incluidas sus referencias."""
    result = ValidationResult()

    for directory in (data_dir, *extra_dirs):
        if not directory.is_dir():
            result.issues.append(
                ValidationIssue(
                    str(directory), None, "no existe el directorio de datos"
                )
            )
    if result.issues:
        return result

    parsed: dict[str, list[_ParsedRow]] = {}
    structure_failed = False

    for name, spec in TABLES.items():
        rows: list[_ParsedRow] = []
        for directory in (data_dir, *extra_dirs):
            filename = (
                spec.filename
                if directory == data_dir
                else str(directory / spec.filename)
            )
            try:
                csv_rows = read_table(
                    directory / spec.filename, filename, spec.headers
                )
            except CsvStructureError as error:
                result.issues.append(
                    ValidationIssue(error.filename, error.line, error.message)
                )
                structure_failed = True
                continue

            rows.extend(_normalize_rows(spec, csv_rows, result.issues, filename))
        _check_unique_fields(spec, rows, result.issues)
        parsed[name] = rows
        result.records[name] = [row.data for row in rows]

    if structure_failed:
        return result

    _check_references(parsed, result.issues)
    _check_recipe_rules(parsed, result.issues)
    _check_sale_recipe_client(parsed, result.issues)

    return result


def _normalize_rows(
    spec: TableSpec,
    csv_rows: list[CsvRow],
    issues: list[ValidationIssue],
    filename: str,
) -> list[_ParsedRow]:
    rows: list[_ParsedRow] = []

    for csv_row in csv_rows:
        data: dict[str, Any] = {}
        for field_spec in spec.fields:
            raw = csv_row.values.get(field_spec.name, "")
            try:
                data[field_spec.name] = _convert(field_spec, raw)
            except ValueError as error:
                data[field_spec.name] = None
                issues.append(
                    ValidationIssue(
                        filename,
                        csv_row.line,
                        f"{field_spec.name}: {error}",
                    )
                )

        if data.get(spec.id_field):
            rows.append(
                _ParsedRow(filename=filename, line=csv_row.line, data=data)
            )

    return rows


def _convert(field_spec: FieldSpec, raw: str) -> Any:
    value = (raw or "").strip()

    if value == "":
        if field_spec.optional:
            return None
        raise ValueError("valor obligatorio vacío")

    if field_spec.kind in (ID, TEXT):
        return value

    if field_spec.kind == BOOL:
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        raise ValueError(
            f"booleano inválido: '{value}' (se espera true o false)"
        )

    if field_spec.kind == DATE:
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(
                f"fecha inválida: '{value}' (se espera AAAA-MM-DD)"
            ) from error

    if field_spec.kind == ENUM:
        if value not in field_spec.choices:
            raise ValueError(
                "valor inválido: '{}' (permitidos: {})".format(
                    value, ", ".join(field_spec.choices)
                )
            )
        return value

    if field_spec.kind == INT:
        try:
            number = int(value)
        except ValueError as error:
            raise ValueError(
                f"se espera un entero, se recibió '{value}'"
            ) from error
        return _check_range(field_spec, number, value)

    if field_spec.kind == NUMBER:
        number = _parse_number(value)
        return _check_range(field_spec, number, value)

    raise ValueError(f"tipo de campo desconocido: {field_spec.kind}")


def _parse_number(value: str) -> int | float:
    try:
        return int(value)
    except ValueError:
        pass

    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(
            f"se espera un número, se recibió '{value}'"
        ) from error

    if not math.isfinite(number):
        raise ValueError(f"número inválido: '{value}'")
    return number


def _check_range(
    field_spec: FieldSpec, number: int | float, raw: str
) -> int | float:
    if field_spec.positive and number <= 0:
        raise ValueError(f"debe ser mayor que cero, se recibió '{raw}'")
    if field_spec.non_negative and number < 0:
        raise ValueError(f"no puede ser negativo, se recibió '{raw}'")
    return number


def _check_unique_fields(
    spec: TableSpec, rows: list[_ParsedRow], issues: list[ValidationIssue]
) -> None:
    for field_name in (spec.id_field, *spec.unique_fields):
        seen: dict[Any, _ParsedRow] = {}
        for row in rows:
            value = row.data.get(field_name)
            if value is None:
                continue
            previous = seen.get(value)
            if previous is not None:
                issues.append(
                    ValidationIssue(
                        row.filename,
                        row.line,
                        f"{field_name} duplicado: '{value}' "
                        f"(también en {previous.filename}:{previous.line})",
                    )
                )
            else:
                seen[value] = row


def _check_references(
    parsed: dict[str, list[_ParsedRow]], issues: list[ValidationIssue]
) -> None:
    for name, spec in TABLES.items():
        for field_name, target_name in spec.references:
            target_spec = TABLES[target_name]
            target_ids = {
                row.data[target_spec.id_field]
                for row in parsed[target_name]
                if row.data.get(target_spec.id_field)
            }

            for row in parsed[name]:
                value = row.data.get(field_name)
                if value is None:
                    continue
                if value not in target_ids:
                    issues.append(
                        ValidationIssue(
                            row.filename,
                            row.line,
                            f"{field_name} '{value}' no existe en "
                            f"{target_spec.filename}",
                        )
                    )


def _check_recipe_rules(
    parsed: dict[str, list[_ParsedRow]], issues: list[ValidationIssue]
) -> None:
    for row in parsed["recetas"]:
        authorized = row.data.get("dispensas_autorizadas")
        used = row.data.get("dispensas_realizadas")
        if isinstance(authorized, int) and isinstance(used, int):
            if used > authorized:
                issues.append(
                    ValidationIssue(
                        row.filename,
                        row.line,
                        f"dispensas_realizadas ({used}) supera "
                        f"dispensas_autorizadas ({authorized})",
                    )
                )


def _check_sale_recipe_client(
    parsed: dict[str, list[_ParsedRow]], issues: list[ValidationIssue]
) -> None:
    recipe_client = {
        row.data["id_receta"]: row.data.get("id_cliente")
        for row in parsed["recetas"]
        if row.data.get("id_receta")
    }
    for row in parsed["ventas"]:
        recipe_id = row.data.get("id_receta")
        if not recipe_id:
            continue
        expected_client = recipe_client.get(recipe_id)
        if expected_client is None:
            continue  # referencia inexistente: ya se informó antes
        if row.data.get("id_cliente") != expected_client:
            issues.append(
                ValidationIssue(
                    row.filename,
                    row.line,
                    f"id_receta '{recipe_id}' pertenece al cliente "
                    f"'{expected_client}', no a '{row.data.get('id_cliente')}'",
                )
            )
