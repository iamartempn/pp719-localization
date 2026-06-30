"""
Streamlit-дашборд для анализа реестра ПП 719.
"""

import os
from pathlib import Path

import duckdb
import plotly.express as px
import polars as pl
import streamlit as st

from analyze import (
    load_data,
    okved_coverage,
    producer_stats,
    score_distribution,
)
from scoring import compute_producer_score

DB_PATH = "data/registry.duckdb"
EXCEL_PATH = os.environ.get("EXCEL_PATH", "data/production.xlsx")


@st.cache_data(show_spinner="Загрузка данных...")
def get_data() -> pl.DataFrame:
    """Загружает данные из DuckDB или напрямую из Excel как запасной вариант."""
    if Path(DB_PATH).exists():
        return load_data(DB_PATH)

    st.warning(
        "Файл DuckDB не найден. Загружаю из Excel - это может занять несколько минут."
    )
    from ingest import read_excel
    return read_excel(EXCEL_PATH)


@st.cache_data(show_spinner=False)
def get_producer_stats(df_hash: int) -> pl.DataFrame:
    """Вычисляет статистику производителей (кешируется по хешу данных)."""
    df = _df_cache[df_hash]
    return producer_stats(df)


@st.cache_data(show_spinner=False)
def get_okved(df_hash: int) -> pl.DataFrame:
    df = _df_cache[df_hash]
    return okved_coverage(df)


_df_cache: dict[int, pl.DataFrame] = {}


def main() -> None:
    """Главная функция дашборда."""
    st.set_page_config(
        page_title="Реестр ПП 719",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("Реестр промышленной продукции - ПП 719")

    df = get_data()

    # Кешируем df по id объекта для передачи в st.cache_data
    df_id = id(df)
    _df_cache[df_id] = df

    tabs = st.tabs(["Реестр", "Производители", "Категории ОКПД2", "Скоринг", "Истекает", "Динамика", "ТН ВЭД"])

    # ----- Вкладка: Реестр -----
    with tabs[0]:
        st.header("Реестровые записи")

        with st.sidebar:
            st.subheader("Фильтры")

            okved_df = okved_coverage(df)
            top_okved = (
                okved_df.head(20)["окпд2_префикс"].to_list()
            )
            selected_okved = st.multiselect(
                "Префикс ОКПД2 (топ-20)",
                options=top_okved,
                default=[],
            )

            предприятие_поиск = st.text_input("Поиск по предприятию", value="")

            инн_поиск = st.text_input("Поиск по ИНН (точное совпадение)", value="", key="inn_search")

            баллы_min = 0.0
            баллы_max = float(df["баллы"].drop_nulls().max() or 3000)
            баллы_range = st.slider(
                "Диапазон баллов",
                min_value=баллы_min,
                max_value=баллы_max,
                value=(баллы_min, баллы_max),
            )

        filtered = df

        if selected_okved:
            окпд2_prefix = pl.col("окпд2").str.slice(0, 4)
            filtered = filtered.filter(окпд2_prefix.is_in(selected_okved))

        if предприятие_поиск:
            filtered = filtered.filter(
                pl.col("предприятие")
                .str.to_lowercase()
                .str.contains(предприятие_поиск.lower())
            )

        if инн_поиск:
            filtered = filtered.filter(pl.col("инн") == инн_поиск.strip())

        filtered = filtered.filter(
            (pl.col("баллы").is_null())
            | (
                (pl.col("баллы") >= баллы_range[0])
                & (pl.col("баллы") <= баллы_range[1])
            )
        )

        st.metric("Записей в выборке", len(filtered))

        display_cols = [
            c for c in
            ["предприятие", "инн", "наименование", "окпд2", "баллы", "срок_действия"]
            if c in filtered.columns
        ]
        st.dataframe(
            filtered.select(display_cols).to_pandas(),
            use_container_width=True,
            height=500,
        )

    # ----- Вкладка: Производители -----
    with tabs[1]:
        st.header("Аналитика по производителям")

        prod_df = producer_stats(df)

        top20_prod = prod_df.head(20).to_pandas()
        fig_bar = px.bar(
            top20_prod,
            x="позиций",
            y="предприятие",
            orientation="h",
            title="Топ-20 производителей по числу позиций",
            labels={"позиций": "Количество позиций", "предприятие": "Предприятие"},
        )
        fig_bar.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_bar, use_container_width=True)

        scatter_df = prod_df.drop_nulls(subset=["ср_баллы", "охват_окпд2"]).to_pandas()
        fig_scatter = px.scatter(
            scatter_df,
            x="охват_окпд2",
            y="ср_баллы",
            size="позиций",
            hover_data=["предприятие", "инн"],
            title="Средние баллы vs охват ОКПД2 (размер = число позиций)",
            labels={
                "охват_окпд2": "Охват ОКПД2 (уникальных категорий)",
                "ср_баллы": "Средние баллы",
            },
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

    # ----- Вкладка: Категории ОКПД2 -----
    with tabs[2]:
        st.header("Анализ товарных категорий ОКПД2")

        okved_df = okved_coverage(df)
        top30 = okved_df.head(30).to_pandas()

        fig_okved = px.bar(
            top30,
            x="количество_позиций",
            y="окпд2_префикс",
            orientation="h",
            title="Топ-30 категорий ОКПД2 по числу позиций",
            labels={
                "количество_позиций": "Количество позиций",
                "окпд2_префикс": "Код ОКПД2",
            },
        )
        fig_okved.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_okved, use_container_width=True)

        st.subheader("Средние баллы по категориям")
        st.dataframe(
            okved_df.select(["окпд2_префикс", "количество_позиций", "количество_производителей", "ср_баллы"])
            .to_pandas(),
            use_container_width=True,
            height=400,
        )

    # ----- Вкладка: Скоринг -----
    with tabs[3]:
        st.header("Рейтинг производителей по составному скору")

        prod_df = producer_stats(df)
        scored_df = compute_producer_score(prod_df)

        top50 = scored_df.head(50).to_pandas()
        st.dataframe(
            top50[
                [c for c in
                 ["rank_position", "предприятие", "инн", "composite_score",
                  "ср_баллы", "позиций", "охват_окпд2",
                  "позиций_norm", "охват_норм", "ср_баллы_norm"]
                 if c in top50.columns]
            ],
            use_container_width=True,
            height=500,
        )

        top20_scored = scored_df.head(20).to_pandas()
        fig_score = px.bar(
            top20_scored,
            x="composite_score",
            y="предприятие",
            orientation="h",
            title="Топ-20 производителей по composite_score",
            labels={
                "composite_score": "Составной скор",
                "предприятие": "Предприятие",
            },
        )
        fig_score.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_score, use_container_width=True)

    # ----- Вкладка: Истекает -----
    with tabs[4]:
        st.header("Записи с истекающим сроком действия")

        from datetime import date, timedelta
        today = date.today()
        deadline = today + timedelta(days=90)

        if "срок_действия" in df.columns:
            expiring = df.filter(
                pl.col("срок_действия").is_not_null()
                & (pl.col("срок_действия") >= today)
                & (pl.col("срок_действия") <= deadline)
            ).sort("срок_действия")

            st.metric("Записей истекает в течение 90 дней", len(expiring))

            if len(expiring) > 0:
                display_cols = [c for c in
                    ["предприятие", "инн", "наименование", "окпд2", "баллы", "срок_действия"]
                    if c in expiring.columns]
                st.dataframe(
                    expiring.select(display_cols).to_pandas(),
                    use_container_width=True,
                    height=400,
                )
            else:
                st.info("Нет записей с истекающим сроком в течение 90 дней.")
        else:
            st.info("Данные о сроке действия недоступны.")

    # ----- Вкладка: Динамика -----
    with tabs[5]:
        st.header("Динамика реестра по годам внесения")

        from analyze import entries_by_year
        year_df = entries_by_year(df)

        if len(year_df) > 0:
            fig_year = px.line(
                year_df.to_pandas(),
                x="год",
                y="количество",
                title="Число новых записей по году внесения в реестр",
                labels={"год": "Год", "количество": "Число записей"},
                markers=True,
            )
            fig_year.update_layout(height=400)
            st.plotly_chart(fig_year, use_container_width=True)
            st.dataframe(year_df.to_pandas(), use_container_width=True, hide_index=True)
        else:
            st.info("Данные о дате внесения недоступны.")

    # ----- Вкладка: ТН ВЭД -----
    with tabs[6]:
        st.header("Топ-20 категорий ТН ВЭД")

        from analyze import tnved_coverage
        tnved_df = tnved_coverage(df, n=20)

        if len(tnved_df) > 0:
            fig_tnved = px.bar(
                tnved_df.to_pandas(),
                x="количество_позиций",
                y="тнвэд_префикс",
                orientation="h",
                title="Топ-20 категорий ТН ВЭД по числу позиций",
                labels={
                    "количество_позиций": "Количество позиций",
                    "тнвэд_префикс": "Код ТН ВЭД",
                },
                color="ср_баллы",
                color_continuous_scale="Viridis",
            )
            fig_tnved.update_layout(
                yaxis={"categoryorder": "total ascending"},
                height=500,
            )
            st.plotly_chart(fig_tnved, use_container_width=True)
            st.dataframe(tnved_df.to_pandas(), use_container_width=True, hide_index=True)
        else:
            st.info("Данные о ТН ВЭД недоступны.")


if __name__ == "__main__":
    main()
