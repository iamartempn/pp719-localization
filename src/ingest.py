"""
Загрузка данных реестра ПП 719 из Excel-файла в DuckDB.
"""

import argparse
from datetime import datetime, date

import duckdb
import openpyxl
import polars as pl


# Имена колонок в порядке столбцов Excel
COLUMN_NAMES = [
    "предприятие",
    "инн",
    "огрн",
    "адрес_факт",
    "адрес_произв",
    "рег_номер_первичный",
    "рег_номер",
    "номер_паспорта",
    "дата_внесения",
    "срок_действия",
    "дата_прекращения",
    "наименование",
    "окпд2",
    "тн_вэд",
    "изготовлена_по",
    "баллы",
    "процент",
    "о_соответствии",
    "флаг_ии",
    "флаг_высокотех",
    "флаг_пак",
    "основание_наименование",
    "основание_дата",
    "основание_номер",
    "основание_срок",
    "заключение_департамент",
    "заключение_номер",
    "заключение_документ",
]


def _to_date(value) -> date | None:
    """Приводит значение ячейки к типу date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _to_float(value) -> float | None:
    """Приводит значение ячейки к float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_bool(value) -> bool | None:
    """Приводит значение ячейки к bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("да", "yes", "true", "1", "+"):
            return True
        if normalized in ("нет", "no", "false", "0", "-"):
            return False
    return None


def _to_str(value) -> str | None:
    """Приводит значение ячейки к строке."""
    if value is None:
        return None
    return str(value).strip() if str(value).strip() else None


def read_excel(path: str) -> pl.DataFrame:
    """
    Читает Excel-файл реестра и возвращает DataFrame.

    Строка 0 и 1 (0-индексация) пропускаются.
    Строка 2 - заголовок (не используется, имена задаются явно).
    Данные начинаются со строки 3.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    rows_iter = ws.iter_rows(values_only=True)

    # Пропускаем строки 0 и 1
    next(rows_iter)
    next(rows_iter)
    # Пропускаем строку заголовка (строка 2)
    next(rows_iter)

    records = []
    for row in rows_iter:
        # Пропускаем полностью пустые строки
        if all(cell is None for cell in row):
            continue

        record = {}

        # Строковые поля (индекс 1=инн и 2=огрн обрабатываются ниже явно)
        for idx in (0, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 17, 21, 23, 24, 25, 26, 27):
            col = COLUMN_NAMES[idx]
            record[col] = _to_str(row[idx] if idx < len(row) else None)

        # ИНН и ОГРН - строка с сохранением ведущих нулей
        record["инн"] = _to_str(row[1] if len(row) > 1 else None)
        record["огрн"] = _to_str(row[2] if len(row) > 2 else None)

        # Даты
        record["дата_внесения"] = _to_date(row[8] if len(row) > 8 else None)
        record["срок_действия"] = _to_date(row[9] if len(row) > 9 else None)
        record["основание_дата"] = _to_date(row[22] if len(row) > 22 else None)

        # Числовые поля
        record["баллы"] = _to_float(row[15] if len(row) > 15 else None)
        record["процент"] = _to_float(row[16] if len(row) > 16 else None)

        # Булевые поля
        record["флаг_ии"] = _to_bool(row[18] if len(row) > 18 else None)
        record["флаг_высокотех"] = _to_bool(row[19] if len(row) > 19 else None)
        record["флаг_пак"] = _to_bool(row[20] if len(row) > 20 else None)

        records.append(record)

    wb.close()

    df = pl.DataFrame(
        records,
        schema={
            "предприятие": pl.Utf8,
            "инн": pl.Utf8,
            "огрн": pl.Utf8,
            "адрес_факт": pl.Utf8,
            "адрес_произв": pl.Utf8,
            "рег_номер_первичный": pl.Utf8,
            "рег_номер": pl.Utf8,
            "номер_паспорта": pl.Utf8,
            "дата_внесения": pl.Date,
            "срок_действия": pl.Date,
            "дата_прекращения": pl.Utf8,
            "наименование": pl.Utf8,
            "окпд2": pl.Utf8,
            "тн_вэд": pl.Utf8,
            "изготовлена_по": pl.Utf8,
            "баллы": pl.Float64,
            "процент": pl.Float64,
            "о_соответствии": pl.Utf8,
            "флаг_ии": pl.Boolean,
            "флаг_высокотех": pl.Boolean,
            "флаг_пак": pl.Boolean,
            "основание_наименование": pl.Utf8,
            "основание_дата": pl.Date,
            "основание_номер": pl.Utf8,
            "основание_срок": pl.Utf8,
            "заключение_департамент": pl.Utf8,
            "заключение_номер": pl.Utf8,
            "заключение_документ": pl.Utf8,
        },
    )

    return df


def save_to_duckdb(df: pl.DataFrame, db_path: str) -> None:
    """Сохраняет DataFrame в таблицу 'реестр' базы DuckDB."""
    con = duckdb.connect(db_path)
    con.execute("DROP TABLE IF EXISTS реестр")
    con.execute("CREATE TABLE реестр AS SELECT * FROM df")
    con.close()


def main() -> None:
    """Точка входа: загрузка Excel и сохранение в DuckDB."""
    parser = argparse.ArgumentParser(description="Загрузка реестра ПП 719 в DuckDB")
    parser.add_argument(
        "--excel-path",
        default="data/production.xlsx",
        help="Путь к Excel-файлу реестра",
    )
    parser.add_argument(
        "--db-path",
        default="data/registry.duckdb",
        help="Путь к файлу DuckDB",
    )
    args = parser.parse_args()

    print(f"Читаю файл: {args.excel_path}")
    df = read_excel(args.excel_path)
    print(f"Прочитано строк: {len(df)}")

    print(f"Сохраняю в DuckDB: {args.db_path}")
    save_to_duckdb(df, args.db_path)
    print("Готово.")


if __name__ == "__main__":
    main()
