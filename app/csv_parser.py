"""
CSV Parser for multiple bank and brokerage formats
Handles: USB Bank, Chase, Fidelity, 401k, and generic CSV formats
"""
import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
import re


class CSVParser:
    """Parse various bank/brokerage CSV formats into standardized transaction data"""
    
    @staticmethod
    def detect_format(content: str) -> str:
        """Detect CSV format based on headers and content"""
        lines = content.strip().split('\n')
        if not lines:
            return "unknown"
        
        first_line = lines[0].lower()
        
        # USB Bank format
        if 'date","transaction","name","memo","amount' in first_line:
            return "usb_bank"
        
        # Chase format
        if 'details,posting date,description,amount,type,balance' in first_line:
            return "chase"
        
        # Fidelity Statement format
        if 'account type,account,beginning mkt value' in first_line:
            return "fidelity_statement"
        
        # Fidelity Transaction History format
        if 'run date,account,action,symbol,security description,quantity' in first_line:
            return "fidelity_transactions"
        
        # 401k format (has header rows)
        if 'plan name:' in first_line or ('date range' in first_line and len(lines) > 2):
            return "401k"
        
        # Generic transaction format
        if any(x in first_line for x in ['date', 'amount', 'description']):
            return "generic"
        
        return "unknown"
    
    @staticmethod
    def parse_usb_bank(content: str) -> List[Dict]:
        """Parse USB Bank CSV format"""
        transactions = []
        reader = csv.DictReader(io.StringIO(content))
        
        for row in reader:
            try:
                amount = Decimal(row['Amount'].replace(',', ''))
                trans_type = 'credit' if amount > 0 else 'debit'
                
                transactions.append({
                    'date': datetime.strptime(row['Date'], '%Y-%m-%d').date(),
                    'description': f"{row['Transaction']} - {row['Name']}",
                    'memo': row.get('Memo', ''),
                    'amount': amount,
                    'transaction_type': trans_type,
                    'balance': None
                })
            except Exception as e:
                print(f"Error parsing USB row: {e}")
                continue
        
        return transactions
    
    @staticmethod
    def parse_chase(content: str) -> List[Dict]:
        """Parse Chase CSV format"""
        transactions = []
        reader = csv.DictReader(io.StringIO(content))
        
        for row in reader:
            try:
                amount = Decimal(row['Amount'].replace(',', ''))
                balance = Decimal(row['Balance'].replace(',', '')) if row.get('Balance') else None
                
                # Parse date (MM/DD/YYYY format)
                date_str = row['Posting Date']
                trans_date = datetime.strptime(date_str, '%m/%d/%Y').date()
                
                transactions.append({
                    'date': trans_date,
                    'description': row['Description'],
                    'amount': amount,
                    'transaction_type': row['Type'].lower(),
                    'balance': balance
                })
            except Exception as e:
                print(f"Error parsing Chase row: {e}")
                continue
        
        return transactions
    
    @staticmethod
    def parse_fidelity_statement(content: str) -> Tuple[List[Dict], List[Dict]]:
        """Parse Fidelity statement CSV - returns (account_balances, holdings)"""
        lines = content.strip().split('\n')
        reader = csv.reader(io.StringIO(content))
        
        account_balances = []
        holdings = []
        
        in_account_section = True
        in_holdings_section = False
        current_account = None
        
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            
            # Account summary section
            if in_account_section and 'Account Type' in row[0]:
                continue
            
            if in_account_section and len(row) >= 7 and row[0] and not row[0].startswith('Symbol'):
                try:
                    account_type = row[0]
                    account_num = row[1]
                    ending_value = Decimal(row[4].replace(',', '').replace('$', '')) if row[4] else Decimal('0')
                    
                    account_balances.append({
                        'account_type': account_type,
                        'account_number': account_num,
                        'balance': ending_value
                    })
                    current_account = account_num
                except:
                    pass
            
            # Holdings section
            if 'Symbol/CUSIP' in str(row):
                in_account_section = False
                in_holdings_section = True
                continue
            
            if in_holdings_section and len(row) >= 3 and row[0] and row[0] not in ['', ' ']:
                try:
                    if row[0].strip() and not row[0].startswith('X') and len(row[0]) <= 10:
                        holdings.append({
                            'account_number': current_account,
                            'symbol': row[0],
                            'description': row[1] if len(row) > 1 else '',
                            'quantity': Decimal(row[2].replace(',', '')) if len(row) > 2 and row[2] else Decimal('0'),
                            'price': Decimal(row[3].replace(',', '').replace('$', '')) if len(row) > 3 and row[3] else None,
                            'value': Decimal(row[5].replace(',', '').replace('$', '')) if len(row) > 5 and row[5] else None,
                        })
                except:
                    pass
        
        return account_balances, holdings
    
    @staticmethod
    def parse_fidelity_transactions(content: str) -> List[Dict]:
        """Parse Fidelity transaction history CSV"""
        transactions = []
        lines = content.strip().split('\n')
        
        # Skip header
        reader = csv.DictReader(io.StringIO(content))
        
        for row in reader:
            try:
                # Parse date
                date_str = row.get('Run Date', '')
                if date_str:
                    trans_date = datetime.strptime(date_str, '%m/%d/%Y').date()
                else:
                    continue
                
                action = row.get('Action', '')
                symbol = row.get('Symbol', '')
                description = row.get('Security Description', '')
                quantity = row.get('Quantity', '0')
                amount = row.get('Amount', '0').replace('$', '').replace(',', '')
                
                transactions.append({
                    'date': trans_date,
                    'description': f"{action} {symbol} - {description}".strip(),
                    'amount': Decimal(amount) if amount else Decimal('0'),
                    'quantity': Decimal(quantity) if quantity else None,
                    'symbol': symbol,
                    'transaction_type': action.lower()
                })
            except Exception as e:
                print(f"Error parsing Fidelity transaction: {e}")
                continue
        
        return transactions
    
    @staticmethod
    def parse_401k(content: str) -> List[Dict]:
        """Parse 401k CSV format (with header rows)"""
        lines = content.strip().split('\n')
        
        # Skip the first 2-3 header lines
        data_start = 0
        for i, line in enumerate(lines):
            if 'Date' in line and 'Transaction' in line:
                data_start = i
                break
        
        if data_start == 0:
            return []
        
        # Parse from data start
        csv_content = '\n'.join(lines[data_start:])
        reader = csv.DictReader(io.StringIO(csv_content))
        
        transactions = []
        for row in reader:
            try:
                date_str = row.get('Date', '').strip()
                if not date_str:
                    continue
                
                trans_date = datetime.strptime(date_str, '%m/%d/%Y').date()
                
                # Sum all amount columns
                amount = Decimal('0')
                for key, value in row.items():
                    if 'amount' in key.lower() and value:
                        try:
                            amount += Decimal(value.replace('$', '').replace(',', ''))
                        except:
                            pass
                
                transactions.append({
                    'date': trans_date,
                    'description': row.get('Transaction Type', 'Transaction'),
                    'amount': amount,
                    'transaction_type': 'contribution'
                })
            except Exception as e:
                print(f"Error parsing 401k row: {e}")
                continue
        
        return transactions
    
    @staticmethod
    def parse_generic(content: str) -> List[Dict]:
        """Parse generic CSV with date, amount, description"""
        transactions = []
        reader = csv.DictReader(io.StringIO(content))
        headers = reader.fieldnames
        
        # Find column mappings
        date_col = next((h for h in headers if 'date' in h.lower()), None)
        amount_col = next((h for h in headers if 'amount' in h.lower()), None)
        desc_col = next((h for h in headers if any(x in h.lower() for x in ['description', 'memo', 'name'])), None)
        
        if not all([date_col, amount_col, desc_col]):
            return []
        
        for row in reader:
            try:
                # Try common date formats
                date_str = row[date_col]
                trans_date = None
                for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d']:
                    try:
                        trans_date = datetime.strptime(date_str, fmt).date()
                        break
                    except:
                        continue
                
                if not trans_date:
                    continue
                
                amount = Decimal(row[amount_col].replace('$', '').replace(',', ''))
                
                transactions.append({
                    'date': trans_date,
                    'description': row[desc_col],
                    'amount': amount,
                    'transaction_type': 'credit' if amount > 0 else 'debit',
                    'balance': None
                })
            except Exception as e:
                print(f"Error parsing generic row: {e}")
                continue
        
        return transactions
    
    @classmethod
    def parse_csv(cls, content: str, filename: str = "") -> Dict:
        """Main entry point - detect format and parse"""
        format_type = cls.detect_format(content)
        
        result = {
            'format': format_type,
            'filename': filename,
            'transactions': [],
            'account_balances': [],
            'holdings': [],
            'errors': []
        }
        
        try:
            if format_type == "usb_bank":
                result['transactions'] = cls.parse_usb_bank(content)
            elif format_type == "chase":
                result['transactions'] = cls.parse_chase(content)
            elif format_type == "fidelity_statement":
                balances, holdings = cls.parse_fidelity_statement(content)
                result['account_balances'] = balances
                result['holdings'] = holdings
            elif format_type == "fidelity_transactions":
                result['transactions'] = cls.parse_fidelity_transactions(content)
            elif format_type == "401k":
                result['transactions'] = cls.parse_401k(content)
            elif format_type == "generic":
                result['transactions'] = cls.parse_generic(content)
            else:
                result['errors'].append(f"Unknown CSV format: {filename}")
        except Exception as e:
            result['errors'].append(f"Error parsing {filename}: {str(e)}")
        
        return result
