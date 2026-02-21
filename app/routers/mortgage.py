import os
import shutil
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..database import get_db
from ..models import MortgageAccount, MortgageStatement
from ..auth import get_current_user
from ..mortgage_parser import parse_mortgage_pdf

router = APIRouter(prefix="/mortgage", tags=["mortgage"])

templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
jinja_env = Environment(
    loader=FileSystemLoader(templates_dir),
    autoescape=select_autoescape(["html", "xml"]),
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "mortgage")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _render(template_name: str, **ctx) -> HTMLResponse:
    t = jinja_env.get_template(template_name)
    return HTMLResponse(t.render(**ctx))


# ── Dashboard ──────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def mortgage_dashboard(request: Request, db: Session = Depends(get_db),
                              user=Depends(get_current_user)):
    mortgages = db.query(MortgageAccount).filter(
        MortgageAccount.user_id == user.id
    ).all()
    return _render("mortgage.html", user=user, mortgages=mortgages, request=request)


# ── Create / Update mortgage account ──────────────────────────────────────────

@router.post("/account")
async def save_mortgage_account(
    mortgage_id: Optional[int] = Form(None),
    servicer_name: str = Form(...),
    loan_number: Optional[str] = Form(None),
    property_address: Optional[str] = Form(None),
    original_balance: Optional[float] = Form(None),
    interest_rate: Optional[float] = Form(None),
    loan_term_months: Optional[int] = Form(None),
    origination_date: Optional[str] = Form(None),
    maturity_date: Optional[str] = Form(None),
    monthly_payment: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    def _d(s): return date.fromisoformat(s) if s else None

    if mortgage_id:
        m = db.query(MortgageAccount).filter(
            MortgageAccount.id == mortgage_id,
            MortgageAccount.user_id == user.id
        ).first()
        if not m:
            raise HTTPException(status_code=404, detail="Not found")
    else:
        m = MortgageAccount(user_id=user.id)
        db.add(m)

    m.servicer_name = servicer_name
    m.loan_number = loan_number or None
    m.property_address = property_address or None
    m.original_balance = original_balance
    m.interest_rate = interest_rate
    m.loan_term_months = loan_term_months
    m.origination_date = _d(origination_date)
    m.maturity_date = _d(maturity_date)
    m.monthly_payment = monthly_payment
    db.commit()
    return RedirectResponse(url="/mortgage", status_code=303)


@router.post("/account/{mortgage_id}/delete")
async def delete_mortgage_account(
    mortgage_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    m = db.query(MortgageAccount).filter(
        MortgageAccount.id == mortgage_id,
        MortgageAccount.user_id == user.id
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(m)
    db.commit()
    return RedirectResponse(url="/mortgage", status_code=303)


# ── Upload PDF statement ───────────────────────────────────────────────────────

@router.post("/account/{mortgage_id}/upload")
async def upload_statement(
    mortgage_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    m = db.query(MortgageAccount).filter(
        MortgageAccount.id == mortgage_id,
        MortgageAccount.user_id == user.id
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mortgage account not found")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save temporarily
    tmp_path = os.path.join(UPLOAD_DIR, f"tmp_{mortgage_id}_{file.filename}")
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        parsed = parse_mortgage_pdf(tmp_path)
    finally:
        os.remove(tmp_path)

    stmt = MortgageStatement(
        mortgage_id=mortgage_id,
        statement_date=parsed.get("statement_date"),
        due_date=parsed.get("due_date"),
        unpaid_principal=parsed.get("unpaid_principal"),
        interest_rate=parsed.get("interest_rate"),
        payment_amount=parsed.get("payment_amount"),
        principal_portion=parsed.get("principal_portion"),
        interest_portion=parsed.get("interest_portion"),
        escrow_portion=parsed.get("escrow_portion"),
        escrow_balance=parsed.get("escrow_balance"),
        ytd_interest=parsed.get("ytd_interest"),
        ytd_taxes=parsed.get("ytd_taxes"),
        raw_text=parsed.get("raw_text", "")[:10000],  # cap text size
    )

    # Update loan number on parent account if parsed and missing
    if parsed.get("loan_number") and not m.loan_number:
        m.loan_number = parsed["loan_number"]

    db.add(stmt)
    db.commit()
    return RedirectResponse(url="/mortgage", status_code=303)


# ── Delete a statement ─────────────────────────────────────────────────────────

@router.post("/statement/{stmt_id}/delete")
async def delete_statement(
    stmt_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = db.query(MortgageStatement).join(MortgageAccount).filter(
        MortgageStatement.id == stmt_id,
        MortgageAccount.user_id == user.id
    ).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")
    db.delete(stmt)
    db.commit()
    return RedirectResponse(url="/mortgage", status_code=303)


# ── API: mortgage dashboard summary ──────────────────────────────────────────

@router.get("/summary")
async def mortgage_summary(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return all mortgage accounts with their latest statement data for the dashboard."""
    mortgages = db.query(MortgageAccount).filter(
        MortgageAccount.user_id == user.id
    ).all()
    result = []
    for m in mortgages:
        latest = m.statements[0] if m.statements else None
        result.append({
            "id": m.id,
            "servicer_name": m.servicer_name,
            "loan_number": m.loan_number,
            "property_address": m.property_address,
            "interest_rate": float(m.interest_rate) if m.interest_rate else None,
            "monthly_payment": float(m.monthly_payment) if m.monthly_payment else None,
            "original_balance": float(m.original_balance) if m.original_balance else None,
            "current_balance": float(latest.unpaid_principal) if latest and latest.unpaid_principal else (
                float(m.original_balance) if m.original_balance else None
            ),
            "due_date": str(latest.due_date) if latest and latest.due_date else None,
            "payment_amount": float(latest.payment_amount) if latest and latest.payment_amount else (
                float(m.monthly_payment) if m.monthly_payment else None
            ),
            "principal_portion": float(latest.principal_portion) if latest and latest.principal_portion else None,
            "interest_portion": float(latest.interest_portion) if latest and latest.interest_portion else None,
            "escrow_portion": float(latest.escrow_portion) if latest and latest.escrow_portion else None,
            "escrow_balance": float(latest.escrow_balance) if latest and latest.escrow_balance else None,
            "ytd_interest": float(latest.ytd_interest) if latest and latest.ytd_interest else None,
            "statement_date": str(latest.statement_date) if latest and latest.statement_date else None,
            "statement_count": len(m.statements),
        })
    return result


# ── API: parsed statement preview (JSON) ──────────────────────────────────────

@router.post("/account/{mortgage_id}/parse-preview")
async def parse_preview(
    mortgage_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Parse PDF and return extracted fields as JSON without saving."""
    m = db.query(MortgageAccount).filter(
        MortgageAccount.id == mortgage_id,
        MortgageAccount.user_id == user.id
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Not found")

    tmp_path = os.path.join(UPLOAD_DIR, f"preview_{mortgage_id}_{file.filename}")
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        parsed = parse_mortgage_pdf(tmp_path)
    finally:
        os.remove(tmp_path)

    parsed.pop("raw_text", None)
    # Convert dates to strings for JSON
    for k, v in parsed.items():
        if hasattr(v, "isoformat"):
            parsed[k] = v.isoformat()
    return parsed
