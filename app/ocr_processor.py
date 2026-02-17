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
