from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from public_loader import (
    ALL,
    MODEL_HISTORY_FIELDS,
    MONTHLY_HISTORY_FIELDS,
    PUBLIC_TABS,
    SUMMARY_FIELDS,
    build_kpis,
    is_partial_month,
    load_public_data,
)
from security_scan_public_production import scan_repo, summarize


ALLOWLIST_PATH = ROOT / "approved_public_export" / "public_production_allowlist.json"
PUBLIC_DEMO_DIR = PROJECT_ROOT / "shipment_axis_dashboard_public_demo" / "public_deploy"
PRIVATE_DIR = PROJECT_ROOT / "shipment_axis_dashboard_private"


def read_allowlist() -> dict:
    return json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))


def test_public_model_export_allowed():
    allowlist = read_allowlist()
    assert allowlist["approved_exports"] == ["model"]
    assert allowlist["model_history_fields"] == MODEL_HISTORY_FIELDS


def test_customer_export_blocked():
    assert "customer" in read_allowlist()["disabled_exports"]


def test_order_amount_export_blocked():
    disabled = set(read_allowlist()["disabled_exports"])
    assert {"order_amount", "sales_amount", "revenue", "price"}.issubset(disabled)


def test_order_export_blocked():
    disabled = set(read_allowlist()["disabled_exports"])
    assert {"order", "order_number", "sales_order"}.issubset(disabled)


def test_part_number_export_blocked():
    assert "part_number" in read_allowlist()["disabled_exports"]


def test_public_model_schema():
    data = load_public_data()
    summary = json.loads((ROOT / "public_data" / "summary.json").read_text(encoding="utf-8"))
    assert list(summary.keys()) == SUMMARY_FIELDS
    assert list(data.monthly_history.columns) == MONTHLY_HISTORY_FIELDS
    assert list(data.model_history.columns) == MODEL_HISTORY_FIELDS


def test_partial_month_mom_suppressed():
    data = load_public_data()
    summary = data.summary
    if is_partial_month(summary["report_year"], summary["report_month"], datetime(2026, 9, 4, 12, 0)):
        assert summary["mom_percent"] is None
    sample = build_kpis(data, summary["report_year"], summary["report_month"], ALL)
    if is_partial_month(summary["report_year"], summary["report_month"], datetime.now()):
        assert sample["mom_percent"] is None


def test_public_filter_no_customer():
    app_text = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'selectbox("客戶"' not in app_text
    assert "FILTER_LABELS = [\"年度\", \"月份\", \"型號\"]" in app_text


def test_public_filter_no_part_number():
    app_text = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "品號搜尋" not in app_text
    assert "part_number" not in app_text


def test_public_tabs():
    assert PUBLIC_TABS == ["總覽", "月出貨", "型號分析"]


def test_real_values_public_data_only():
    counts = summarize(scan_repo(ROOT))
    assert counts["REAL_VALUES_OUTSIDE_PUBLIC_DATA"] == 0


def test_no_internal_metadata():
    counts = summarize(scan_repo(ROOT))
    assert counts["PUBLIC_INTERNAL_METADATA_LEAK"] == 0
    assert counts["WINDOWS_USERNAME"] == 0
    assert counts["COMPANY_IP"] == 0
    assert counts["UNC_PATH"] == 0


def test_public_demo_unchanged():
    app_text = (PUBLIC_DEMO_DIR / "app.py").read_text(encoding="utf-8")
    assert "PUBLIC DEMO" in app_text
    assert "DEMO DATA" in app_text
    assert "Synthetic Manufacturing Sample" in app_text


def test_private_app_unchanged():
    app_text = (PRIVATE_DIR / "app.py").read_text(encoding="utf-8")
    gate = json.loads((PRIVATE_DIR / "private_deployment_gate.json").read_text(encoding="utf-8"))
    assert "PRIVATE DASHBOARD" in app_text
    assert "APPROVED SUMMARY" in app_text
    assert gate["sharing_mode"] == "SPECIFIC_USERS_ONLY"
