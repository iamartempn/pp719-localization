"""
Аналитические функции для реестра ПП 719.
"""

import argparse
from datetime import date

import duckdb
import polars as pl


def load_data(db_path: str) -> pl.DataFrame:
    """Загружает таблицу реестра из DuckDB."""
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("SELECT * FROM реестр").pl()
    con.close()
    return df


def okved_coverage(df: pl.DataFrame) -> pl.DataFrame:
    """
    Агрегирует данные по первым 4 символам кода ОКПД2.

    Возвращает DataFrame с колонками:
    окпд2_префикс, количество_позиций, количество_производителей, ср_баллы.
    """
    result = (
        df.with_columns(
            pl.col("окпд2").str.slice(0, 4).alias("окпд2_префикс")
        )
        .group_by("окпд2_префикс")
        .agg(
            pl.len().alias("количество_позиций"),
            pl.col("инн").n_unique().alias("количество_производителей"),
            pl.col("баллы").mean().alias("ср_баллы"),
        )
        .sort("количество_позиций", descending=True)
    )
    return result


def producer_stats(df: pl.DataFrame) -> pl.DataFrame:
    """
    Вычисляет агрегированные показатели по производителям.

    Группирует по ИНН и наименованию предприятия, возвращает
    число позиций, средние баллы, охват ОКПД2 и счётчики флагов.
    """
    result = (
        df.with_columns(
            pl.col("окпд2").str.slice(0, 4).alias("окпд2_префикс")
        )
        .group_by(["инн", "предприятие"])
        .agg(
            pl.len().alias("позиций"),
            pl.col("баллы").mean().alias("ср_баллы"),
            pl.col("окпд2_префикс").n_unique().alias("охват_окпд2"),
            pl.col("флаг_ии").cast(pl.Int32).sum().alias("флаг_ии_count"),
            pl.col("флаг_высокотех").cast(pl.Int32).sum().alias("флаг_высокотех_count"),
        )
        .sort("позиций", descending=True)
    )
    return result


def score_distribution(df: pl.DataFrame) -> pl.DataFrame:
    """
    Строит гистограмму распределения баллов по фиксированным диапазонам.

    Возвращает DataFrame с колонками: диапазон, количество.
    """
    bins = [
        ("0-50", 0, 50),
        ("50-100", 50, 100),
        ("100-200", 100, 200),
        ("200-500", 200, 500),
        ("500+", 500, float("inf")),
    ]

    rows = []
    scores = df["баллы"].drop_nulls()
    for label, low, high in bins:
        if high == float("inf"):
            count = (scores >= low).sum()
        else:
            count = ((scores >= low) & (scores < high)).sum()
        rows.append({"диапазон": label, "количество": count})

    return pl.DataFrame(rows)


def active_vs_expired(df: pl.DataFrame) -> dict:
    """
    Подсчитывает количество активных, истёкших и прекращённых записей.

    Активные: срок_действия > сегодня.
    Истёкшие: срок_действия <= сегодня.
    Прекращённые: дата_прекращения заполнена.
    """
    today = date.today()

    if "срок_действия" in df.columns:
        active = (
            df["срок_действия"]
            .is_not_null()
            .cast(pl.Int32)
            .sum()
        )
        non_null = df.filter(pl.col("срок_действия").is_not_null())
        active_count = non_null.filter(pl.col("срок_действия") > today).height
        expired_count = non_null.filter(pl.col("срок_действия") <= today).height
    else:
        active_count = 0
        expired_count = 0

    if "дата_прекращения" in df.columns:
        terminated_count = df["дата_прекращения"].is_not_null().sum()
    else:
        terminated_count = 0

    return {
        "активных": active_count,
        "истёкших": expired_count,
        "прекращённых": terminated_count,
    }


def top_departments(df: pl.DataFrame, n: int = 15) -> pl.DataFrame:
    """
    Возвращает топ-N департаментов по количеству позиций.

    Группировка по заключение_департамент.
    """
    result = (
        df.filter(pl.col("заключение_департамент").is_not_null())
        .group_by("заключение_департамент")
        .agg(pl.len().alias("количество_позиций"))
        .sort("количество_позиций", descending=True)
        .head(n)
    )
    return result


def main() -> None:
    """Точка входа: вывод аналитических сводок в консоль."""
    parser = argparse.ArgumentParser(description="Аналитика реестра ПП 719")
    parser.add_argument(
        "--db-path",
        default="data/registry.duckdb",
        help="Путь к файлу DuckDB",
    )
    args = parser.parse_args()

    df = load_data(args.db_path)
    print(f"Загружено записей: {len(df)}")

    print("\n--- Покрытие ОКПД2 (топ-10) ---")
    print(okved_coverage(df).head(10))

    print("\n--- Статистика производителей (топ-10) ---")
    print(producer_stats(df).head(10))

    print("\n--- Распределение баллов ---")
    print(score_distribution(df))

    print("\n--- Активные / истёкшие / прекращённые ---")
    status = active_vs_expired(df)
    for key, val in status.items():
        print(f"  {key}: {val}")

    print("\n--- Топ-15 департаментов ---")
    print(top_departments(df))


if __name__ == "__main__":
    main()
