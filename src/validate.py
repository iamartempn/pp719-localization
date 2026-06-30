"""
Валидация схемы данных реестра ПП 719 с помощью pandera.
"""

import argparse
from collections import defaultdict

import duckdb
import pandera.polars as pa
import polars as pl
from pandera.typing.polars import Series


class RegistrySchema(pa.DataFrameModel):
    """Схема валидации реестровых записей."""

    инн: Series[str] = pa.Field(nullable=False)
    рег_номер: Series[str] = pa.Field(nullable=False)
    наименование: Series[str] = pa.Field(nullable=False)
    окпд2: Series[str] = pa.Field(nullable=False)
    баллы: Series[float] = pa.Field(nullable=True, ge=0, le=3000)
    срок_действия: Series[pl.Date] = pa.Field(nullable=False)

    class Config:
        coerce = True


def validate(df: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """
    Валидирует DataFrame по схеме реестра.

    Возвращает кортеж (valid_df, report), где report содержит
    n_total, n_valid, n_invalid, error_counts_by_column.
    """
    n_total = len(df)
    error_counts: dict[str, int] = defaultdict(int)
    invalid_mask = pl.Series("invalid", [False] * n_total)

    # Проверяем обязательные строковые поля на null
    for col in ("инн", "рег_номер", "наименование", "окпд2"):
        if col in df.columns:
            null_mask = df[col].is_null()
            error_counts[col] += null_mask.sum()
            invalid_mask = invalid_mask | null_mask

    # Проверяем срок_действия на null
    if "срок_действия" in df.columns:
        null_mask = df["срок_действия"].is_null()
        error_counts["срок_действия"] += null_mask.sum()
        invalid_mask = invalid_mask | null_mask

    # Проверяем диапазон баллов
    if "баллы" in df.columns:
        out_of_range = df["баллы"].is_not_null() & (
            (df["баллы"] < 0) | (df["баллы"] > 3000)
        )
        error_counts["баллы"] += out_of_range.sum()
        invalid_mask = invalid_mask | out_of_range

    valid_df = df.filter(~invalid_mask)
    n_valid = len(valid_df)
    n_invalid = n_total - n_valid

    report = {
        "n_total": n_total,
        "n_valid": n_valid,
        "n_invalid": n_invalid,
        "error_counts_by_column": dict(error_counts),
    }

    return valid_df, report


def main() -> None:
    """Точка входа: загрузка из DuckDB и вывод отчёта валидации."""
    parser = argparse.ArgumentParser(description="Валидация данных реестра ПП 719")
    parser.add_argument(
        "--db-path",
        default="data/registry.duckdb",
        help="Путь к файлу DuckDB",
    )
    args = parser.parse_args()

    con = duckdb.connect(args.db_path)
    df = con.execute("SELECT * FROM реестр").pl()
    con.close()

    _, report = validate(df)

    print(f"Всего записей:    {report['n_total']}")
    print(f"Валидных:         {report['n_valid']}")
    print(f"Невалидных:       {report['n_invalid']}")
    print("Ошибки по колонкам:")
    for col, cnt in report["error_counts_by_column"].items():
        print(f"  {col}: {cnt}")


if __name__ == "__main__":
    main()
