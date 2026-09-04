from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from public_loader import (
    AXIS_VALUE,
    ALL,
    PUBLIC_TABS,
    PublicDataSecurityError,
    active_months,
    available_models,
    available_years,
    build_kpis,
    filter_model_history,
    is_partial_month,
    load_public_data,
    model_month_matrix,
    monthly_history_for_year,
    month_text,
)


APP_DIR = Path(__file__).resolve().parent
STYLE_PATH = APP_DIR / "assets" / "style.css"
PLOT_CONFIG = {"displayModeBar": False, "displaylogo": False, "responsive": True}
GREEN = "#178f5f"
GRAY = "#667085"
PALETTE = ["#178f5f", "#3f7db8", "#d28b2c", "#8a6fb0", "#339080", "#c05239", "#697386"]
FILTER_LABELS = ["年度", "月份", "型號"]
PUBLIC_NOTICE = "本頁提供型號與出貨彙總統計，不包含客戶、訂單金額或訂單明細。"


st.set_page_config(
    page_title="第二生產中心｜電動滑台出貨軸數戰情室",
    layout="wide",
)


def load_css() -> None:
    if STYLE_PATH.exists():
        st.markdown(f"<style>{STYLE_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def public_data_signature() -> tuple[tuple[str, int, int], ...]:
    data_dir = APP_DIR / "public_data"
    signature = []
    for filename in ("summary.json", "monthly_history.csv", "model_monthly.csv"):
        stat = (data_dir / filename).stat()
        signature.append((filename, stat.st_size, stat.st_mtime_ns))
    return tuple(signature)


@st.cache_data(show_spinner=False)
def cached_data(signature: tuple[tuple[str, int, int], ...]):
    return load_public_data()


def axis_text(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.0f} 軸"
    except (TypeError, ValueError):
        return "—"


def percent_text(value: Any, arrow: bool = False) -> str:
    if value is None:
        return "—"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "—"
    if not arrow:
        return f"{parsed:.1%}"
    mark = "↑" if parsed >= 0 else "↓"
    css_class = "delta-up" if parsed >= 0 else "delta-down"
    return f'<span class="{css_class}">{mark} {abs(parsed):.1%}</span>'


def generated_text(value: str) -> str:
    return value.replace("-", "/")


def generated_day(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").strftime("%Y/%m/%d")
    except ValueError:
        return value[:10].replace("-", "/")


def kpi_card(label: str, value: str, note: str = "") -> str:
    return (
        '<div class="kpi-card">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-note">{note}</div>'
        "</div>"
    )


def style_plot(fig, height: int | None = None):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Microsoft JhengHei, Arial, sans-serif", "color": "#263238", "size": 12},
        title={"font": {"size": 17}, "x": 0, "xanchor": "left"},
        margin={"l": 8, "r": 8, "t": 42, "b": 8},
        hoverlabel={"bgcolor": "white", "font_size": 12},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    if height:
        fig.update_layout(height=height)
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#e9eef0", zeroline=False)
    return fig


def monthly_trend_chart(monthly: pd.DataFrame, year: int, latest_month: int, partial: bool) -> None:
    if monthly.empty:
        st.info("目前篩選條件下沒有資料。")
        return

    trend = monthly.copy()
    trend["月份"] = trend["month"].map(lambda value: f"{int(value)}月")
    trend["狀態"] = [
        "本月累計" if partial and int(row["month"]) == latest_month else "完整月份"
        for _, row in trend.iterrows()
    ]
    avg_base = trend[trend["month"].le(latest_month)]
    avg_value = float(avg_base[AXIS_VALUE].mean()) if not avg_base.empty else 0
    fig = px.bar(
        trend,
        x="月份",
        y=AXIS_VALUE,
        title=f"{year} 每月出貨軸數",
        text=AXIS_VALUE,
        color_discrete_sequence=[GREEN],
        hover_data={"狀態": True, AXIS_VALUE: ":,.0f", "month": False},
    )
    fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside", cliponaxis=False)
    if avg_value:
        fig.add_trace(
            go.Scatter(
                x=trend["月份"],
                y=[avg_value] * len(trend),
                mode="lines",
                name=f"月平均：{avg_value:,.0f} 軸",
                line={"color": GRAY, "width": 2, "dash": "dash"},
                hovertemplate=f"月平均：{avg_value:,.0f} 軸<extra></extra>",
            )
        )
    st.plotly_chart(style_plot(fig, height=330), width="stretch", config=PLOT_CONFIG)


def top_model_chart(df: pd.DataFrame, title: str) -> None:
    if df.empty:
        st.info("目前篩選條件下沒有資料。")
        return

    chart_df = df.sort_values(AXIS_VALUE, ascending=True).copy()
    max_value = pd.to_numeric(chart_df[AXIS_VALUE], errors="coerce").fillna(0).max()
    fig = px.bar(
        chart_df,
        x=AXIS_VALUE,
        y="model",
        orientation="h",
        title=title,
        text=AXIS_VALUE,
        color_discrete_sequence=[GREEN],
        hover_data={"share": ":.1%", AXIS_VALUE: ":,.0f", "model": True},
    )
    fig.update_traces(texttemplate="%{x:,.0f}", textposition="outside", cliponaxis=False)
    fig.update_layout(yaxis={"title": "", "categoryorder": "array", "categoryarray": chart_df["model"].tolist()})
    if max_value > 0:
        fig.update_xaxes(range=[0, max_value * 1.18])
    st.plotly_chart(style_plot(fig, height=330), width="stretch", config=PLOT_CONFIG)


def structure_chart(df: pd.DataFrame, title: str) -> None:
    if df.empty:
        st.info("目前篩選條件下沒有資料。")
        return

    fig = px.pie(
        df,
        values=AXIS_VALUE,
        names="model",
        title=title,
        color_discrete_sequence=PALETTE,
        hole=0.45,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    st.plotly_chart(style_plot(fig, height=350), width="stretch", config=PLOT_CONFIG)


def top_models(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["model", AXIS_VALUE, "share", "rank"])
    grouped = df.groupby("model", as_index=False)[AXIS_VALUE].sum()
    grouped = grouped[grouped[AXIS_VALUE] > 0].sort_values(AXIS_VALUE, ascending=False).head(limit)
    total = grouped[AXIS_VALUE].sum()
    grouped["share"] = grouped[AXIS_VALUE] / total if total else 0
    grouped["rank"] = range(1, len(grouped) + 1)
    return grouped


def render_kpis(kpi: dict[str, Any], partial: bool) -> None:
    period = month_text(kpi["report_year"], kpi["report_month"])
    data_day = generated_day(kpi["generated_at"])
    mom_value = percent_text(kpi["mom_percent"], arrow=True)
    mom_note = "月對月"
    first_label = "最新月份出貨軸數"
    first_note = period
    if partial:
        first_label = "本月累計出貨軸數"
        first_note = f"資料截至 {data_day}"
        mom_value = '<span class="delta-neutral">—</span>'
        mom_note = "本月尚未結算"

    cards = [
        kpi_card(first_label, axis_text(kpi["monthly_shipment_axes"]), first_note),
        kpi_card("年度累計出貨軸數", axis_text(kpi["ytd_shipment_axes"]), f"截至 {period}"),
        kpi_card("最新月份每日平均出貨量", axis_text(kpi["avg_daily_shipment_axes"]), f"{kpi['shipment_days']} 個出貨日"),
        kpi_card("上月出貨軸數", axis_text(kpi["previous_month_axes"]), "前一月份"),
        kpi_card("月增率 MoM", mom_value, mom_note),
        kpi_card("去年同期 YoY", percent_text(kpi["yoy_percent"]), "同期比較" if kpi["yoy_percent"] is not None else "無去年同期資料"),
    ]
    st.markdown(f"<div class='kpi-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)


load_css()

try:
    data = cached_data(public_data_signature())
except PublicDataSecurityError:
    st.error("SECURITY_FAIL")
    st.stop()

summary = data.summary
partial = is_partial_month(int(summary["report_year"]), int(summary["report_month"]))
years = available_years(data.monthly_history)
selected_year = st.sidebar.selectbox(FILTER_LABELS[0], years, index=years.index(int(summary["report_year"])) if int(summary["report_year"]) in years else len(years) - 1)
year_monthly = monthly_history_for_year(data.monthly_history, int(selected_year))
months = active_months(year_monthly)
month_options = [ALL, *[f"{month}月" for month in months]]
default_month_label = f"{int(summary['report_month'])}月" if int(selected_year) == int(summary["report_year"]) else ALL
default_month_index = month_options.index(default_month_label) if default_month_label in month_options else 0
selected_month_label = st.sidebar.selectbox(FILTER_LABELS[1], month_options, index=default_month_index)
selected_month = None if selected_month_label == ALL else int(selected_month_label.replace("月", ""))
models = available_models(data.model_history, int(selected_year))
selected_model = st.sidebar.selectbox(FILTER_LABELS[2], [ALL, *models])

selected_model_history = filter_model_history(data.model_history, int(selected_year), selected_month, selected_model)
selected_monthly = year_monthly.copy()
if selected_model != ALL:
    selected_monthly = (
        selected_model_history.groupby(["year", "month"], as_index=False)[AXIS_VALUE]
        .sum()
        .merge(pd.DataFrame({"year": [int(selected_year)] * 12, "month": list(range(1, 13))}), how="right", on=["year", "month"])
        .fillna({AXIS_VALUE: 0})
        .sort_values("month")
    )
latest_month = selected_month or int(summary["report_month"])
display_kpis = build_kpis(data, int(selected_year), selected_month, selected_model)
display_partial = partial and int(selected_year) == int(summary["report_year"]) and latest_month == int(summary["report_month"])

st.markdown(
    f"""
    <div class="public-banner">
      <span>PUBLIC DASHBOARD</span>
      <strong>{PUBLIC_NOTICE}</strong>
    </div>
    <div class="dashboard-header">
      <div>
        <div class="dashboard-kicker">第二生產中心</div>
        <h1 class="dashboard-title">電動滑台出貨軸數戰情室</h1>
      </div>
      <div class="dashboard-updated">最後更新：{generated_text(summary["generated_at"])}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="status-bar">
      <span>來源：正式出貨彙總</span>
      <span>資料更新：{generated_text(summary["generated_at"])[5:]}</span>
      <span class="status-ok">資料狀態：● 統計正常</span>
      <span>{'本月累計' if display_partial else '完整月份'}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

overview_tab, monthly_tab, model_tab = st.tabs(PUBLIC_TABS)

with overview_tab:
    render_kpis(display_kpis, display_partial)
    monthly_trend_chart(selected_monthly, int(selected_year), latest_month, display_partial)
    chart_cols = st.columns(2)
    with chart_cols[0]:
        yearly_models = filter_model_history(data.model_history, int(selected_year), None, selected_model)
        top_model_chart(top_models(yearly_models), f"{int(selected_year)} 型號出貨 TOP10")
    with chart_cols[1]:
        month_models = filter_model_history(data.model_history, int(selected_year), latest_month, selected_model)
        top_model_chart(top_models(month_models), f"{month_text(int(selected_year), latest_month)} 型號出貨 TOP10")

with monthly_tab:
    st.markdown(f"<div class='section-title'>{month_text(int(selected_year), latest_month)} 月份出貨</div>", unsafe_allow_html=True)
    month_models = filter_model_history(data.model_history, int(selected_year), latest_month, selected_model)
    month_kpi_cols = st.columns(3)
    month_top = top_models(month_models)
    with month_kpi_cols[0]:
        st.metric("月份出貨軸數", axis_text(display_kpis["monthly_shipment_axes"]))
    with month_kpi_cols[1]:
        st.metric("每日平均出貨量", axis_text(display_kpis["avg_daily_shipment_axes"]))
    with month_kpi_cols[2]:
        st.metric("型號數", f"{month_models.loc[month_models[AXIS_VALUE] > 0, 'model'].nunique():,}")
    cols = st.columns([1.05, 0.95])
    with cols[0]:
        top_model_chart(month_top, "月份型號排名")
    with cols[1]:
        structure_chart(month_top, "月份結構占比")

with model_tab:
    year_models = filter_model_history(data.model_history, int(selected_year), None, selected_model)
    cols = st.columns([0.95, 1.05])
    with cols[0]:
        top_model_chart(top_models(year_models), "年度型號排名")
    with cols[1]:
        matrix = model_month_matrix(data.model_history, int(selected_year), selected_model)
        st.markdown("<div class='section-title'>型號 × 月份矩陣</div>", unsafe_allow_html=True)
        st.dataframe(matrix, width="stretch", height=390, hide_index=True)
