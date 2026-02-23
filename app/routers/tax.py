import os
import json
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from sqlalchemy.orm import Session
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..database import get_db
from ..models import TaxDocument
from ..auth import get_current_user
from ..ocr_processor import TaxOCR

router = APIRouter(prefix="/tax", tags=["tax"])

templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
jinja_env = Environment(
    loader=FileSystemLoader(templates_dir),
    autoescape=select_autoescape(["html", "xml"]),
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "tax_docs")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Constants ──────────────────────────────────────────────────────────────────

FORM_TYPES = [
    ("W2",                 "W-2"),
    ("1099_INT",           "1099-INT"),
    ("1098_T",             "1098-T"),
    ("1098",               "1098"),
    ("3922",               "3922"),
    ("1099_CONSOLIDATED",  "1099 Consolidated"),
    ("1099_R",             "1099-R"),
    ("SSA_1099",           "SSA-1099"),
    ("1099_SA",            "1099-SA (HSA)"),
]

FORM_TYPE_DISPLAY = {k: v for k, v in FORM_TYPES}

# Keys extracted from each form type (must match ed_<key> input names in template)
FORM_FIELD_KEYS = {
    "W2": [
        "employer_ein", "wages", "federal_withheld",
        "ss_wages", "ss_withheld", "medicare_wages", "medicare_withheld",
        "state", "state_wages", "state_withheld",
    ],
    "1099_INT": [
        "interest_income", "early_withdrawal_penalty",
        "us_bond_interest", "federal_withheld",
    ],
    "1098_T": [
        "student_name", "tuition_paid", "scholarships", "adjustments",
    ],
    "1098": [
        "mortgage_interest", "outstanding_principal",
        "mortgage_insurance", "points", "property_address",
    ],
    "3922": [
        "company_name", "grant_date", "exercise_date",
        "fmv_on_grant_date", "fmv_on_exercise_date",
        "exercise_price", "shares_transferred",
    ],
    "1099_CONSOLIDATED": [
        "account_last4", "ordinary_dividends", "qualified_dividends",
        "total_cap_gain_dist", "interest_income",
        "gross_proceeds", "cost_basis", "net_gain_loss", "federal_withheld",
    ],
    "1099_R": [
        "payer_name", "gross_distribution", "taxable_amount",
        "federal_withheld", "state", "state_withheld", "distribution_code",
    ],
    "SSA_1099": [
        "gross_benefits", "repaid_benefits", "net_benefits",
        "medicare_deducted", "voluntary_federal_withheld",
    ],
    "1099_SA": [
        "total_distributions", "earnings_on_excess", "distribution_code",
        "fair_market_value",
    ],
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _key_figure(form_type: str, data: dict) -> tuple:
    """Return (label, value_str) for the primary display figure of a document."""
    def _fmt(k, decimals=2):
        try:
            v = float(data.get(k) or 0)
            return f"${v:,.{decimals}f}"
        except (ValueError, TypeError):
            return "—"

    if form_type == "W2":
        return "Wages", _fmt("wages")
    elif form_type == "1099_INT":
        return "Interest", _fmt("interest_income")
    elif form_type == "1098_T":
        return "Tuition Paid", _fmt("tuition_paid")
    elif form_type == "1098":
        return "Mortgage Interest", _fmt("mortgage_interest")
    elif form_type == "3922":
        try:
            qty = float(data.get("shares_transferred") or 0)
            return "Shares", f"{qty:,.4f}"
        except (ValueError, TypeError):
            return "Shares", "—"
    elif form_type == "1099_CONSOLIDATED":
        return "Net Gain/Loss", _fmt("net_gain_loss")
    elif form_type == "1099_R":
        return "Gross Distribution", _fmt("gross_distribution")
    elif form_type == "SSA_1099":
        return "Net Benefits", _fmt("net_benefits")
    elif form_type == "1099_SA":
        return "HSA Distributions", _fmt("total_distributions")
    return "", ""


def _compute_summary(docs: list) -> dict:
    """Aggregate key tax figures across all documents for a year."""
    s = dict(
        total_wages=0.0, total_federal_withheld=0.0, total_state_withheld=0.0,
        total_ss_withheld=0.0, total_medicare_withheld=0.0,
        total_interest=0.0, total_dividends=0.0, total_qualified_div=0.0,
        net_cap_gain=0.0, tuition_paid=0.0, mortgage_interest=0.0,
        total_retirement_dist=0.0, total_ss_benefits=0.0, espp_compensation=0.0,
    )

    def _f(d, k):
        try:
            return float(d.get(k) or 0)
        except (ValueError, TypeError):
            return 0.0

    for doc in docs:
        try:
            d = json.loads(doc.extracted_data) if doc.extracted_data else {}
        except Exception:
            d = {}

        ft = doc.form_type
        if ft == "W2":
            s["total_wages"]            += _f(d, "wages")
            s["total_federal_withheld"] += _f(d, "federal_withheld")
            s["total_state_withheld"]   += _f(d, "state_withheld")
            s["total_ss_withheld"]      += _f(d, "ss_withheld")
            s["total_medicare_withheld"]+= _f(d, "medicare_withheld")
        elif ft == "1099_INT":
            s["total_interest"]         += _f(d, "interest_income")
            s["total_federal_withheld"] += _f(d, "federal_withheld")
        elif ft == "1098_T":
            s["tuition_paid"]           += _f(d, "tuition_paid")
        elif ft == "1098":
            s["mortgage_interest"]      += _f(d, "mortgage_interest")
        elif ft == "1099_CONSOLIDATED":
            s["total_dividends"]        += _f(d, "ordinary_dividends")
            s["total_qualified_div"]    += _f(d, "qualified_dividends")
            s["net_cap_gain"]           += _f(d, "net_gain_loss")
            s["total_interest"]         += _f(d, "interest_income")
            s["total_federal_withheld"] += _f(d, "federal_withheld")
        elif ft == "1099_R":
            s["total_retirement_dist"]  += _f(d, "gross_distribution")
            s["total_federal_withheld"] += _f(d, "federal_withheld")
            s["total_state_withheld"]   += _f(d, "state_withheld")
        elif ft == "SSA_1099":
            s["total_ss_benefits"]      += _f(d, "net_benefits")
            s["total_federal_withheld"] += _f(d, "voluntary_federal_withheld")
        elif ft == "1099_SA":
            pass  # HSA distributions tracked for reference; tax-free if qualified
        elif ft == "3922":
            fmv_ex = _f(d, "fmv_on_exercise_date")
            ex_px  = _f(d, "exercise_price")
            shares = _f(d, "shares_transferred")
            if shares and fmv_ex > ex_px:
                s["espp_compensation"] += (fmv_ex - ex_px) * shares

    return s


def _render(template_name: str, **ctx) -> HTMLResponse:
    t = jinja_env.get_template(template_name)
    return HTMLResponse(t.render(**ctx))


async def _save_upload(file: UploadFile, user_id: int) -> tuple:
    """Save uploaded file; return (file_name, original_name, content_type)."""
    ext = os.path.splitext(file.filename)[1]
    file_name = f"{uuid.uuid4().hex}{ext}"
    user_dir = os.path.join(UPLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    dest = os.path.join(user_dir, file_name)
    with open(dest, "wb") as fout:
        fout.write(await file.read())
    return file_name, file.filename, file.content_type


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def tax_dashboard(
    request: Request,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    all_docs = db.query(TaxDocument).filter(TaxDocument.user_id == user.id).all()
    available_years = sorted({d.tax_year for d in all_docs}, reverse=True)

    current_year = datetime.now().year
    default_year = available_years[0] if available_years else current_year - 1
    if year is None:
        year = default_year

    # Year selector: last 5 years + any years that already have docs
    year_options = sorted(
        set(available_years) | set(range(max(2020, current_year - 4), current_year + 1)),
        reverse=True,
    )

    docs_for_year = [d for d in all_docs if d.tax_year == year]

    docs_with_data = []
    for doc in sorted(docs_for_year, key=lambda d: d.form_type):
        try:
            ed = json.loads(doc.extracted_data) if doc.extracted_data else {}
        except Exception:
            ed = {}
        kf_label, kf_value = _key_figure(doc.form_type, ed)
        docs_with_data.append({
            "doc": doc,
            "ed": ed,
            "kf_label": kf_label,
            "kf_value": kf_value,
        })

    summary = _compute_summary(docs_for_year)

    # Serialize docs for JS edit modal
    docs_json = json.dumps([
        {
            "id": item["doc"].id,
            "tax_year": item["doc"].tax_year,
            "form_type": item["doc"].form_type,
            "issuer": item["doc"].issuer or "",
            "description": item["doc"].description or "",
            "status": item["doc"].status or "uploaded",
            "notes": item["doc"].notes or "",
            "ed": item["ed"],
            "has_file": bool(item["doc"].file_name),
            "original_name": item["doc"].original_name or "",
            "content_type": item["doc"].content_type or "",
        }
        for item in docs_with_data
    ])

    dup_id = request.query_params.get("dup")
    return _render(
        "tax.html",
        request=request,
        user=user,
        docs=docs_with_data,
        summary=summary,
        year=year,
        year_options=year_options,
        available_years=available_years,
        form_types=FORM_TYPES,
        form_type_display=FORM_TYPE_DISPLAY,
        docs_json=docs_json,
        dup_id=dup_id,
    )


@router.post("/add")
async def add_tax_document(
    request: Request,
    tax_year: int = Form(...),
    form_type: str = Form(...),
    issuer: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    status: str = Form("uploaded"),
    notes: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    form_data = await request.form()
    extracted = {
        k: str(form_data[f"ed_{k}"]).strip()
        for k in FORM_FIELD_KEYS.get(form_type, [])
        if f"ed_{k}" in form_data and str(form_data[f"ed_{k}"]).strip()
    }

    # Duplicate guard: same year + form type + issuer
    existing = db.query(TaxDocument).filter(
        TaxDocument.user_id == user.id,
        TaxDocument.tax_year == tax_year,
        TaxDocument.form_type == form_type,
        TaxDocument.issuer == (issuer or None),
    ).first()
    if existing:
        return RedirectResponse(url=f"/tax?year={tax_year}&dup={existing.id}", status_code=303)

    file_name = original_name = content_type = None
    if file and file.filename:
        file_name, original_name, content_type = await _save_upload(file, user.id)

    doc = TaxDocument(
        user_id=user.id,
        tax_year=tax_year,
        form_type=form_type,
        issuer=issuer or None,
        description=description or None,
        status=status,
        notes=notes or None,
        extracted_data=json.dumps(extracted) if extracted else None,
        file_name=file_name,
        original_name=original_name,
        content_type=content_type,
    )
    db.add(doc)
    db.commit()
    return RedirectResponse(url=f"/tax?year={tax_year}", status_code=303)


@router.post("/seed_year")
async def seed_year(
    from_year: int = Form(...),
    to_year: int = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Copy prior-year doc roster as 'expected' placeholders for a new tax year."""
    already = db.query(TaxDocument).filter(
        TaxDocument.user_id == user.id,
        TaxDocument.tax_year == to_year,
    ).count()
    if not already:
        prior = db.query(TaxDocument).filter(
            TaxDocument.user_id == user.id,
            TaxDocument.tax_year == from_year,
        ).all()
        for p in prior:
            db.add(TaxDocument(
                user_id=user.id,
                tax_year=to_year,
                form_type=p.form_type,
                issuer=p.issuer,
                description=p.description,
                status="expected",
            ))
        db.commit()
    return RedirectResponse(url=f"/tax?year={to_year}", status_code=303)


@router.post("/{doc_id}/edit")
async def edit_tax_document(
    doc_id: int,
    request: Request,
    tax_year: int = Form(...),
    form_type: str = Form(...),
    issuer: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    status: str = Form("uploaded"),
    notes: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = db.query(TaxDocument).filter(
        TaxDocument.id == doc_id, TaxDocument.user_id == user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    form_data = await request.form()
    extracted = {
        k: str(form_data[f"ed_{k}"]).strip()
        for k in FORM_FIELD_KEYS.get(form_type, [])
        if f"ed_{k}" in form_data and str(form_data[f"ed_{k}"]).strip()
    }

    if file and file.filename:
        # Remove old file
        if doc.file_name:
            old_path = os.path.join(UPLOAD_DIR, str(user.id), doc.file_name)
            if os.path.exists(old_path):
                os.remove(old_path)
        doc.file_name, doc.original_name, doc.content_type = await _save_upload(file, user.id)

    doc.tax_year = tax_year
    doc.form_type = form_type
    doc.issuer = issuer or None
    doc.description = description or None
    doc.status = status
    doc.notes = notes or None
    doc.extracted_data = json.dumps(extracted) if extracted else None
    doc.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/tax?year={tax_year}", status_code=303)


@router.get("/{doc_id}/file")
async def download_tax_file(
    doc_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = db.query(TaxDocument).filter(
        TaxDocument.id == doc_id, TaxDocument.user_id == user.id
    ).first()
    if not doc or not doc.file_name:
        raise HTTPException(status_code=404, detail="File not found")
    path = os.path.join(UPLOAD_DIR, str(user.id), doc.file_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(
        path,
        filename=doc.original_name or doc.file_name,
        media_type=doc.content_type or "application/octet-stream",
    )


@router.get("/{doc_id}/preview")
async def preview_tax_file(
    doc_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Serve file inline for in-browser preview (PDF viewer / image)."""
    doc = db.query(TaxDocument).filter(
        TaxDocument.id == doc_id, TaxDocument.user_id == user.id
    ).first()
    if not doc or not doc.file_name:
        raise HTTPException(status_code=404, detail="File not found")
    path = os.path.join(UPLOAD_DIR, str(user.id), doc.file_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    fname = doc.original_name or doc.file_name
    return FileResponse(
        path,
        media_type=doc.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@router.post("/{doc_id}/scan")
async def scan_tax_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Run OCR on the stored file and return extracted field values as JSON."""
    doc = db.query(TaxDocument).filter(
        TaxDocument.id == doc_id, TaxDocument.user_id == user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_name:
        raise HTTPException(status_code=400, detail="No file uploaded for this document")

    path = os.path.join(UPLOAD_DIR, str(user.id), doc.file_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    form_type = doc.form_type

    # OCR is CPU/IO-bound and synchronous — run in a thread so the event loop
    # is not blocked, with a 60-second timeout for large/multi-page PDFs.
    def _run_ocr():
        return TaxOCR().scan(path, form_type)

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(pool, _run_ocr),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            return JSONResponse({"_error": "OCR timed out after 60 s. Try a smaller or clearer file."})

    return JSONResponse(result)


@router.post("/{doc_id}/delete")
async def delete_tax_document(
    doc_id: int,
    tax_year: int = Form(0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = db.query(TaxDocument).filter(
        TaxDocument.id == doc_id, TaxDocument.user_id == user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    year = doc.tax_year or tax_year
    if doc.file_name:
        path = os.path.join(UPLOAD_DIR, str(user.id), doc.file_name)
        if os.path.exists(path):
            os.remove(path)
    db.delete(doc)
    db.commit()
    return RedirectResponse(url=f"/tax?year={year}", status_code=303)


@router.post("/{doc_id}/status")
async def update_status(
    doc_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = db.query(TaxDocument).filter(
        TaxDocument.id == doc_id, TaxDocument.user_id == user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.status = status
    doc.updated_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"ok": True, "status": status})
