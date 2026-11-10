"""Ingest an AP export. Tolerant of column names, strict about values.

Every ERP names columns differently, so headers are matched by alias. Bad rows are
reported with their row number instead of crashing the run or being guessed at.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .models import APLine

ALIASES: dict[str, list[str]] = {
    "vendor": ["vendor", "vendor_name", "supplier", "payee"],
    "invoice_no": ["invoice_no", "invoice", "invoice_number", "inv_no", "document_no"],
    "invoice_date": ["invoice_date", "date", "inv_date", "posting_date"],
    "description": ["description", "item", "item_description", "memo", "line_description"],
    "amount": ["amount", "line_amount", "net_amount", "extended_amount", "subtotal"],
    "tax_charged": ["tax_charged", "sales_tax", "tax", "tax_amount", "vendor_tax"],
    "use_tax_accrued": ["use_tax_accrued", "use_tax", "accrued_use_tax", "self_assessed_tax"],
    "gl_account": ["gl_account", "gl", "account", "gl_code", "expense_account"],
    "ship_to_state": ["ship_to_state", "state", "ship_state", "location_state"],
    "local_rate": ["local_rate", "tax_rate", "combined_rate"],
}
REQUIRED = ["vendor", "invoice_no", "invoice_date", "description", "amount", "tax_charged"]
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%Y/%m/%d")


@dataclass
class IngestResult:
    lines: list[APLine] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    column_map: dict[str, str] = field(default_factory=dict)


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


def _money(v: str) -> float:
    v = (v or "").strip().replace("$", "").replace(",", "")
    if v.startswith("(") and v.endswith(")"):
        v = "-" + v[1:-1]
    return float(v) if v else 0.0


def _date(v: str) -> date:
    v = (v or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{v}'")


def _rate(v: str) -> float | None:
    v = (v or "").strip().replace("%", "")
    if not v:
        return None
    r = float(v)
    return r / 100 if r > 1 else r


def load_ap_csv(path: str | Path) -> IngestResult:
    result = IngestResult()
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = {_norm(h): h for h in (reader.fieldnames or [])}
        for canon, options in ALIASES.items():
            for opt in options:
                if opt in headers:
                    result.column_map[canon] = headers[opt]
                    break
        missing = [c for c in REQUIRED if c not in result.column_map]
        if missing:
            result.errors.append(
                f"Missing required columns: {', '.join(missing)}. "
                f"Found: {', '.join(reader.fieldnames or [])}")
            return result

        def get(rec: dict, canon: str) -> str:
            col = result.column_map.get(canon)
            return rec.get(col, "") if col else ""

        for i, rec in enumerate(reader, start=2):  # row 1 is the header
            try:
                amount = _money(get(rec, "amount"))
                line = APLine(
                    row=i,
                    vendor=get(rec, "vendor").strip(),
                    invoice_no=get(rec, "invoice_no").strip(),
                    invoice_date=_date(get(rec, "invoice_date")),
                    description=get(rec, "description").strip(),
                    amount=amount,
                    tax_charged=_money(get(rec, "tax_charged")),
                    use_tax_accrued=_money(get(rec, "use_tax_accrued")),
                    gl_account=get(rec, "gl_account").strip(),
                    ship_to_state=(get(rec, "ship_to_state").strip() or "TX").upper(),
                    local_rate=_rate(get(rec, "local_rate")),
                )
            except ValueError as e:
                result.errors.append(f"Row {i}: {e}")
                continue
            if not line.vendor or not line.invoice_no:
                result.errors.append(f"Row {i}: vendor and invoice number are required")
                continue
            if amount <= 0:
                result.errors.append(f"Row {i}: non-positive amount {amount} skipped (credit memo?)")
                continue
            result.lines.append(line)
    return result
