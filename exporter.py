from __future__ import annotations

import math
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from models import LotResult

TIMEZONE = ZoneInfo("Europe/Kyiv")
DEFAULT_OUTPUT_DIR = "output"
ROW_HEIGHT_PER_LINE = 15

LINK_FONT = Font(color="0563C1", underline="single")
HEADER_FONT = Font(bold=True)

KIND_ALIGNMENT: dict[str, Alignment] = {
    "numeric": Alignment(horizontal="center", vertical="center"),
    "text": Alignment(horizontal="left", vertical="center", wrap_text=True),
    "link": Alignment(horizontal="left", vertical="center", wrap_text=True),
}

ColumnGetter = Callable[[LotResult], Any]


def _winner_field(name: str) -> ColumnGetter:
    def getter(result: LotResult) -> Any:
        return getattr(result.winner, name) if result.winner else None

    return getter


def _profile_url(result: LotResult) -> Optional[str]:
    username = result.winner.username if result.winner else None
    return f"https://t.me/{username}" if username else None


COLUMNS: list[tuple[str, ColumnGetter, str]] = [
    ("Номер лоту", lambda result: result.lot.number, "numeric"),
    ("Назва", lambda result: result.lot.title, "text"),
    ("Посилання на лот", lambda result: result.lot.link, "link"),
    ("Стартова ставка", lambda result: result.lot.start_price, "numeric"),
    ("Переможна ставка", _winner_field("amount"), "numeric"),
    ("Коментар переможця", _winner_field("comment"), "text"),
    ("ПІБ", _winner_field("full_name"), "text"),
    ("Username", _profile_url, "link"),
]


def build_filename(now: Optional[datetime] = None) -> str:
    moment = now or datetime.now(TIMEZONE)
    return f"results_{moment:%H%M_%d.%m}.xlsx"


def _cell_text(value: object) -> str:
    return "" if value is None else str(value)


def export_results(
    results: list[LotResult],
    output_dir: str = DEFAULT_OUTPUT_DIR,
    now: Optional[datetime] = None,
) -> str:
    os.makedirs(output_dir, exist_ok=True)

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Результати"

    _write_header(worksheet)
    _write_rows(worksheet, results)
    _format_sheet(worksheet)
    _set_row_heights(worksheet)

    path = os.path.join(output_dir, build_filename(now))
    workbook.save(path)
    return path


def _write_header(worksheet: Worksheet) -> None:
    worksheet.append([header for header, _, _ in COLUMNS])
    for cell in worksheet[1]:
        cell.font = HEADER_FONT
        cell.alignment = _alignment(cell.column)


def _write_rows(worksheet: Worksheet, results: list[LotResult]) -> None:
    for result in results:
        worksheet.append([getter(result) for _, getter, _ in COLUMNS])
        row = worksheet[worksheet.max_row]
        for cell in row:
            _decorate_cell(cell)


def _decorate_cell(cell: Any) -> None:
    kind = COLUMNS[cell.column - 1][2]
    cell.alignment = KIND_ALIGNMENT[kind]
    if kind == "link" and cell.value:
        cell.hyperlink = cell.value
        cell.font = LINK_FONT


def _alignment(column: int) -> Alignment:
    return KIND_ALIGNMENT[COLUMNS[column - 1][2]]


def _format_sheet(worksheet: Worksheet) -> None:
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    _autosize_columns(worksheet)


def _autosize_columns(worksheet: Worksheet) -> None:
    for index, (header, _, _) in enumerate(COLUMNS, start=1):
        width = len(header)
        for row in worksheet.iter_rows(min_col=index, max_col=index):
            for cell in row:
                for line in _cell_text(cell.value).split("\n"):
                    width = max(width, len(line))
        worksheet.column_dimensions[get_column_letter(index)].width = min(width + 2, 80)


def _set_row_heights(worksheet: Worksheet) -> None:
    widths = {
        index: worksheet.column_dimensions[get_column_letter(index)].width or 8
        for index in range(1, len(COLUMNS) + 1)
    }
    for row in worksheet.iter_rows(min_row=2):
        lines = max(
            (
                _estimated_lines(_cell_text(cell.value), widths[cell.column])
                for cell in row
                if _is_text_kind(cell.column)
            ),
            default=1,
        )
        worksheet.row_dimensions[row[0].row].height = max(ROW_HEIGHT_PER_LINE, lines * ROW_HEIGHT_PER_LINE)


def _is_text_kind(column: int) -> bool:
    return COLUMNS[column - 1][2] in ("text", "link")


def _estimated_lines(value: str, width: float) -> int:
    if not value:
        return 1
    usable = max(int(width) - 1, 1)
    return sum(max(1, math.ceil(len(line) / usable)) for line in value.split("\n"))
