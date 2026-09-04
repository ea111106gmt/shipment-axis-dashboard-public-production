from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "public_data"
SUMMARY_PATH = DATA_DIR / "summary.json"
MONTHLY_HISTORY_PATH = DATA_DIR / "monthly_history.csv"
MODEL_HISTORY_PATH = DATA_DIR / "model_monthly.csv"
AXIS_VALUE = "shipment_axes"
ALL = "全部"
PUBLIC_TABS = ["總覽", "月出貨", "型號分析"]
SUMMARY_FIELDS = [
    "report_year",
    "report_month",
    "monthly_shipment_axes",
    "ytd_shipment_axes",
    "shipment_days",
    "avg_daily_shipment_axes",
    "previous_month_axes",
    "mom_percent",
    "yoy_percent",
    "data_period",
    "generated_at",
]
MONTHLY_HISTORY_FIELDS = ["year", "month", "shipment_axes"]
MODEL_HISTORY_FIELDS = ["year", "month", "model", "shipment_axes"]


class PublicDataSecurityError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicDashboardData:
    summary: dict[str, Any]
    monthly_history: pd.DataFrame
    model_history: pd.DataFrame


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PublicDataSecurityError(f"INVALID_JSON:{path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicDataSecurityError(f"INVALID_JSON_OBJECT:{path.name}")
    return payload


def _require_exact_order(actual: list[str], expected: list[str], label: str) -> None:
    if actual != expected:
        raise PublicDataSecurityError(f"{label}_SCHEMA_FAIL")


def _require_int(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PublicDataSecurityError(f"{label}_MUST_BE_INTEGER")
    if value < minimum:
        raise PublicDataSecurityError(f"{label}_OUT_OF_RANGE")
    return value


def _require_number_or_none(value: Any, label: str) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PublicDataSecurityError(f"{label}_MUST_BE_NUMBER_OR_NULL")
    return value


def _validate_summary(summary: dict[str, Any]) -> None:
    _require_exact_order(list(summary.keys()), SUMMARY_FIELDS, "SUMMARY")
    report_month = _require_int(summary["report_month"], "report_month", minimum=1)
    if report_month > 12:
        raise PublicDataSecurityError("report_month_OUT_OF_RANGE")
    _require_int(summary["report_year"], "report_year", minimum=2000)
    _require_int(summary["monthly_shipment_axes"], "monthly_shipment_axes")
    _require_int(summary["ytd_shipment_axes"], "ytd_shipment_axes")
    _require_int(summary["shipment_days"], "shipment_days")
    _require_int(summary["previous_month_axes"], "previous_month_axes")
    if isinstance(summary["avg_daily_shipment_axes"], bool) or not isinstance(summary["avg_daily_shipment_axes"], (int, float)):
        raise PublicDataSecurityError("avg_daily_shipment_axes_MUST_BE_NUMBER")
    _require_number_or_none(summary["mom_percent"], "mom_percent")
    _require_number_or_none(summary["yoy_percent"], "yoy_percent")
    if summary["data_period"] != f"{summary['report_year']}/{summary['report_month']:02d}":
        raise PublicDataSecurityError("data_period_MISMATCH")
    try:
        datetime.strptime(summary["generated_at"], "%Y-%m-%d %H:%M")
    except (TypeError, ValueError) as exc:
        raise PublicDataSecurityError("generated_at_FORMAT_FAIL") from exc


def _validate_monthly(history: pd.DataFrame) -> pd.DataFrame:
    _require_exact_order(list(history.columns), MONTHLY_HISTORY_FIELDS, "MONTHLY_HISTORY")
    if history.empty:
        raise PublicDataSecurityError("MONTHLY_HISTORY_EMPTY")
    normalized = history.copy()
    for column in MONTHLY_HISTORY_FIELDS:
        normalized[column] = pd.to_numeric(normalized[column], errors="raise").astype("int64")
    if not normalized["month"].between(1, 12).all():
        raise PublicDataSecurityError("MONTHLY_MONTH_OUT_OF_RANGE")
    if not (normalized[AXIS_VALUE] >= 0).all():
        raise PublicDataSecurityError("MONTHLY_AXIS_OUT_OF_RANGE")
    return normalized.sort_values(["year", "month"]).reset_index(drop=True)


def _validate_model(history: pd.DataFrame) -> pd.DataFrame:
    _require_exact_order(list(history.columns), MODEL_HISTORY_FIELDS, "MODEL_HISTORY")
    if history.empty:
        raise PublicDataSecurityError("MODEL_HISTORY_EMPTY")
    normalized = history.copy()
    for column in ("year", "month", AXIS_VALUE):
        normalized[column] = pd.to_numeric(normalized[column], errors="raise").astype("int64")
    normalized["model"] = normalized["model"].astype(str).str.strip()
    if (normalized["model"] == "").any():
        raise PublicDataSecurityError("MODEL_REQUIRED")
    if not normalized["month"].between(1, 12).all():
        raise PublicDataSecurityError("MODEL_MONTH_OUT_OF_RANGE")
    if not (normalized[AXIS_VALUE] >= 0).all():
        raise PublicDataSecurityError("MODEL_AXIS_OUT_OF_RANGE")
    return normalized.sort_values(["year", "month", "model"]).reset_index(drop=True)


def load_public_data(data_dir: Path = DATA_DIR) -> PublicDashboardData:
    summary_path = data_dir / SUMMARY_PATH.name
    monthly_path = data_dir / MONTHLY_HISTORY_PATH.name
    model_path = data_dir / MODEL_HISTORY_PATH.name
    missing = [path.name for path in (summary_path, monthly_path, model_path) if not path.exists()]
    if missing:
        raise PublicDataSecurityError("PUBLIC_DATA_REQUIRED:" + ",".join(missing))

    summary = _read_json(summary_path)
    _validate_summary(summary)
    monthly = _validate_monthly(pd.read_csv(monthly_path))
    model = _validate_model(pd.read_csv(model_path))
    return PublicDashboardData(summary=summary, monthly_history=monthly, model_history=model)


def is_partial_month(year: int, month: int, now: datetime | None = None) -> bool:
    current = now or datetime.now()
    return int(year) == current.year and int(month) == current.month


def month_text(year: int, month: int | None) -> str:
    if not month:
        return "—"
    return f"{year}/{month:02d}"


def available_years(monthly_history: pd.DataFrame) -> list[int]:
    years = sorted(int(value) for value in monthly_history["year"].dropna().unique())
    return years or [datetime.now().year]


def active_months(monthly_history: pd.DataFrame) -> list[int]:
    active = monthly_history[monthly_history[AXIS_VALUE] > 0]["month"].astype(int).tolist()
    return active or list(range(1, 13))


def available_models(model_history: pd.DataFrame, year: int) -> list[str]:
    models = (
        model_history.loc[model_history["year"].eq(year), "model"]
        .dropna()
        .astype(str)
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    return models


def monthly_history_for_year(monthly_history: pd.DataFrame, year: int) -> pd.DataFrame:
    months = pd.DataFrame({"year": [year] * 12, "month": list(range(1, 13))})
    base = monthly_history[monthly_history["year"].eq(year)][["year", "month", AXIS_VALUE]].copy()
    result = months.merge(base, on=["year", "month"], how="left").fillna({AXIS_VALUE: 0})
    result[AXIS_VALUE] = result[AXIS_VALUE].astype(int)
    return result.sort_values("month").reset_index(drop=True)


def filter_model_history(model_history: pd.DataFrame, year: int, month: int | None, model: str = ALL) -> pd.DataFrame:
    scoped = model_history[model_history["year"].eq(year)].copy()
    if month:
        scoped = scoped[scoped["month"].eq(month)]
    if model != ALL:
        scoped = scoped[scoped["model"].astype(str).eq(model)]
    return scoped.reset_index(drop=True)


def _period_value(monthly_history: pd.DataFrame, year: int, month: int) -> int:
    matched = monthly_history[(monthly_history["year"].eq(year)) & (monthly_history["month"].eq(month))]
    if matched.empty:
        return 0
    return int(matched.iloc[0][AXIS_VALUE])


def build_kpis(data: PublicDashboardData, year: int, month: int | None, model: str = ALL) -> dict[str, Any]:
    if model != ALL:
        scoped = filter_model_history(data.model_history, year, None, model)
        monthly = (
            scoped.groupby(["year", "month"], as_index=False)[AXIS_VALUE]
            .sum()
            .merge(pd.DataFrame({"year": [year] * 12, "month": list(range(1, 13))}), how="right", on=["year", "month"])
            .fillna({AXIS_VALUE: 0})
            .sort_values("month")
        )
    else:
        monthly = monthly_history_for_year(data.monthly_history, year)

    active = monthly[monthly[AXIS_VALUE] > 0]
    ref_month = int(month or (active["month"].max() if not active.empty else 12))
    current_value = int(monthly.loc[monthly["month"].eq(ref_month), AXIS_VALUE].sum())
    previous_value = int(monthly.loc[monthly["month"].eq(ref_month - 1), AXIS_VALUE].sum()) if ref_month > 1 else 0
    ytd = int(monthly.loc[monthly["month"].le(ref_month), AXIS_VALUE].sum())
    mom = None if previous_value == 0 else round((current_value - previous_value) / previous_value, 4)

    previous_year_value = _period_value(data.monthly_history, year - 1, ref_month)
    yoy = None if previous_year_value == 0 else round((current_value - previous_year_value) / previous_year_value, 4)

    shipment_days = int(data.summary["shipment_days"]) if year == int(data.summary["report_year"]) and ref_month == int(data.summary["report_month"]) and model == ALL else 0
    avg_daily = round(current_value / shipment_days, 2) if shipment_days else 0
    if model == ALL and year == int(data.summary["report_year"]) and ref_month == int(data.summary["report_month"]):
        avg_daily = data.summary["avg_daily_shipment_axes"]
        yoy = data.summary["yoy_percent"]
        if is_partial_month(year, ref_month):
            mom = None

    return {
        "report_year": year,
        "report_month": ref_month,
        "monthly_shipment_axes": current_value,
        "ytd_shipment_axes": ytd,
        "shipment_days": shipment_days,
        "avg_daily_shipment_axes": avg_daily,
        "previous_month_axes": previous_value,
        "mom_percent": mom,
        "yoy_percent": yoy,
        "generated_at": data.summary["generated_at"],
    }


def model_month_matrix(model_history: pd.DataFrame, year: int, model: str = ALL) -> pd.DataFrame:
    scoped = filter_model_history(model_history, year, None, model)
    if scoped.empty:
        return pd.DataFrame(columns=["型號", *[f"{month}月" for month in range(1, 13)], "合計"])
    pivot = scoped.pivot_table(index="model", columns="month", values=AXIS_VALUE, aggfunc="sum", fill_value=0)
    for month in range(1, 13):
        if month not in pivot.columns:
            pivot[month] = 0
    pivot = pivot[list(range(1, 13))]
    pivot["合計"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("合計", ascending=False).reset_index()
    pivot = pivot.rename(columns={"model": "型號", **{month: f"{month}月" for month in range(1, 13)}})
    return pivot
