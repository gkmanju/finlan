import re
import os
from datetime import datetime
from typing import Optional, Dict
from PIL import Image
import pytesseract
from pdf2image import convert_from_path
from dateutil import parser as date_parser


class ReceiptOCR:
    """Extract structured data from receipt images/PDFs using OCR"""
    
    def __init__(self):
        # Common HSA providers and categories for matching
        self.providers_keywords = [
            'medical', 'dental', 'vision', 'pharmacy', 'hospital', 'clinic',
            'cvs', 'walgreens', 'rite aid', 'urgent care', 'doctor', 'dr.',
            'optometry', 'orthodontics', 'pediatrics', 'urgent care'
        ]
        
        self.categories = {
            'dental': ['dental', 'dentist', 'orthodont', 'teeth', 'braces'],
            'vision': ['vision', 'eye', 'optometry', 'glasses', 'contacts', 'ophthalmology'],
            'pharmacy': ['pharmacy', 'cvs', 'walgreens', 'rite aid', 'prescription', 'rx'],
            'medical': ['medical', 'hospital', 'clinic', 'doctor', 'dr.', 'urgent care', 'emergency']
        }
    
    def extract_text(self, file_path: str) -> str:
        """Extract text from image or PDF"""
        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if ext == '.pdf':
                # Convert PDF to images and extract text
                images = convert_from_path(file_path, dpi=300)
                text = ""
                for img in images:
                    text += pytesseract.image_to_string(img) + "\n"
            else:
                # Direct image OCR
                img = Image.open(file_path)
                text = pytesseract.image_to_string(img)
            
            return text
        except Exception as e:
            print(f"OCR extraction error: {e}")
            return ""
    
    def extract_dates(self, text: str) -> Dict[str, Optional[str]]:
        """Extract dates from text"""
        dates = {
            'service_date': None,
            'paid_date': None,
        }
        
        # Common date patterns
        date_patterns = [
            r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',  # MM/DD/YYYY or MM-DD-YYYY
            r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',    # YYYY-MM-DD
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}',  # Month DD, YYYY
        ]
        
        found_dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    parsed_date = date_parser.parse(match, fuzzy=True)
                    found_dates.append(parsed_date.strftime('%Y-%m-%d'))
                except:
                    pass
        
        # Assign first found date as service date, second as paid date
        if found_dates:
            dates['service_date'] = found_dates[0]
            if len(found_dates) > 1:
                dates['paid_date'] = found_dates[1]
        
        return dates
    
    def extract_amounts(self, text: str) -> Dict[str, Optional[float]]:
        """Extract monetary amounts from text"""
        amounts = {
            'amount': None,
        }
        
        # Look for dollar amounts
        amount_patterns = [
            r'\$\s*(\d+[,\d]*\.?\d{0,2})',  # $100.00 or $1,000.00
            r'(?:total|amount|due|paid)[\s:]*\$?\s*(\d+[,\d]*\.?\d{2})',  # Total: $100.00
        ]
        
        found_amounts = []
        for pattern in amount_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    # Remove commas and convert to float
                    clean_amount = match.replace(',', '')
                    amount_val = float(clean_amount)
                    if amount_val > 0 and amount_val < 100000:  # Sanity check
                        found_amounts.append(amount_val)
                except:
                    pass
        
        # Take the largest amount found (usually the total)
        if found_amounts:
            amounts['amount'] = max(found_amounts)
        
        return amounts
    
    def extract_provider(self, text: str) -> Optional[str]:
        """Extract provider/vendor name from text"""
        lines = text.split('\n')
        
        # Usually the provider is in the first few lines
        for line in lines[:5]:
            line = line.strip()
            # Look for lines with provider keywords
            if any(keyword in line.lower() for keyword in self.providers_keywords):
                if len(line) > 3 and len(line) < 100:
                    return line
            # Or just return first substantial line
            elif len(line) > 5 and len(line) < 100 and not line.startswith('*'):
                return line
        
        return None
    
    def extract_category(self, text: str) -> Optional[str]:
        """Determine category based on keywords"""
        text_lower = text.lower()
        
        for category, keywords in self.categories.items():
            if any(keyword in text_lower for keyword in keywords):
                return category.capitalize()
        
        return None
    
    def process_receipt(self, file_path: str) -> Dict[str, any]:
        """Process receipt and extract all relevant data"""
        text = self.extract_text(file_path)
        
        if not text:
            return {'error': 'Could not extract text from receipt'}
        
        result = {
            'raw_text': text[:500],  # First 500 chars for debugging
            'provider': self.extract_provider(text),
            'category': self.extract_category(text),
        }
        
        # Extract dates
        dates = self.extract_dates(text)
        result.update(dates)
        
        # Extract amounts
        amounts = self.extract_amounts(text)
        result.update(amounts)
        
        # Auto-populate tax year from service date
        if result.get('service_date'):
            try:
                result['tax_year'] = int(result['service_date'][:4])
            except:
                pass
        
        return result

# ── Tax Document OCR ──────────────────────────────────────────────────────────

class TaxOCR:
    """
    Extract structured key figures from tax forms (W-2, 1099-*, 1098-*, 3922,
    SSA-1099).

    Strategy:
      1. Try pypdf digital text extraction first (fast, accurate for e-filed PDFs).
      2. Fall back to Tesseract OCR for scanned/image PDFs.
      3. For W-2: strip the duplicate copy-B/copy-2 side-by-side columns before
         parsing so regex patterns don't pick up the wrong copy.
    """

    def __init__(self):
        self._receipt_ocr = ReceiptOCR()

    # ── Public entry point ────────────────────────────────────────────────────

    def scan(self, file_path: str, form_type: str) -> dict:
        text = self._extract(file_path)
        if not text or not text.strip():
            return {"_error": "Could not extract text from file"}

        extractor = {
            "W2":                self._parse_w2,
            "1099_INT":          self._parse_1099_int,
            "1098_T":            self._parse_1098_t,
            "1098":              self._parse_1098,
            "3922":              self._parse_3922,
            "1099_CONSOLIDATED": self._parse_1099_consolidated,
            "1099_R":            self._parse_1099_r,
            "SSA_1099":          self._parse_ssa_1099,
        }.get(form_type)

        if extractor is None:
            return {"_error": f"No OCR parser for form type '{form_type}'"}

        try:
            result = extractor(text)
            result["_raw_preview"] = text[:800]
            return result
        except Exception as exc:
            return {"_error": str(exc), "_raw_preview": text[:800]}

    # ── Text extraction ───────────────────────────────────────────────────────

    def _extract(self, file_path: str) -> str:
        """
        Try pypdf digital text first; fall back to Tesseract if text is sparse.
        pypdf gives clean, line-ordered text for digitally-created tax PDFs.
        """
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            digital = self._pdf_digital_text(file_path)
            if len(digital.strip()) > 120:
                return digital
        return self._receipt_ocr.extract_text(file_path)

    @staticmethod
    def _pdf_digital_text(file_path: str) -> str:
        try:
            import pypdf
            parts = []
            reader = pypdf.PdfReader(file_path)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
            return "\n".join(parts)
        except Exception:
            return ""

    # ── Core helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _clean_w2(text: str) -> str:
        """
        W-2 PDFs contain multiple copies (B, C, 2, etc.) whose text gets
        concatenated by pypdf / OCR.  Truncate at the second occurrence of the
        SSN so only the first copy is parsed.
        """
        ssn_m = re.search(r'\d{3}-\d{2}-\d{4}', text)
        if ssn_m:
            second = text.find(ssn_m.group(), ssn_m.end())
            if second > 0:
                return text[:second]
        # Tesseract: cut at "Copy 2" / "Copy C" header
        for marker in [r"Copy\s+2\s*[—\-–]", r"Copy\s+C\s*[—\-–]"]:
            m = re.search(marker, text, re.IGNORECASE)
            if m:
                return text[:m.start()]
        return text

    @staticmethod
    def _amt(text: str, *labels, allow_negative: bool = False) -> str:
        """
        Find the first dollar-style amount (≥ 3 digits before decimal) that
        appears within ~200 chars of any of the given label strings.
        Searches across newlines so it works when values appear on the next line.
        Requires at least 3 digits to avoid matching bare box numbers (1, 2, …).
        """
        label_re = "|".join(re.escape(l) for l in labels)
        # lazy multiline span, then a money amount (3+ digits, optional commas, optional cents)
        pattern = rf"(?:{label_re})[\s\S]{{0,200}}?([-]?\$?\s*\d{{1,3}}(?:,\d{{3}})+\.?\d{{0,2}}|\d{{3,}}\.?\d{{0,2}})"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = re.sub(r"[\$,\s]", "", m.group(1))
            try:
                val = float(raw)
                if not allow_negative:
                    val = abs(val)
                return f"{val:.2f}"
            except ValueError:
                pass
        return ""

    @staticmethod
    def _find(text: str, pattern: str, group: int = 1, flags: int = re.IGNORECASE) -> str:
        m = re.search(pattern, text, flags)
        return m.group(group).strip() if m else ""

    @staticmethod
    def _date(text: str, *labels) -> str:
        label_re = "|".join(re.escape(l) for l in labels)
        pattern = rf"(?:{label_re})[\s\S]{{0,80}}?(\d{{1,2}}[/\-]\d{{1,2}}[/\-]\d{{2,4}}|\d{{4}}[/\-]\d{{1,2}}[/\-]\d{{1,2}})"
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return ""
        raw = m.group(1)
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
        return raw

    # ── Per-form parsers ──────────────────────────────────────────────────────

    def _parse_w2(self, text: str) -> dict:
        """
        Positional W-2 parser — works for both pypdf (label-free) and Tesseract
        (label-present) output.

        pypdf W-2 structure (after dedup):
          SSN  wages  fed_withheld
          EIN
          ss_wages  ss_withheld
          medicare_wages  medicare_withheld
          employer name / address ...
          STATE  stateID  state_wages  state_withheld

        We locate each row by its anchor (SSN / EIN / state code) then read
        the decimal amounts on that line in order.
        """
        text = self._clean_w2(text)

        def _amts_on_line(line: str) -> list:
            """Return all decimal amounts on a line (handles both 327968.97 and 327,968.97)."""
            return [m.replace(",", "") for m in re.findall(r'\b\d[\d,]*\.\d{2}\b', line)]

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        result = {k: "" for k in [
            "issuer", "employer_ein", "wages", "federal_withheld",
            "ss_wages", "ss_withheld", "medicare_wages", "medicare_withheld",
            "state", "state_wages", "state_withheld",
        ]}

        for i, line in enumerate(lines):
            # ── Row anchored on SSN ──────────────────────────────────────────
            if re.match(r'\d{3}-\d{2}-\d{4}', line):
                vals = _amts_on_line(line)
                if len(vals) >= 2:
                    result["wages"]           = vals[0]
                    result["federal_withheld"]= vals[1]

                # next few lines: look for EIN
                for j in range(i + 1, min(i + 5, len(lines))):
                    ein_m = re.search(r'(\d{2}-\d{7})', lines[j])
                    if ein_m:
                        result["employer_ein"] = ein_m.group(1)
                        # after EIN: first line with ≥2 amounts → SS
                        for k2 in range(j + 1, min(j + 4, len(lines))):
                            ss_vals = _amts_on_line(lines[k2])
                            if len(ss_vals) >= 2:
                                result["ss_wages"]   = ss_vals[0]
                                result["ss_withheld"]= ss_vals[1]
                                # next line with ≥2 amounts → Medicare
                                for m2 in range(k2 + 1, min(k2 + 4, len(lines))):
                                    med_vals = _amts_on_line(lines[m2])
                                    if len(med_vals) >= 2:
                                        result["medicare_wages"]   = med_vals[0]
                                        result["medicare_withheld"]= med_vals[1]
                                        break
                                break
                        break
                break   # found first SSN — stop outer loop

        # ── State line (pypdf): "CA  196-0988-2  336518.97  24452.56" ───────────
        state_m = re.search(
            r'^([A-Z]{2})\s+[\w\-]+\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})',
            text, re.MULTILINE,
        )
        if state_m:
            result["state"]          = state_m.group(1)
            result["state_wages"]    = state_m.group(2).replace(",", "")
            result["state_withheld"] = state_m.group(3).replace(",", "")
        else:
            # fallback: state from address (with or without comma before state code)
            addr_m = re.search(r'[,\s]\s*([A-Z]{2})\s+\d{5}', text)
            if addr_m:
                result["state"] = addr_m.group(1)

        # ── Employer name: first non-numeric line after EIN (pypdf path only) ─
        # Guard: wages are set by the SSN positional parser only on the pypdf path.
        # On the Tesseract path wages are still empty here, so skip this block.
        if result["wages"]:
            ein_idx = next((i for i, l in enumerate(lines) if re.match(r'\d{2}-\d{7}', l)), -1)
            if ein_idx >= 0:
                for emp_line in lines[ein_idx + 3:]:  # skip SS and Medicare rows
                    if re.search(r'\d+\.\d{2}', emp_line):
                        continue  # skip lines with amounts
                    if re.match(r'\d', emp_line):
                        continue  # skip lines starting with digits
                    if len(emp_line) > 3:
                        result["issuer"] = emp_line
                        break

        # ── Employer name (Tesseract path): look for label ───────────────────
        if not result["issuer"]:
            emp_m = re.search(r"Employer'?s\s+name[,\s].*?\n(.{3,80})", text, re.IGNORECASE)
            if emp_m:
                name = emp_m.group(1).strip()
                if not re.match(r'^\d', name) and len(name) > 3:
                    result["issuer"] = name

        # ── EIN fallback via label (Tesseract path) ──────────────────────────
        if not result["employer_ein"]:
            ein_m = re.search(
                r'(?:EIN|Employer.{0,25}(?:FED\s+ID|ID|number))[\s\S]{0,80}?(\d{2}\s*[\-~–—]\s*\d{7})',
                text, re.IGNORECASE)
            if ein_m:
                result["employer_ein"] = re.sub(r'[\s~–—]+', '-', ein_m.group(1)).strip('-')

        # ── Label-based fallback for wages/withheld (Tesseract path) ─────────
        if not result["wages"]:
            # Normalize OCR glitch "4458 .40" → "4458.40" before any matching
            tn = re.sub(r'(\d)\s+\.(\d)', r'\1.\2', text)

            def _last_pair(label1: str, label2: str):
                """Find the LAST occurrence where label1 and label2 appear on
                the same line (or close together), followed by a line with 2+
                amounts. Returns (val1, val2) or None."""
                hits = list(re.finditer(
                    rf'(?:{re.escape(label1)})[\s\S]{{0,150}}?(?:{re.escape(label2)}).*?\n(.+)',
                    tn, re.IGNORECASE))
                for m in reversed(hits):
                    vals = [v.replace(',', '') for v in re.findall(r'\b\d[\d,]*\.\d{2}\b', m.group(1))
                        if not re.match(r'^\d\.\d{2}$', v.replace(',', ''))]
                    if len(vals) >= 2:
                        return vals[0], vals[1]
                return None

            p = _last_pair("wages, tips, other comp", "federal income tax withheld")
            if p:
                result["wages"], result["federal_withheld"] = p
            else:
                result["wages"]            = self._amt(tn, "wages, tips, other comp")
                result["federal_withheld"] = self._amt(tn, "federal income tax withheld")

            p = _last_pair("social security wages", "social security tax withheld")
            if p:
                result["ss_wages"], result["ss_withheld"] = p
            else:
                result["ss_wages"]   = self._amt(tn, "social security wages")
                result["ss_withheld"]= self._amt(tn, "social security tax withheld")

            p = _last_pair("medicare wages", "medicare tax withheld")
            if p:
                result["medicare_wages"], result["medicare_withheld"] = p
            else:
                result["medicare_wages"]   = self._amt(tn, "medicare wages")
                result["medicare_withheld"]= self._amt(tn, "medicare tax withheld")

            # State for Tesseract path (different layout from pypdf)
            if not result["state_wages"]:
                sw_m = re.search(r'(?:16\s+)?state\s+wages[^\n]*\n[\w\-\s]{0,30}?([\d,]+\.\d{2})', tn, re.IGNORECASE)
                if sw_m:
                    result["state_wages"] = sw_m.group(1).replace(',', '')
            if not result["state_withheld"]:
                st_m = re.search(r'(?:17\s+)?state\s+income\s+tax[^\n]*\n\n?([\d,]+\.\d{2})', tn, re.IGNORECASE)
                if st_m:
                    result["state_withheld"] = st_m.group(1).replace(',', '')

        return result

    def _parse_1099_int(self, text: str) -> dict:
        a = self._amt
        payer = ""
        for line in text.splitlines():
            line = line.strip()
            if len(line) > 4 and not line.startswith("Form") and not re.match(r'^\d', line):
                payer = line
                break
        return {
            "issuer":                    payer,
            "interest_income":           a(text, "interest income", "1 interest income", "box 1"),
            "early_withdrawal_penalty":  a(text, "early withdrawal penalty", "2 early withdrawal"),
            "us_bond_interest":          a(text, "u.s. savings bond", "us bond interest", "3 interest"),
            "federal_withheld":          a(text, "federal income tax withheld", "4 federal"),
        }

    def _parse_1098_t(self, text: str) -> dict:
        a, f = self._amt, self._find
        institution = ""
        for line in text.splitlines():
            line = line.strip()
            if len(line) > 4 and not line.startswith("Form") and not re.match(r'^\d', line):
                institution = line
                break
        return {
            "issuer":        institution,
            "student_name":  f(text, r"(?:student'?s?\s+name|student)[^\n]{0,10}\n(.{3,60})"),
            "tuition_paid":  a(text, "payments received", "amounts billed", "1 payments", "box 1"),
            "scholarships":  a(text, "scholarships", "grants", "5 scholarships"),
            "adjustments":   a(text, "adjustments", "4 adjustments"),
        }

    def _parse_1098(self, text: str) -> dict:
        a, f = self._amt, self._find

        # ── Lender name ──
        # On CrossCountry / RoundPoint style 1098s pypdf emits the lender name
        # on the SAME text line as the header, right after "telephone no."
        # e.g. "...telephone no.CrossCountry Mortgage powered by RoundPoint"
        # Fallback: first non-blank line that follows the header (older layouts).
        _lender_noise = re.compile(
            r'RECIPIENT|LENDER|PAYER|BORROWER|OMB\s+No|zip|postal'
            r'|telephone|city\s+or|state\s+or|www\.|Copy\s+[ABC\d]'
            r'|department\s+of|internal\s+revenue|Phone\s*:',
            re.IGNORECASE)

        def _lender_ok(s: str) -> bool:
            return (len(s) > 3
                    and bool(re.match(r'^[A-Z]', s))
                    and not _lender_noise.search(s)
                    and not re.search(
                        r'\b(you|may|this|that|was|been|incurred|deductible|fully'
                        r'|secured|caution|amount|reimbursed|information)\b',
                        s, re.IGNORECASE))

        lender = ""
        # Primary: lender name appears inline right after "telephone no."
        tel_m = re.search(
            r'telephone\s+no\.?\s*([A-Z][^\n@]{2,80})(?:\n|$)', text, re.IGNORECASE)
        if tel_m and _lender_ok(tel_m.group(1).strip()):
            lender = tel_m.group(1).strip()

        if not lender:
            # Fallback: first non-blank line after RECIPIENT'S/LENDER'S name label
            lender_hdr = re.search(
                r"RECIPIENT.{0,5}S/LENDER.{0,5}S\s+name[^\n]*\n\s*\n?(.{3,100})",
                text, re.IGNORECASE)
            if lender_hdr:
                candidate = lender_hdr.group(1).strip()
                if _lender_ok(candidate):
                    lender = candidate

        def _dollar(*labels):
            """Find a $ amount after a label — span widened to 250 chars to cross
            blank lines between the box label and its value."""
            for label in labels:
                m = re.search(
                    rf'(?:{re.escape(label)})[\s\S]{{0,250}}?\$\s*([\d,]+\.\d{{2}})',
                    text, re.IGNORECASE,
                )
                if m:
                    return m.group(1).replace(',', '')
            return ""

        result = {
            "issuer":                    lender,
            "lender_tin":               f(text, r"RECIPIENT.{0,5}S/LENDER.{0,5}S\s+TIN[^\n]*\n([0-9]{2}-[0-9]{7})"),
            "mortgage_interest":         _dollar("mortgage interest received", "1 mortgage interest")
                                         or a(text, "mortgage interest received", "1 mortgage interest"),
            "outstanding_principal":     _dollar("outstanding mortgage principal", "2 outstanding")
                                         or a(text, "outstanding mortgage principal", "2 outstanding"),
            "origination_date":          self._date(text, "3 mortgage origination", "origination date"),
            "refund_overpaid_interest":  _dollar("refund of overpaid interest", "4 refund")
                                         or a(text, "refund of overpaid interest", "4 refund"),
            "mortgage_insurance":        _dollar("mortgage insurance premium", "5 mortgage insurance")
                                         or a(text, "mortgage insurance premium", "pmi"),
            "points":                    _dollar("points paid on purchase", "6 points paid")
                                         or a(text, "points paid", "6 points"),
            "num_properties":            f(text, r'(?:9\s+number\s+of\s+properties)[^\d]{0,40}(\d+)'),
            "other":                     _dollar("10 other") or a(text, "10 other"),
            "acquisition_date":          self._date(text, "11 mortgage acquisition", "acquisition date"),
            "account_number":            f(text, r'(?:account\s+number)[^\n]*\n([0-9A-Z\-]{4,20})'),
            "property_address":          f(text, r"(?:8\s+address[^\n]*|property address[^\n]*"
                                                  r"|address.*?securing\s+mortgage[^\n]*)\n(.{5,80})"),
        }

        # Box 7 checked → property address is same as borrower's — fill it in
        if not result["property_address"] or re.search(
                r'same\s+as|box\s+is\s+checked|If\s+address|\b7\s+If\b',
                result["property_address"], re.IGNORECASE):
            result["property_address"] = ""
            box7_m = re.search(r'7\s*[\[(]?[Xx✓][\])]?\s*[Ii]f\s+address', text)
            if box7_m:
                # The borrower name may be inline with the label (same text line)
                # or on a separate line — handle both with an optional name group.
                baddr = re.search(
                    r"PAYER.{0,5}S/BORROWER.{0,5}S\s+name[^\n]*\n"
                    r"(?:[A-Z][A-Z\s,.'\-]{3,80}\n)?"  # optional separate name line
                    r"(.{5,80})\n"                      # street address
                    r"([A-Z][^\n]{3,50})",              # city / state / zip
                    text, re.IGNORECASE)
                if baddr:
                    result["property_address"] = (
                        baddr.group(1).strip() + ", " + baddr.group(2).strip())

        return result

    def _parse_3922(self, text: str) -> dict:
        a, d, f = self._amt, self._date, self._find
        company = f(text, r"(?:corporation|company|employer)[^\n]{0,15}\n(.{3,80})")
        if not company:
            for line in text.splitlines():
                line = line.strip()
                if len(line) > 4 and not line.startswith("Form") and not re.match(r'^\d', line):
                    company = line
                    break
        return {
            "issuer":               company,
            "company_name":         company,
            "grant_date":           d(text, "grant date", "offering date", "box 1"),
            "exercise_date":        d(text, "exercise date", "purchase date", "box 2"),
            "fmv_on_grant_date":    a(text, "fair market value.*grant", "fmv.*grant", "box 3"),
            "fmv_on_exercise_date": a(text, "fair market value.*exercise", "fmv.*exercise", "fmv.*purchase", "box 4"),
            "exercise_price":       a(text, "exercise price", "purchase price", "box 5"),
            "shares_transferred":   f(text, r"(?:shares transferred|box\s*6)[^\d]{0,20}([\d,]+\.?\d{0,6})"),
        }

    def _parse_1099_consolidated(self, text: str) -> dict:
        a, f = self._amt, self._find
        broker = ""
        for line in text.splitlines():
            line = line.strip()
            if len(line) > 4 and not line.startswith("Form") and not re.match(r'^\d', line):
                broker = line
                break
        return {
            "issuer":              broker,
            "account_last4":       f(text, r"(?:account|acct)[\s\S]{0,30}?(?:x+|[*]+)?(\d{4})\b"),
            "ordinary_dividends":  a(text, "ordinary dividends", "1a ordinary", "total ordinary"),
            "qualified_dividends": a(text, "qualified dividends", "1b qualified"),
            "total_cap_gain_dist": a(text, "total capital gain", "2a total", "cap gain dist"),
            "interest_income":     a(text, "interest income", "1 interest"),
            "gross_proceeds":      a(text, "gross proceeds", "1d gross"),
            "cost_basis":          a(text, "cost basis", "1e cost"),
            "net_gain_loss":       a(text, "net gain", "net loss", allow_negative=True),
            "federal_withheld":    a(text, "federal income tax withheld", "4 federal"),
        }

    def _parse_1099_r(self, text: str) -> dict:
        a, f = self._amt, self._find
        # payer name is typically the first non-empty line
        payer = ""
        for line in text.splitlines():
            line = line.strip()
            if len(line) > 4 and not line.startswith("Form"):
                payer = line
                break
        return {
            "issuer":              payer,
            "gross_distribution":  a(text, "gross distribution", "1 gross"),
            "taxable_amount":      a(text, "taxable amount", "2a taxable"),
            "federal_withheld":    a(text, "federal income tax withheld", "4 federal"),
            "distribution_code":   f(text, r"(?:distribution code|box\s*7)[^\w]{0,15}([A-Z0-9]{1,2})\b"),
            "state":               f(text, r"\b([A-Z]{2})\s+\d{5}"),
            "state_withheld":      a(text, "state tax withheld", "14 state"),
        }

    def _parse_ssa_1099(self, text: str) -> dict:
        a = self._amt
        return {
            "issuer":                       "Social Security Administration",
            "gross_benefits":               a(text, "total benefits paid", "gross benefits", "box 3"),
            "repaid_benefits":              a(text, "benefits repaid", "repaid to ssa", "box 4"),
            "net_benefits":                 a(text, "net benefits", "box 5", "net amount"),
            "medicare_deducted":            a(text, "medicare", "part b premiums", "part d"),
            "voluntary_federal_withheld":   a(text, "voluntary withholding", "federal tax withheld", "box 6"),
        }