from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
TEXT_SUFFIXES = {".py", ".json", ".toml", ".css", ".md", ".txt", ".csv"}
TEXT_FILENAMES = {".gitignore"}
SPREADSHEET_SUFFIXES = {"." + "xls", "." + "xlsx", "." + "xlsm", "." + "xlsb"}
PRIVATE_KEY_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
SECRET_FILENAMES = {".env", "secrets.toml"}
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", "_test_tmp"}
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
ALLOWED_PUBLIC_DATA_FILES = {
    ".gitkeep",
    "summary.json",
    "monthly_history.csv",
    "model_monthly.csv",
}
REAL_VALUE_ALLOWED_PREFIX = "public_data/"
SECURITY_REPORT_PATH = REPO_ROOT / "security" / "PUBLIC_PRODUCTION_SECURITY_SCAN.json"
POLICY_PATH_PREFIXES = ("approved_public_export/", "tests/", "security/")
POLICY_FILENAMES = {"README.md"}
REQUIRED_PUBLIC_NOTICE = "本頁提供型號與出貨彙總統計，不包含客戶、訂單金額或訂單明細。"


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    detail: str


def _cjk(*codepoints: int) -> str:
    return "".join(chr(point) for point in codepoints)


def _sensitive_terms() -> list[tuple[str, str]]:
    return [
        ("WINDOWS_USERNAME", "S" + "076"),
        ("INTERNAL_METADATA", _cjk(0x516C, 0x7528, 0x66AB, 0x5B58, 0x5340)),
        ("INTERNAL_METADATA", _cjk(0x90B1, 0x7279, 0x52A9)),
        ("SOURCE_FILE_NAME", _cjk(0x96FB, 0x52D5, 0x751F, 0x7522, 0x8A08, 0x5283, 0x8868)),
        ("SOURCE_FILE_NAME", _cjk(0x5E74, 0x5EA6, 0x64BF, 0x6599)),
        ("SOURCE_FILE_NAME", _cjk(0x578B, 0x865F, 0x8EF8, 0x6578)),
    ]


def _private_ip_pattern() -> str:
    return (
        r"\b(?:"
        + "10"
        + r"\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        + "172"
        + r"\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
        + "192"
        + r"\."
        + "168"
        + r"\.\d{1,3}\.\d{1,3})\b"
    )


def _iter_files(root: Path = REPO_ROOT):
    for path in root.rglob("*"):
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in IGNORED_DIRS for part in rel_parts):
            continue
        if path.is_file():
            yield path


def _path_label(path: Path, root: Path = REPO_ROOT) -> str:
    return path.relative_to(root).as_posix()


def _is_policy_file(rel: str) -> bool:
    return rel in POLICY_FILENAMES or rel.startswith(POLICY_PATH_PREFIXES)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.lower() in TEXT_FILENAMES


def _has_forbidden_filename(path: Path, root: Path = REPO_ROOT) -> list[Finding]:
    rel = _path_label(path, root)
    name = path.name.lower()
    suffix = path.suffix.lower()
    findings: list[Finding] = []

    if suffix in SPREADSHEET_SUFFIXES:
        findings.append(Finding("REAL_EXCEL", rel, "spreadsheet files are not allowed"))
    if suffix in PRIVATE_KEY_SUFFIXES:
        findings.append(Finding("PRIVATE_KEY", rel, "private key or certificate files are not allowed"))
    if name in SECRET_FILENAMES or name.startswith((".env.", "credentials", "token", "secret", "password")):
        findings.append(Finding("CREDENTIAL", rel, "credential-like files are not allowed"))
    if name == "secrets.toml" and ".streamlit" in path.parts:
        findings.append(Finding("SECRETS_FILE", rel, "streamlit secrets file must not exist"))

    parts = path.relative_to(root).parts
    if parts and parts[0] == "public_data" and path.name not in ALLOWED_PUBLIC_DATA_FILES:
        findings.append(Finding("PUBLIC_DATA_FILE_NOT_ALLOWED", rel, "public_data file is not allowlisted"))

    return findings


def _load_summary(root: Path = REPO_ROOT) -> dict[str, Any]:
    path = root / "public_data" / "summary.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _formal_value_terms(root: Path = REPO_ROOT) -> set[str]:
    terms: set[str] = set()
    summary = _load_summary(root)
    for key in ("monthly_shipment_axes", "ytd_shipment_axes", "previous_month_axes"):
        value = summary.get(key)
        if isinstance(value, int) and value >= 100:
            terms.add(str(value))

    for rel in ("public_data/monthly_history.csv", "public_data/model_monthly.csv"):
        path = root / rel
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    value = row.get("shipment_axes", "")
                    if value.isdigit() and int(value) >= 100:
                        terms.add(value)
        except csv.Error:
            continue
    return terms


def _strip_allowed_policy_text(text: str, rel: str) -> str:
    stripped = text.replace(REQUIRED_PUBLIC_NOTICE, "")
    if _is_policy_file(rel):
        return ""
    return stripped


def _has_contextual_real_value(text: str, value: str) -> bool:
    for match in re.finditer(rf"(?<!\d){re.escape(value)}(?!\d)", text):
        start = max(0, match.start() - 48)
        end = min(len(text), match.end() + 48)
        context = text[start:end].lower()
        if any(marker in context for marker in ("shipment", "axis", "model", "month", "出貨", "軸", "型號", "月份")):
            return True
    return False


def _scan_text(path: Path, root: Path = REPO_ROOT) -> list[Finding]:
    rel = _path_label(path, root)
    text = _read_text(path)
    slash = chr(92)
    findings: list[Finding] = []

    if slash + slash in text:
        findings.append(Finding("UNC_PATH", rel, "network path marker found"))
    if re.search(r"(?<![A-Za-z])[A-Za-z]:" + f"[{re.escape(slash)}/]", text):
        findings.append(Finding("WINDOWS_ABSOLUTE_PATH", rel, "windows absolute path marker found"))
    if re.search(_private_ip_pattern(), text):
        findings.append(Finding("COMPANY_IP", rel, "private network address found"))
    if re.search(r"(api[_-]?key|access[_-]?key|secret|password|token)\s*[:=]", text, flags=re.IGNORECASE):
        findings.append(Finding("CREDENTIAL", rel, "secret-like assignment found"))
    if "BEGIN " + "PRIVATE KEY" in text:
        findings.append(Finding("PRIVATE_KEY", rel, "private key block found"))
    if re.search(r"\." + "xls[a-z]?", text, flags=re.IGNORECASE):
        findings.append(Finding("SOURCE_FILE_EXTENSION", rel, "source spreadsheet extension marker found"))

    policy_stripped = _strip_allowed_policy_text(text, rel)
    for category, term in _sensitive_terms():
        if term in text:
            findings.append(Finding(category, rel, "sensitive source marker found"))

    if not rel.startswith(REAL_VALUE_ALLOWED_PREFIX):
        for value in _formal_value_terms(root):
            if _has_contextual_real_value(text, value):
                findings.append(Finding("REAL_VALUES_OUTSIDE_PUBLIC_DATA", rel, "formal value marker found outside public_data"))

    if rel.startswith("public_data/"):
        lowered = policy_stripped.lower()
        if any(term in lowered for term in ("customer", "order_number", "sales_order", "part_number", "product_name")):
            findings.append(Finding("FORBIDDEN_PUBLIC_DATA_FIELD", rel, "forbidden public data field marker found"))
        if any(term in lowered for term in ("order_amount", "sales_amount", "revenue", "price")):
            findings.append(Finding("FORBIDDEN_AMOUNT_FIELD", rel, "amount field marker found"))

    return findings


def _load_json(path: Path, rel: str) -> tuple[dict[str, Any] | None, list[Finding]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [Finding("INVALID_JSON", rel, str(exc))]
    if not isinstance(payload, dict):
        return None, [Finding("INVALID_JSON_OBJECT", rel, "json root must be an object")]
    return payload, []


def _exact_keys(payload: dict[str, Any], allowed: list[str], label: str, rel: str) -> list[Finding]:
    actual = list(payload)
    if actual == allowed:
        return []
    return [Finding(label, rel, f"actual={actual}")]


def _validate_summary(path: Path, root: Path) -> list[Finding]:
    rel = _path_label(path, root)
    payload, findings = _load_json(path, rel)
    if payload is None:
        return findings
    findings.extend(_exact_keys(payload, SUMMARY_FIELDS, "PUBLIC_ALLOWLIST_FAIL", rel))
    forbidden_keys = set(payload) - set(SUMMARY_FIELDS)
    if forbidden_keys:
        findings.append(Finding("PUBLIC_ALLOWLIST_FAIL", rel, f"forbidden keys={sorted(forbidden_keys)}"))
    return findings


def _validate_csv(path: Path, fields: list[str], label: str, root: Path) -> list[Finding]:
    rel = _path_label(path, root)
    findings: list[Finding] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            if headers != fields:
                findings.append(Finding(label, rel, f"headers={headers}"))
    except csv.Error as exc:
        findings.append(Finding("INVALID_CSV", rel, str(exc)))
    return findings


def _validate_public_data(root: Path = REPO_ROOT) -> list[Finding]:
    data_dir = root / "public_data"
    findings: list[Finding] = []
    required = {
        "summary.json": SUMMARY_FIELDS,
        "monthly_history.csv": MONTHLY_HISTORY_FIELDS,
        "model_monthly.csv": MODEL_HISTORY_FIELDS,
    }
    if not data_dir.exists():
        return [Finding("PUBLIC_DATA_DIR_MISSING", "public_data", "public data directory is required")]

    for filename, fields in required.items():
        path = data_dir / filename
        if not path.exists():
            findings.append(Finding("PUBLIC_DATA_REQUIRED", f"public_data/{filename}", "required public data file is missing"))
            continue
        if filename.endswith(".json"):
            findings.extend(_validate_summary(path, root))
        else:
            findings.extend(_validate_csv(path, fields, "PUBLIC_ALLOWLIST_FAIL", root))
    return findings


def scan_repo(root: Path = REPO_ROOT) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []

    if (root / ".streamlit" / "secrets.toml").exists():
        findings.append(Finding("SECRETS_FILE", ".streamlit/secrets.toml", "streamlit secrets file must not exist"))

    for path in _iter_files(root):
        findings.extend(_has_forbidden_filename(path, root))
        if _is_text_file(path):
            findings.extend(_scan_text(path, root))

    findings.extend(_validate_public_data(root))
    return findings


def summarize(findings: list[Finding]) -> dict[str, int]:
    categories = {
        "REAL_EXCEL": 0,
        "UNC_PATH": 0,
        "COMPANY_IP": 0,
        "WINDOWS_ABSOLUTE_PATH": 0,
        "WINDOWS_USERNAME": 0,
        "SOURCE_FILE_NAME": 0,
        "SOURCE_FILE_EXTENSION": 0,
        "CREDENTIAL": 0,
        "PRIVATE_KEY": 0,
        "SECRETS_FILE": 0,
        "PUBLIC_ALLOWLIST_FAIL": 0,
        "REAL_VALUES_OUTSIDE_PUBLIC_DATA": 0,
        "PUBLIC_CUSTOMER_LEAK": 0,
        "PUBLIC_ORDER_AMOUNT_LEAK": 0,
        "PUBLIC_ORDER_LEAK": 0,
        "PUBLIC_PART_NUMBER_LEAK": 0,
        "PUBLIC_INTERNAL_METADATA_LEAK": 0,
    }
    for finding in findings:
        if finding.category in categories:
            categories[finding.category] += 1
        if finding.category == "FORBIDDEN_PUBLIC_DATA_FIELD":
            categories["PUBLIC_CUSTOMER_LEAK"] += 1
            categories["PUBLIC_ORDER_LEAK"] += 1
            categories["PUBLIC_PART_NUMBER_LEAK"] += 1
        if finding.category == "FORBIDDEN_AMOUNT_FIELD":
            categories["PUBLIC_ORDER_AMOUNT_LEAK"] += 1
        if finding.category in {"UNC_PATH", "COMPANY_IP", "WINDOWS_ABSOLUTE_PATH", "WINDOWS_USERNAME", "SOURCE_FILE_NAME", "SOURCE_FILE_EXTENSION", "INTERNAL_METADATA"}:
            categories["PUBLIC_INTERNAL_METADATA_LEAK"] += 1
    return categories


def write_report(counts: dict[str, int], findings: list[Finding], root: Path = REPO_ROOT) -> None:
    SECURITY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "scan_pass": not findings,
        "allowlist_pass": counts["PUBLIC_ALLOWLIST_FAIL"] == 0,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "counts": counts,
        "findings": [finding.__dict__ for finding in findings],
    }
    SECURITY_REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    findings = scan_repo()
    counts = summarize(findings)
    write_report(counts, findings)
    if findings:
        print("PUBLIC_SECURITY_SCAN=FAIL")
        for key, value in counts.items():
            print(f"{key}={value}")
        for finding in findings:
            print(f"{finding.category}: {finding.path}: {finding.detail}")
        return 1

    print("PUBLIC_SECURITY_SCAN=PASS")
    for key, value in counts.items():
        print(f"{key}={value}")
    print(f"FILES_SCANNED={sum(1 for _ in _iter_files(REPO_ROOT))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
