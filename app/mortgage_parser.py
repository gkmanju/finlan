"""
Parse RoundPoint (and generic) mortgage PDF statements.
Extracts: principal balance, interest rate, payment due date,
payment breakdown (P/I/escrow), escrow balance, YTD interest/taxes.
"""
import re
from datetime import date
from typing import Optional, Dict, Any

# Try pdfplumber first (more accurate), fall back to pypdf
try:
    import pdfplumber
    _USE_PDFPLUMBER = True
except ImportError:
    _USE_PDFPLUMBER = False

try:
    from pypdf import PdfReader
    _USE_PYPDF = True
except ImportError:
    _USE_PYPDF = False


def extract_pdf_text(file_path: str) -> str:
    """Extract all text from a PDF file."""
    text = ""
    if _USE_PDFPLUMBER:
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text += t + "\n"
            if text.strip():
                return text
        except Exception:
            pass

    if _USE_PYPDF:
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        except Exception:
            pass

    return text


def _parse_amount(s: str) -> Optional[float]:
    """Convert '$1,234.56' or '1234.56' to float."""
    if not s:
        return None
    s = re.sub(r'[,$]', '', s.strip())
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(s: str) -> Optional[date]:
    """Parse MM/DD/YYYY or Month DD, YYYY."""
    if not s:
        return None
    s = s.strip()
    # Try MM/DD/YYYY
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    # Try Month DD, YYYY
    try:
        from dateutil import parser as dp
        return dp.parse(s).date()
    except Exception:
        pass
    return None


def _find(pattern: str, text: str, group: int = 1, flags: int = re.IGNORECASE) -> Optional[str]:
    """Return first match group or None."""
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else None


def parse_roundpoint_statement(text: str) -> Dict[str, Any]:
    """
    Parse a RoundPoint mortgage statement text.
    Returns a dict with all found fields (None if not found).
    """
    data: Dict[str, Any] = {
        "statement_date": None,
        "due_date": None,
        "unpaid_principal": None,
        "interest_rate": None,
        "payment_amount": None,
        "principal_portion": None,
        "interest_portion": None,
        "escrow_portion": None,
        "escrow_balance": None,
        "ytd_interest": None,
        "ytd_taxes": None,
        "loan_number": None,
        "property_address": None,
    }

    # ── Loan number ────────────────────────────────────────────────────────────
    ln = _find(r'loan\s+(?:number|#|no\.?)\s*[:\-]?\s*(\d[\d\-]+)', text)
    if ln:
        data["loan_number"] = ln

    # ── Statement / cycle date ─────────────────────────────────────────────────
    sd = _find(r'statement\s+date\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    if not sd:
        sd = _find(r'cycle\s+date\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    if sd:
        data["statement_date"] = _parse_date(sd)

    # ── Payment due date ───────────────────────────────────────────────────────
    dd = _find(r'(?:payment\s+)?due\s+date\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    if not dd:
        dd = _find(r'amount\s+due\s+by\s+(\d{1,2}/\d{1,2}/\d{4})', text)
    if dd:
        data["due_date"] = _parse_date(dd)

    # ── Unpaid principal balance ───────────────────────────────────────────────
    pb = _find(r'unpaid\s+principal\s+balance\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if not pb:
        pb = _find(r'principal\s+balance\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if not pb:
        pb = _find(r'outstanding\s+principal\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if pb:
        data["unpaid_principal"] = _parse_amount(pb)

    # ── Interest rate ──────────────────────────────────────────────────────────
    ir = _find(r'interest\s+rate\s*[:\-]?\s*([\d.]+)\s*%', text)
    if ir:
        data["interest_rate"] = float(ir)

    # ── Total amount due / payment amount ─────────────────────────────────────
    ta = _find(r'total\s+amount\s+due\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if not ta:
        ta = _find(r'amount\s+due\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if not ta:
        ta = _find(r'regular\s+monthly\s+payment\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if ta:
        data["payment_amount"] = _parse_amount(ta)

    # ── Payment breakdown ──────────────────────────────────────────────────────
    # Often appears as a table: Principal | Interest | Escrow
    pp = _find(r'principal\s*[:\-]?\s*\$?([\d,]+\.\d{2})\s', text)
    if pp:
        data["principal_portion"] = _parse_amount(pp)

    ip = _find(r'interest\s*[:\-]?\s*\$?([\d,]+\.\d{2})\s', text)
    if ip:
        data["interest_portion"] = _parse_amount(ip)

    ep = _find(r'escrow\s*[:\-]?\s*\$?([\d,]+\.\d{2})\s', text)
    if ep:
        data["escrow_portion"] = _parse_amount(ep)

    # ── Escrow balance ─────────────────────────────────────────────────────────
    eb = _find(r'escrow\s+balance\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if eb:
        data["escrow_balance"] = _parse_amount(eb)

    # ── YTD interest paid ──────────────────────────────────────────────────────
    yi = _find(r'year[\s\-]to[\s\-]date\s+interest(?:\s+paid)?\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if not yi:
        yi = _find(r'ytd\s+interest\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if yi:
        data["ytd_interest"] = _parse_amount(yi)

    # ── YTD taxes paid ─────────────────────────────────────────────────────────
    yt = _find(r'year[\s\-]to[\s\-]date\s+(?:real\s+estate\s+)?tax(?:es)?\s+paid\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if not yt:
        yt = _find(r'ytd\s+tax(?:es)?\s*[:\-]?\s*\$?([\d,]+\.\d{2})', text)
    if yt:
        data["ytd_taxes"] = _parse_amount(yt)

    return data


def parse_mortgage_pdf(file_path: str) -> Dict[str, Any]:
    """Extract text from PDF and parse mortgage statement fields."""
    text = extract_pdf_text(file_path)
    result = parse_roundpoint_statement(text)
    result["raw_text"] = text
    return result
