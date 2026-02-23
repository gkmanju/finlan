"""
Business income router — Wave CSV importer + Schedule C summary.
Supports Wave's standard transaction CSV export format.
"""
import csv
import json
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from io import StringIO
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import extract
from sqlalchemy.orm import Session
import os

from ..database import get_db
from ..auth import get_current_user
from ..models import BusinessTransaction

router = APIRouter(prefix="/business", tags=["business"])

templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
jinja_env = Environment(
    loader=FileSystemLoader(templates_dir),
    autoescape=select_autoescape(["html", "xml"]),
)

# ── Schedule C line mapping ────────────────────────────────────────────────────
# Maps lowercase Wave category keywords → (line_number, display_label)
# Meals are 50% deductible — flagged in UI.
SCHEDULE_C_MAP = [
    (["advertising", "marketing", "promotion", "ads"],              ("8",   "Advertising")),
    (["mileage", "car", "truck", "auto", "vehicle", "gas", "fuel"], ("9",   "Car & Truck Expenses")),
    (["commission", "referral fee"],                                 ("10",  "Commissions & Fees")),
    (["contract", "freelance", "subcontract", "1099"],               ("11",  "Contract Labor")),
    (["depreciation", "amortization"],                               ("13",  "Depreciation")),
    (["insurance"],                                                  ("15",  "Insurance")),
    (["interest - mortgage", "mortgage interest"],                   ("16a", "Mortgage Interest")),
    (["interest"],                                                   ("16b", "Interest - Other")),
    (["legal", "accounting", "attorney", "cpa", "bookkeeping"],      ("17",  "Legal & Professional Services")),
    (["office supply", "office expense", "software", "saas",
      "subscript", "app", "cloud", "hosting"],                       ("18",  "Office Expense")),
    (["rent", "lease"],                                              ("20b", "Rent/Lease – Other")),
    (["repair", "maintenance"],                                      ("21",  "Repairs & Maintenance")),
    (["supplies"],                                                   ("22",  "Supplies")),
    (["tax", "license", "permit", "registration"],                   ("23",  "Taxes & Licenses")),
    (["travel", "hotel", "flight", "airfare", "lodging"],            ("24a", "Travel")),
    (["meal", "dining", "food", "restaurant", "entertainment"],      ("24b", "Meals (50%)")),
    (["utility", "electric", "internet", "phone", "water"],         ("25",  "Utilities")),
    (["wage", "salary", "payroll"],                                  ("26",  "Wages")),
    (["home office"],                                                ("30",  "Home Office")),
]

INCOME_KEYWORDS = ["income", "revenue", "sales", "invoice", "payment received",
                   "service", "consulting", "fee income", "client"]


def _map_category(wave_cat: str, is_credit: bool) -> tuple[bool, str, str]:
    """
    Returns (is_income, schedule_c_line, schedule_c_label).
    Wave exports: Credits = income (money in), Debits = expense (money out).
    """
    cat_lower = (wave_cat or "").lower()

    # Explicit income check
    if is_credit or any(k in cat_lower for k in INCOME_KEYWORDS):
        return True, "1", "Gross Receipts / Sales"

    # Match expense to Schedule C line
    for keywords, (line, label) in SCHEDULE_C_MAP:
        if any(k in cat_lower for k in keywords):
            return False, line, label

    # Default: other expenses (Part V)
    return False, "48", "Other Expenses"


def _detect_wave_format(content: str) -> str:
    """
    Returns 'pl' for Profit & Loss report, 'txn' for transaction export.
    Wave P&L reports start with 'Profit' or have 'Total Income' / 'Net Income' rows.
    """
    head = content[:800].lower()
    if "profit" in head or "net income" in head or "total income" in head:
        return "pl"
    return "txn"


def _parse_wave_pl_csv(content: str, tax_year: int) -> list[dict]:
    """
    Parse Wave Profit & Loss report CSV export.

    Actual Wave P&L CSV structure:
        Profit and Loss,,
        E-AUTOMATION,,
        Date Range: 2025-01-01 to 2025-12-31,,
        Report Type: Accrual (Paid & Unpaid),,
        ,,
        ,ACCOUNTS,Jan 01 2025 to Dec 31 2025
        ,Income,$25555.99
        ,Cost of Goods Sold,$7608.96
        ,Gross Profit,$17947.03        <- skip (calculated)
        ,Operating Expenses,$7714.22
        ,Net Profit,$10232.81          <- skip (calculated)

    Column layout: col[0]=indent(blank), col[1]=account name, col[2]=amount.
    Calculated summary rows (Gross Profit, Net Profit, Net Loss) are skipped.
    """
    lines = content.splitlines()
    rows = []

    # Rows that are calculated summaries — never import these
    SKIP_NAMES = {
        "gross profit", "net profit", "net loss", "net income",
        "total income", "total expenses", "total cost of goods sold",
        "total operating expenses", "accounts", "",
    }
    # Names that are always income
    INCOME_NAMES = {"income", "revenue", "sales", "other income"}
    # Names that are always COGS (expense)
    COGS_NAMES = {"cost of goods sold", "cost of sales", "cogs",
                  "cost of goods", "direct costs"}

    for raw_line in lines:
        line = raw_line.strip().strip("\ufeff")
        if not line:
            continue

        try:
            cols = next(csv.reader([line]))
        except StopIteration:
            continue

        cols = [c.strip().strip('"').strip() for c in cols]

        # Need at least 2 non-empty cols — skip title/header/blank rows
        non_empty = [c for c in cols if c]
        if len(non_empty) < 2:
            continue

        # Wave layout: first col blank, account in col[1], amount in col[2]
        # But also handle layout where account is col[0] and amount is col[1]
        if cols[0] == "" and len(cols) >= 3:
            account_name = cols[1]
            amount_str   = cols[2]
        elif cols[0] == "" and len(cols) == 2:
            account_name = cols[1]
            amount_str   = ""
        else:
            account_name = cols[0]
            amount_str   = cols[-1] if len(cols) > 1 else ""

        name_lower = account_name.lower().strip()

        # Skip title rows (no dollar amount) and calculated summaries
        if name_lower in SKIP_NAMES:
            continue
        if name_lower.startswith("date range") or name_lower.startswith("report type"):
            continue
        if name_lower.startswith("profit and loss"):
            continue

        # Parse amount
        amount_str = amount_str.replace("$", "").replace(",", "") \
                               .replace("(", "-").replace(")", "").strip()
        if not amount_str:
            continue
        try:
            amount = Decimal(amount_str)
        except Exception:
            continue

        if amount == 0:
            continue

        # Determine income vs expense
        if name_lower in INCOME_NAMES or "income" in name_lower and "net" not in name_lower:
            is_income_row = True
        elif name_lower in COGS_NAMES or "operating expense" in name_lower:
            is_income_row = False
        else:
            # Fall back: positive = income, negative = expense
            is_income_row = amount > 0

        _, sc_line, sc_label = _map_category(account_name, is_income_row)
        if is_income_row:
            sc_line, sc_label = "1", "Gross Receipts / Sales"
            amount = abs(amount)
        elif name_lower in COGS_NAMES:
            sc_line, sc_label = "4", "Cost of Goods Sold"
            amount = -abs(amount)
        else:
            amount = -abs(amount)

        rows.append({
            "transaction_date": date(tax_year, 1, 1),
            "description":      account_name,
            "amount":           amount,
            "account_name":     "Wave P&L",
            "wave_category":    account_name,
            "schedule_c_line":  sc_line,
            "schedule_c_label": sc_label,
            "is_income":        is_income_row,
            "notes":            f"Imported from Wave P&L report ({tax_year})",
        })
    return rows


def _parse_wave_csv(content: str, tax_year: int) -> list[dict]:
    """
    Parse Wave transaction CSV export.
    Wave column names vary by export version — handle all known variants.
    """
    reader = csv.DictReader(StringIO(content))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]

    # Normalise column lookup
    def _col(row: dict, *candidates) -> str:
        for c in candidates:
            for k, v in row.items():
                if k.strip().lower() == c.lower():
                    return (v or "").strip()
        return ""

    rows = []
    for raw in reader:
        # Date
        date_str = _col(raw, "date", "transaction date", "transaction_date")
        try:
            txn_date = date.fromisoformat(date_str)
        except ValueError:
            # Try MM/DD/YYYY
            try:
                from datetime import datetime as dt
                txn_date = dt.strptime(date_str, "%m/%d/%Y").date()
            except Exception:
                continue

        if txn_date.year != tax_year:
            continue

        description = _col(raw, "description", "memo", "name")
        account_name = _col(raw, "account name", "account", "account_name")
        wave_cat = _col(raw, "category", "category name", "category_name")
        notes = _col(raw, "notes", "note", "memo")

        # Amount resolution — Wave may give separate debit/credit cols or a signed total
        debit_str = _col(raw, "debit amount", "debit", "amount (debit)")
        credit_str = _col(raw, "credit amount", "credit", "amount (credit)")
        total_str = _col(raw, "total", "amount", "total amount", "net amount")

        def _to_dec(s: str) -> Decimal:
            s = s.replace("$", "").replace(",", "").strip()
            if not s:
                return Decimal("0")
            return Decimal(s)

        if debit_str or credit_str:
            debit = _to_dec(debit_str)
            credit = _to_dec(credit_str)
            is_credit = credit > 0
            amount = credit if is_credit else -debit
        else:
            amount = _to_dec(total_str)
            is_credit = amount >= 0

        if amount == 0:
            continue

        is_income, sc_line, sc_label = _map_category(wave_cat, is_credit)

        rows.append({
            "transaction_date": txn_date,
            "description":      description or "(no description)",
            "amount":           amount,
            "account_name":     account_name,
            "wave_category":    wave_cat,
            "schedule_c_line":  sc_line,
            "schedule_c_label": sc_label,
            "is_income":        is_income,
            "notes":            notes or None,
        })
    return rows


def _schedule_c_summary(rows: list[BusinessTransaction]) -> dict:
    """Aggregate transactions into Schedule C line totals."""
    income = Decimal("0")
    expenses: dict[str, dict] = {}     # line → {label, amount}

    for r in rows:
        amt = abs(Decimal(str(r.amount)))
        if r.is_income:
            income += amt
        else:
            key = r.schedule_c_line or "48"
            if key not in expenses:
                expenses[key] = {"label": r.schedule_c_label or "Other Expenses", "amount": Decimal("0")}
            expenses[key]["amount"] += amt

    total_expenses = sum(v["amount"] for v in expenses.values())
    net_profit = income - total_expenses

    # Sort by line number (treat letters as decimal: 16a < 16b < 17)
    def _sort_key(k):
        import re
        m = re.match(r"(\d+)([a-z]?)", k)
        return (int(m.group(1)), m.group(2)) if m else (999, "")

    sorted_expenses = {k: expenses[k] for k in sorted(expenses.keys(), key=_sort_key)}

    # Meals are only 50% deductible
    if "24b" in sorted_expenses:
        sorted_expenses["24b"]["deductible"] = sorted_expenses["24b"]["amount"] / 2
    for k in sorted_expenses:
        if "deductible" not in sorted_expenses[k]:
            sorted_expenses[k]["deductible"] = sorted_expenses[k]["amount"]

    deductible_expenses = sum(v["deductible"] for v in sorted_expenses.values())
    net_profit_after_meals = income - deductible_expenses
    se_tax = max(net_profit_after_meals, Decimal("0")) * Decimal("0.9235") * Decimal("0.153")

    return {
        "gross_income":         income,
        "total_expenses":       total_expenses,
        "deductible_expenses":  deductible_expenses,
        "net_profit":           net_profit_after_meals,
        "se_tax":               se_tax,
        "expense_lines":        sorted_expenses,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def business_page(
    request: Request,
    year: int = 2025,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows = (
        db.query(BusinessTransaction)
        .filter(BusinessTransaction.user_id == user.id,
                BusinessTransaction.tax_year == year)
        .order_by(BusinessTransaction.transaction_date.desc())
        .all()
    )

    summary = _schedule_c_summary(rows) if rows else None

    # Available years
    from sqlalchemy import func
    years = [
        r[0] for r in
        db.query(BusinessTransaction.tax_year)
        .filter(BusinessTransaction.user_id == user.id)
        .distinct()
        .order_by(BusinessTransaction.tax_year.desc())
        .all()
    ]
    if year not in years:
        years = [year] + years

    template = jinja_env.get_template("business.html")
    return HTMLResponse(template.render(
        request=request,
        username=user.username,
        rows=rows,
        summary=summary,
        year=year,
        years=years,
    ))


@router.post("/import-wave")
async def import_wave(
    request: Request,
    year: int = Form(...),
    replace: bool = Form(False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = (await file.read()).decode("utf-8-sig", errors="ignore")  # handle BOM

    fmt = _detect_wave_format(content)
    if fmt == "pl":
        parsed = _parse_wave_pl_csv(content, year)
    else:
        parsed = _parse_wave_csv(content, year)

    if not parsed:
        raise HTTPException(status_code=422,
                            detail=f"No {year} data found in this CSV (detected format: {fmt}). "
                                   "For P&L: set the report period to Jan 1–Dec 31 and export. "
                                   "For Transactions: filter to the same date range.")

    batch_id = str(uuid.uuid4())

    if replace:
        db.query(BusinessTransaction).filter(
            BusinessTransaction.user_id == user.id,
            BusinessTransaction.tax_year == year,
        ).delete()

    for p in parsed:
        db.add(BusinessTransaction(
            user_id=user.id,
            tax_year=year,
            import_batch=batch_id,
            **p,
        ))

    db.commit()
    return RedirectResponse(url=f"/business?year={year}", status_code=303)


@router.post("/{txn_id}/reclassify")
async def reclassify(
    txn_id: int,
    schedule_c_line: str = Form(...),
    schedule_c_label: str = Form(...),
    is_income: bool = Form(False),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    txn = db.query(BusinessTransaction).filter(
        BusinessTransaction.id == txn_id,
        BusinessTransaction.user_id == user.id,
    ).first()
    if not txn:
        raise HTTPException(404)
    txn.schedule_c_line = schedule_c_line
    txn.schedule_c_label = schedule_c_label
    txn.is_income = is_income
    db.commit()
    return JSONResponse({"ok": True})


@router.delete("/{txn_id}")
async def delete_txn(
    txn_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    txn = db.query(BusinessTransaction).filter(
        BusinessTransaction.id == txn_id,
        BusinessTransaction.user_id == user.id,
    ).first()
    if not txn:
        raise HTTPException(404)
    db.delete(txn)
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/schedule-c-json")
async def schedule_c_json(
    year: int = 2025,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Returns Schedule C summary as JSON — used by the tax summary page."""
    rows = db.query(BusinessTransaction).filter(
        BusinessTransaction.user_id == user.id,
        BusinessTransaction.tax_year == year,
    ).all()
    summary = _schedule_c_summary(rows)
    return JSONResponse({
        k: float(v) if isinstance(v, Decimal) else
           {ek: {ik: float(iv) if isinstance(iv, Decimal) else iv
                 for ik, iv in ev.items()}
            for ek, ev in v.items()} if isinstance(v, dict) else v
        for k, v in summary.items()
    })
