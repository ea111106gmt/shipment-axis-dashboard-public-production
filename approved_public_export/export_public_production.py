from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
PUBLIC_PROJECT_DIR = ROOT.parent
PROJECT_ROOT = PUBLIC_PROJECT_DIR.parent
FORMAL_DASHBOARD_DIR = PROJECT_ROOT / "shipment_axis_dashboard"
FORMAL_CONFIG_PATH = FORMAL_DASHBOARD_DIR / "config.json"
ALLOWLIST_PATH = ROOT / "public_production_allowlist.json"
EXPORT_CONFIG_PATH = ROOT / "public_production_export_config.json"
PUBLIC_DATA_DIR = PUBLIC_PROJECT_DIR / "public_data"
SUMMARY_PATH = PUBLIC_DATA_DIR / "summary.json"
MONTHLY_HISTORY_PATH = PUBLIC_DATA_DIR / "monthly_history.csv"
MODEL_HISTORY_PATH = PUBLIC_DATA_DIR / "model_monthly.csv"
APPROVAL_REFERENCE = "USER_APPROVAL_2026-09-04_PUBLIC_MODEL_AGGREGATE_NO_CUSTOMER_NO_AMOUNT"
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
DISABLED_EXPORTS = {
    "customer",
    "customer_name",
    "customer_code",
    "end_customer",
    "order",
    "order_number",
    "sales_order",
    "order_amount",
    "amount",
    "price",
    "revenue",
    "sales_amount",
    "part_number",
    "product_name",
    "daily_raw_detail",
    "raw_detail",
}


class PublicProductionExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicProductionExportResult:
    real_data_export: str
    excel_read_only: str
    source_unchanged_during_read: str
    month_total_check: str
    year_total_check: str
    model_total_check: str
    public_allowlist: str
    partial_month_rule: str
    data_period: str
    monthly_rows: int
    model_rows: int


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise PublicProductionExportError(f"{path.name} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def validate_export_config() -> None:
    config = read_json(EXPORT_CONFIG_PATH)
    if config.get("public_production_approved") is not True:
        raise PublicProductionExportError("PUBLIC_PRODUCTION_APPROVAL=FAIL")
    if config.get("allow_real_public_export") is not True:
        raise PublicProductionExportError("REAL_PUBLIC_EXPORT=BLOCKED")
    if config.get("approval_reference") != APPROVAL_REFERENCE:
        raise PublicProductionExportError("APPROVAL_REFERENCE=FAIL")


def validate_allowlist() -> dict[str, Any]:
    allowlist = read_json(ALLOWLIST_PATH)
    if allowlist.get("summary_fields") != SUMMARY_FIELDS:
        raise PublicProductionExportError("PUBLIC_ALLOWLIST=FAIL: summary fields do not match")
    if allowlist.get("monthly_history_fields") != MONTHLY_HISTORY_FIELDS:
        raise PublicProductionExportError("PUBLIC_ALLOWLIST=FAIL: monthly fields do not match")
    if allowlist.get("model_history_fields") != MODEL_HISTORY_FIELDS:
        raise PublicProductionExportError("PUBLIC_ALLOWLIST=FAIL: model fields do not match")
    if not DISABLED_EXPORTS.issubset(set(allowlist.get("disabled_exports", []))):
        raise PublicProductionExportError("PUBLIC_ALLOWLIST=FAIL: disabled exports are incomplete")
    if allowlist.get("approved_exports") != ["model"]:
        raise PublicProductionExportError("PUBLIC_ALLOWLIST=FAIL: approved exports must be model only")
    return allowlist


def _load_formal_dataset(formal_config_path: Path = FORMAL_CONFIG_PATH) -> tuple[Any, dict[str, str], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if str(FORMAL_DASHBOARD_DIR) not in sys.path:
        sys.path.insert(0, str(FORMAL_DASHBOARD_DIR))
    from data_loader import load_dashboard_data
    from dashboard_service import daily_summary, monthly_model_long, monthly_summary, validation_results

    dataset = load_dashboard_data(formal_config_path)
    validation_summary, _details = validation_results(dataset)
    monthly = monthly_summary(dataset)
    model = monthly_model_long(dataset)
    daily = daily_summary(dataset)
    return dataset, validation_summary, monthly, model, daily


def _numeric(value: Any) -> float:
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return 0.0
    return float(parsed)


def _build_monthly_history(monthly: pd.DataFrame) -> list[dict[str, int]]:
    if monthly.empty:
        raise PublicProductionExportError("No monthly summary rows are available")

    rows: list[dict[str, int]] = []
    for _, row in monthly.sort_values(["Year", "Month"]).iterrows():
        rows.append(
            {
                "year": int(row["Year"]),
                "month": int(row["Month"]),
                "shipment_axes": int(round(_numeric(row["出貨軸數"]))),
            }
        )
    return rows


def _build_model_history(model: pd.DataFrame) -> list[dict[str, Any]]:
    if model.empty:
        raise PublicProductionExportError("No model summary rows are available")

    model_rows = model[~model["is_total"]].copy()
    rows: list[dict[str, Any]] = []
    for _, row in model_rows.sort_values(["Year", "Month", "型號分類"]).iterrows():
        rows.append(
            {
                "year": int(row["Year"]),
                "month": int(row["Month"]),
                "model": str(row["型號分類"]).strip(),
                "shipment_axes": int(round(_numeric(row["出貨軸數"]))),
            }
        )
    return rows


def _model_total_check(monthly_history: list[dict[str, int]], model_history: list[dict[str, Any]]) -> str:
    model_df = pd.DataFrame(model_history)
    monthly_df = pd.DataFrame(monthly_history)
    if model_df.empty or monthly_df.empty:
        return "FAIL"
    grouped = model_df.groupby(["year", "month"], as_index=False)["shipment_axes"].sum()
    merged = monthly_df.merge(grouped, on=["year", "month"], how="left", suffixes=("_month", "_model")).fillna(0)
    diffs = (merged["shipment_axes_month"] - merged["shipment_axes_model"]).abs()
    return "PASS" if bool((diffs <= 0.0001).all()) else "WARN"


def _latest_active_month(history: list[dict[str, int]]) -> dict[str, int]:
    active = [row for row in history if row["shipment_axes"] > 0]
    if not active:
        raise PublicProductionExportError("No active monthly shipment rows are available")
    return active[-1]


def _same_period_value(history: list[dict[str, int]], year: int, month: int) -> int:
    return next((row["shipment_axes"] for row in history if row["year"] == year and row["month"] == month), 0)


def _shipment_days(daily: pd.DataFrame, year: int, month: int) -> int:
    if daily.empty or "Year" not in daily.columns or "Month" not in daily.columns or "出貨軸數" not in daily.columns:
        return 0
    scoped = daily[daily["Year"].eq(year) & daily["Month"].eq(month)].copy()
    if scoped.empty:
        return 0
    return int((pd.to_numeric(scoped["出貨軸數"], errors="coerce").fillna(0) > 0).sum())


def _is_partial_month(year: int, month: int) -> bool:
    now = datetime.now()
    return int(year) == now.year and int(month) == now.month


def _build_summary(monthly_history: list[dict[str, int]], daily: pd.DataFrame) -> dict[str, Any]:
    current = _latest_active_month(monthly_history)
    year = int(current["year"])
    month = int(current["month"])
    current_value = int(current["shipment_axes"])
    previous_value = _same_period_value(monthly_history, year, month - 1) if month > 1 else 0
    ytd = sum(row["shipment_axes"] for row in monthly_history if row["year"] == year and row["month"] <= month)
    days = _shipment_days(daily, year, month)
    avg_daily = round(current_value / days, 2) if days else 0
    previous_year_value = _same_period_value(monthly_history, year - 1, month)
    yoy = None if previous_year_value == 0 else round((current_value - previous_year_value) / previous_year_value, 4)
    mom = None if previous_value == 0 else round((current_value - previous_value) / previous_value, 4)
    if _is_partial_month(year, month):
        mom = None

    return {
        "report_year": year,
        "report_month": month,
        "monthly_shipment_axes": current_value,
        "ytd_shipment_axes": int(ytd),
        "shipment_days": days,
        "avg_daily_shipment_axes": avg_daily,
        "previous_month_axes": int(previous_value),
        "mom_percent": mom,
        "yoy_percent": yoy,
        "data_period": f"{year}/{month:02d}",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def validate_schemas(summary: dict[str, Any], monthly_history: list[dict[str, int]], model_history: list[dict[str, Any]]) -> None:
    if list(summary.keys()) != SUMMARY_FIELDS:
        raise PublicProductionExportError("PUBLIC_ALLOWLIST=FAIL: summary keys are not exact")
    for row in monthly_history:
        if list(row.keys()) != MONTHLY_HISTORY_FIELDS:
            raise PublicProductionExportError("PUBLIC_ALLOWLIST=FAIL: monthly keys are not exact")
    for row in model_history:
        if list(row.keys()) != MODEL_HISTORY_FIELDS:
            raise PublicProductionExportError("PUBLIC_ALLOWLIST=FAIL: model keys are not exact")
        if not row["model"]:
            raise PublicProductionExportError("PUBLIC_ALLOWLIST=FAIL: model is blank")
    if summary["monthly_shipment_axes"] < 0:
        raise PublicProductionExportError("monthly_shipment_axes must be >= 0")
    if summary["ytd_shipment_axes"] < summary["monthly_shipment_axes"]:
        raise PublicProductionExportError("ytd_shipment_axes must be >= monthly_shipment_axes")
    if _is_partial_month(int(summary["report_year"]), int(summary["report_month"])) and summary["mom_percent"] is not None:
        raise PublicProductionExportError("PARTIAL_MONTH_RULE=FAIL")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export_public_production(formal_config_path: Path = FORMAL_CONFIG_PATH) -> PublicProductionExportResult:
    validate_export_config()
    validate_allowlist()

    dataset, validation_summary, monthly, model, daily = _load_formal_dataset(formal_config_path)
    source_unchanged = bool(dataset.source.source_unchanged_during_read)
    month_total_check = validation_summary.get("MONTH_TOTAL_CHECK", "FAIL")
    year_total_check = validation_summary.get("YEAR_TOTAL_CHECK", "FAIL")
    if month_total_check != "PASS":
        raise PublicProductionExportError("MONTH_TOTAL_CHECK=FAIL")
    if year_total_check != "PASS":
        raise PublicProductionExportError("YEAR_TOTAL_CHECK=FAIL")
    if not source_unchanged:
        raise PublicProductionExportError("SOURCE_UNCHANGED_DURING_READ=FAIL")

    monthly_history = _build_monthly_history(monthly)
    model_history = _build_model_history(model)
    summary = _build_summary(monthly_history, daily)
    model_total_check = _model_total_check(monthly_history, model_history)
    if model_total_check != "PASS":
        raise PublicProductionExportError(f"MODEL_TOTAL_CHECK={model_total_check}")
    validate_schemas(summary, monthly_history, model_history)

    write_json(SUMMARY_PATH, summary)
    write_csv(MONTHLY_HISTORY_PATH, monthly_history, MONTHLY_HISTORY_FIELDS)
    write_csv(MODEL_HISTORY_PATH, model_history, MODEL_HISTORY_FIELDS)

    return PublicProductionExportResult(
        real_data_export="PASS",
        excel_read_only="PASS",
        source_unchanged_during_read="PASS",
        month_total_check=month_total_check,
        year_total_check=year_total_check,
        model_total_check=model_total_check,
        public_allowlist="PASS",
        partial_month_rule="PASS",
        data_period=str(summary["data_period"]),
        monthly_rows=len(monthly_history),
        model_rows=len(model_history),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--formal-config", type=Path, default=FORMAL_CONFIG_PATH)
    args = parser.parse_args()
    result = export_public_production(args.formal_config)
    print(f"REAL_DATA_EXPORT={result.real_data_export}")
    print(f"EXCEL_READ_ONLY={result.excel_read_only}")
    print(f"SOURCE_UNCHANGED_DURING_READ={result.source_unchanged_during_read}")
    print(f"MONTH_TOTAL_CHECK={result.month_total_check}")
    print(f"YEAR_TOTAL_CHECK={result.year_total_check}")
    print(f"MODEL_TOTAL_CHECK={result.model_total_check}")
    print(f"PUBLIC_ALLOWLIST={result.public_allowlist}")
    print(f"PARTIAL_MONTH_RULE={result.partial_month_rule}")
    print(f"DATA_PERIOD={result.data_period}")
    print(f"MONTH_HISTORY_ROWS={result.monthly_rows}")
    print(f"MODEL_HISTORY_ROWS={result.model_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
