"""Validación de los CSV"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tests.support import DATA_DIR, EXPECTED_COUNTS, DatasetEditor
from src.loaders.validate import validate_data


def _messages(result) -> list[str]:
    return [issue.message for issue in result.issues]


def test_valid_dataset_loads_every_table() -> None:
    result = validate_data(DATA_DIR)

    assert result.ok, [str(issue) for issue in result.issues]
    assert result.counts() == EXPECTED_COUNTS


def test_extra_dataset_adds_ten_valid_records_per_table() -> None:
    result = validate_data(DATA_DIR, DATA_DIR / "extra")

    assert result.ok, [str(issue) for issue in result.issues]
    assert result.counts() == {
        table: count + 10 for table, count in EXPECTED_COUNTS.items()
    }


@pytest.mark.parametrize(
    ("filename", "id_field", "id_value", "column", "value"),
    [
        ("clientes.csv", "id_cliente", "C009", "id_cliente", "C001"),
        ("clientes.csv", "id_cliente", "C009", "dni", "31245678"),
        ("farmaceuticos.csv", "id_farmaceutico", "F008", "matricula", "MN-18041"),
    ],
)
def test_duplicates_between_original_and_extra_are_rejected(
    dataset: Path,
    filename: str,
    id_field: str,
    id_value: str,
    column: str,
    value: str,
) -> None:
    extra_dir = dataset / "extra"
    DatasetEditor(extra_dir).set_value(
        filename, id_field, id_value, column, value
    )

    result = validate_data(dataset, extra_dir)

    assert any(
        issue.filename == str(extra_dir / filename)
        and f"{column} duplicado: '{value}'" in issue.message
        for issue in result.issues
    )


def test_extra_invalid_reference_reports_its_source(dataset: Path) -> None:
    extra_dir = dataset / "extra"
    DatasetEditor(extra_dir).set_value(
        "farmaceuticos.csv", "id_farmaceutico", "F008", "id_sucursal", "S999"
    )

    result = validate_data(dataset, extra_dir)

    assert any(
        issue.filename == str(extra_dir / "farmaceuticos.csv")
        and issue.line == 2
        and "id_sucursal 'S999' no existe" in issue.message
        for issue in result.issues
    )


def test_missing_extra_file_is_rejected(dataset: Path) -> None:
    extra_dir = dataset / "extra"
    (extra_dir / "ventas.csv").unlink()

    result = validate_data(dataset, extra_dir)

    assert any(
        issue.filename == str(extra_dir / "ventas.csv")
        and issue.message == "no existe"
        for issue in result.issues
    )


def test_types_are_converted_once() -> None:
    result = validate_data(DATA_DIR)

    sale = next(
        row for row in result.records["ventas"] if row["id_venta"] == "V001"
    )
    assert sale["fecha"] == date(2025, 9, 18)
    assert isinstance(sale["fecha"], date)
    assert sale["total"] == 3850
    assert isinstance(sale["total"], int)

    client = next(
        row for row in result.records["clientes"] if row["id_cliente"] == "C005"
    )
    assert client["activo"] is True
    assert client["nro_afiliado"] is None

    recipe = next(
        row for row in result.records["recetas"] if row["id_receta"] == "RC002"
    )
    assert recipe["proxima_dispensa"] == date(2026, 9, 15)
    assert recipe["dispensas_autorizadas"] == 3

    batch = next(
        row for row in result.records["stock_lotes"] if row["id_lote"] == "L001"
    )
    assert batch["unidades"] == 120
    assert isinstance(batch["unidades"], int)
    assert batch["vencimiento"] == date(2027, 8, 31)

    decimal = next(
        row
        for row in result.records["productos"]
        if row["id_producto"] == "PRD001"
    )
    assert isinstance(decimal["precio_unit"], (int, float))


def test_missing_file_is_reported(dataset: Path) -> None:
    (dataset / "ventas.csv").unlink()

    result = validate_data(dataset)

    assert not result.ok
    assert any(
        issue.filename == "ventas.csv" and issue.message == "no existe"
        for issue in result.issues
    )


def test_missing_header_is_reported(
    dataset: Path, editor: DatasetEditor
) -> None:
    editor.drop_column("clientes.csv", "email")

    result = validate_data(dataset)

    assert not result.ok
    assert any(
        issue.filename == "clientes.csv"
        and "encabezado incorrecto" in issue.message
        and "email" in issue.message
        for issue in result.issues
    )


def test_duplicate_ids_are_reported(
    dataset: Path, editor: DatasetEditor
) -> None:
    editor.edit("ventas.csv", lambda rows: rows.append(dict(rows[0])))

    result = validate_data(dataset)

    assert not result.ok
    assert any(
        "id_venta duplicado: 'V001'" in message
        for message in _messages(result)
    )


def test_duplicate_unique_field_is_reported(
    dataset: Path, editor: DatasetEditor
) -> None:
    def copy_dni(rows: list[dict[str, str]]) -> None:
        rows[1]["dni"] = rows[0]["dni"]

    editor.edit("clientes.csv", copy_dni)

    result = validate_data(dataset)

    assert any("dni duplicado" in message for message in _messages(result))


def test_invalid_reference_is_reported(
    dataset: Path, editor: DatasetEditor
) -> None:
    def break_product(rows: list[dict[str, str]]) -> None:
        rows[0]["id_producto"] = "PRD999"

    editor.edit("detalle_ventas.csv", break_product)

    result = validate_data(dataset)

    assert any(
        "id_producto 'PRD999' no existe en productos.csv" in message
        for message in _messages(result)
    )


def test_recipe_dispensas_rule_is_checked(
    dataset: Path, editor: DatasetEditor
) -> None:
    def exceed(rows: list[dict[str, str]]) -> None:
        recipe = next(row for row in rows if row["id_receta"] == "RC001")
        recipe["dispensas_realizadas"] = "2"

    editor.edit("recetas.csv", exceed)

    result = validate_data(dataset)

    assert any(
        "dispensas_realizadas (2) supera dispensas_autorizadas (1)" in message
        for message in _messages(result)
    )


def test_sale_recipe_must_belong_to_client(
    dataset: Path, editor: DatasetEditor
) -> None:
    def change_client(rows: list[dict[str, str]]) -> None:
        sale = next(row for row in rows if row["id_venta"] == "V001")
        sale["id_cliente"] = "C005"

    editor.edit("ventas.csv", change_client)

    result = validate_data(dataset)

    assert any(
        "id_receta 'RC007' pertenece al cliente 'C004'" in message
        for message in _messages(result)
    )


@pytest.mark.parametrize(
    ("filename", "id_field", "id_value", "column", "value", "expected"),
    [
        (
            "ventas.csv",
            "id_venta",
            "V001",
            "fecha",
            "18/09/2025",
            "fecha inválida",
        ),
        (
            "clientes.csv",
            "id_cliente",
            "C001",
            "activo",
            "si",
            "booleano inválido",
        ),
        (
            "productos.csv",
            "id_producto",
            "PRD001",
            "precio_unit",
            "0",
            "debe ser mayor que cero",
        ),
        (
            "productos.csv",
            "id_producto",
            "PRD001",
            "precio_unit",
            "abc",
            "se espera un número",
        ),
        (
            "productos.csv",
            "id_producto",
            "PRD001",
            "condicion_venta",
            "Libre",
            "valor inválido",
        ),
        (
            "stock_lotes.csv",
            "id_lote",
            "L001",
            "unidades",
            "-1",
            "no puede ser negativo",
        ),
        (
            "stock_lotes.csv",
            "id_lote",
            "L001",
            "unidades",
            "muchas",
            "se espera un entero",
        ),
        (
            "clientes.csv",
            "id_cliente",
            "C001",
            "nombre",
            "",
            "valor obligatorio vacío",
        ),
    ],
)
def test_invalid_values_report_filename_and_line(
    dataset: Path,
    editor: DatasetEditor,
    filename: str,
    id_field: str,
    id_value: str,
    column: str,
    value: str,
    expected: str,
) -> None:
    editor.set_value(filename, id_field, id_value, column, value)

    result = validate_data(dataset)

    issues = [
        issue
        for issue in result.issues
        if issue.filename == filename and expected in issue.message
    ]
    assert issues, _messages(result)
    assert issues[0].line is not None and issues[0].line > 1


def test_nonexistent_data_directory(tmp_path: Path) -> None:
    result = validate_data(tmp_path / "no-existe")

    assert not result.ok
    assert result.issues[0].message == "no existe el directorio de datos"
