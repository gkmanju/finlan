#!/usr/bin/env python3
"""
Clean up old CSV-imported portfolio data
Keeps only Plaid-synced data
"""
import sys
sys.path.append('/opt/finlan')

from app.database import SessionLocal
from app.models import PortfolioAccount, Holding, BankTransaction, PlaidItem

def cleanup_csv_data():
    db = SessionLocal()
    
    try:
        # Get all Plaid items to identify which accounts to keep
        plaid_items = db.query(PlaidItem).all()
        plaid_institutions = [item.institution_name for item in plaid_items]
        
        print(f"Found {len(plaid_institutions)} Plaid-connected institutions: {plaid_institutions}")
        
        # Delete accounts NOT from Plaid (CSV imported accounts)
        csv_accounts = db.query(PortfolioAccount).filter(
            ~PortfolioAccount.institution.in_(plaid_institutions)
        ).all() if plaid_institutions else db.query(PortfolioAccount).all()
        
        print(f"\nFound {len(csv_accounts)} CSV-imported accounts to delete")
        
        for account in csv_accounts:
            print(f"  - {account.institution} - {account.account_name} ({account.account_type})")
            
            # Delete associated holdings
            holdings_count = db.query(Holding).filter(Holding.account_id == account.id).delete()
            print(f"    Deleted {holdings_count} holdings")
            
            # Delete associated transactions
            txn_count = db.query(BankTransaction).filter(BankTransaction.account_id == account.id).delete()
            print(f"    Deleted {txn_count} transactions")
            
            # Delete the account
            db.delete(account)
        
        db.commit()
        print(f"\n✓ Cleanup complete! Removed {len(csv_accounts)} CSV-imported accounts")
        
        # Show remaining accounts
        remaining = db.query(PortfolioAccount).all()
        print(f"\nRemaining accounts ({len(remaining)}):")
        for account in remaining:
            print(f"  - {account.institution} - {account.account_name} (${account.balance})")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    cleanup_csv_data()
