"""
Составной скоринг производителей по реестру ПП 719.
"""

import polars as pl


def _minmax_norm(series: pl.Series) -> pl.Series:
    """Нормирует Series методом min-max к диапазону [0, 1]."""
    min_val = series.min()
    max_val = series.max()
    if max_val == min_val:
        return pl.Series(series.name, [0.0] * len(series))
    return (series - min_val) / (max_val - min_val)


def compute_producer_score(df: pl.DataFrame) -> pl.DataFrame:
    """
    Вычисляет составной показатель для каждого производителя.

    Входной DataFrame - результат функции producer_stats из analyze.py.
    Формула:
        composite_score = ср_баллы_norm * 0.4 + позиций_norm * 0.3 + охват_норм * 0.3

    Возвращает DataFrame, отсортированный по composite_score по убыванию,
    с добавленными колонками нормировок, composite_score и rank_position.
    """
    позиций_norm = _minmax_norm(df["позиций"].cast(pl.Float64))
    охват_норм = _minmax_norm(df["охват_окпд2"].cast(pl.Float64))

    ср_баллы = df["ср_баллы"].fill_null(0.0)
    max_баллы = ср_баллы.max()
    if max_баллы and max_баллы > 0:
        ср_баллы_norm = ср_баллы / max_баллы
    else:
        ср_баллы_norm = pl.Series("ср_баллы_norm", [0.0] * len(df))

    composite_score = (
        ср_баллы_norm * 0.4 + позиций_norm * 0.3 + охват_норм * 0.3
    )

    result = df.with_columns(
        позиций_norm.alias("позиций_norm"),
        охват_норм.alias("охват_норм"),
        ср_баллы_norm.alias("ср_баллы_norm"),
        composite_score.alias("composite_score"),
    ).sort("composite_score", descending=True)

    rank = pl.Series("rank_position", list(range(1, len(result) + 1)))
    result = result.with_columns(rank)

    return result
