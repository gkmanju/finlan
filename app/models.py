from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    accounts = relationship("Account", back_populates="owner")
    transactions = relationship("Transaction", back_populates="user")
    receipts = relationship("Receipt", back_populates="user")
    portfolio_accounts = relationship("PortfolioAccount", back_populates="user")
    holdings = relationship("Holding", back_populates="user")
    bank_transactions = relationship("BankTransaction", back_populates="user")
    broker_credentials = relationship("BrokerCredential", back_populates="user")
    mortgage_accounts = relationship("MortgageAccount", back_populates="user")
    tax_documents = relationship("TaxDocument", back_populates="user")
    business_transactions = relationship("BusinessTransaction", back_populates="user")


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)  # e.g., cash, bank, credit
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    owner = relationship("User", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account")


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    type = Column(String(20), nullable=False)  # income or expense

    transactions = relationship("Transaction", back_populates="category")


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    date = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)

    is_income = Column(Boolean, default=False)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)

    user = relationship("User", back_populates="transactions")
    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")


class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    service_date = Column(Date, nullable=False)
    provider = Column(String(150), nullable=False)
    patient_name = Column(String(100), nullable=True)
    category = Column(String(100), nullable=True)
    amount = Column(Numeric(12, 2), nullable=True)
    payment_method = Column(String(50), nullable=True)  # HSA Card, Personal Card, Cash
    paid_date = Column(Date, nullable=True)
    submitted_date = Column(Date, nullable=True)
    reimbursed = Column(Boolean, default=False)
    reimbursement_amount = Column(Numeric(12, 2), nullable=True)
    reimbursement_date = Column(Date, nullable=True)
    claim_number = Column(String(100), nullable=True)
    tax_year = Column(Integer, nullable=True)
    hsa_eligible = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="receipts")
    files = relationship("ReceiptFile", back_populates="receipt", cascade="all, delete-orphan")


class ReceiptFile(Base):
    """Files attached to receipts (one receipt can have multiple files)"""
    __tablename__ = "receipt_files"
    id = Column(Integer, primary_key=True, index=True)
    
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=False)
    file_name = Column(String(255), nullable=False)  # stored filename
    original_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    receipt = relationship("Receipt", back_populates="files")


class PortfolioAccount(Base):
    """Investment and bank accounts"""
    __tablename__ = "portfolio_accounts"
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    institution = Column(String(100), nullable=False)  # Fidelity, Chase, etc.
    account_type = Column(String(50), nullable=False)  # investment, checking, savings, credit_card
    account_name = Column(String(150), nullable=True)  # Custom name/nickname
    account_holder = Column(String(150), nullable=True)  # Actual account holder name (e.g., "John Doe")
    account_number_last4 = Column(String(4), nullable=True)  # Last 4 digits for identification
    balance = Column(Numeric(15, 2), default=0)
    currency = Column(String(3), default="USD")
    last_synced = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="portfolio_accounts")
    holdings = relationship("Holding", back_populates="account")
    bank_transactions = relationship("BankTransaction", back_populates="account")


class Holding(Base):
    """Investment holdings - stocks, ETFs, mutual funds"""
    __tablename__ = "holdings"
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("portfolio_accounts.id"), nullable=False)
    
    symbol = Column(String(20), nullable=False)  # Stock ticker
    name = Column(String(200), nullable=True)  # Full name
    quantity = Column(Numeric(15, 6), nullable=False)
    cost_basis = Column(Numeric(15, 2), nullable=True)  # Total purchase price
    current_price = Column(Numeric(15, 2), nullable=True)
    current_value = Column(Numeric(15, 2), nullable=True)
    asset_type = Column(String(50), nullable=True)  # stock, etf, mutual_fund, bond, crypto
    snapshot_date = Column(Date, nullable=False)  # Date of this data
    
    user = relationship("User", back_populates="holdings")
    account = relationship("PortfolioAccount", back_populates="holdings")


class BankTransaction(Base):
    """Bank and credit card transactions"""
    __tablename__ = "bank_transactions"
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("portfolio_accounts.id"), nullable=False)
    
    transaction_date = Column(Date, nullable=False)
    post_date = Column(Date, nullable=True)
    description = Column(String(255), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)  # Negative for expenses, positive for income
    category = Column(String(100), nullable=True)  # Auto-categorized or manual
    transaction_type = Column(String(50), nullable=True)  # debit, credit, transfer, fee, etc.
    balance_after = Column(Numeric(15, 2), nullable=True)
    notes = Column(Text, nullable=True)
    import_id = Column(String(100), nullable=True)  # External transaction ID to prevent duplicates
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="bank_transactions")
    account = relationship("PortfolioAccount", back_populates="bank_transactions")


class BrokerCredential(Base):
    """Encrypted broker credentials for automated sync"""
    __tablename__ = "broker_credentials"
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    institution = Column(String(100), nullable=False)  # Fidelity, E*TRADE, etc.
    username = Column(String(255), nullable=False)
    encrypted_password = Column(Text, nullable=False)  # Encrypted password
    additional_data = Column(Text, nullable=True)  # JSON for MFA tokens, security questions, etc.
    is_active = Column(Boolean, default=True)
    last_used = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="broker_credentials")


class PlaidItem(Base):
    """Store Plaid access tokens and item info"""
    __tablename__ = "plaid_items"
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    item_id = Column(String(255), nullable=False, unique=True)
    access_token = Column(Text, nullable=False)  # Should be encrypted in production
    institution_name = Column(String(255), nullable=True)
    institution_id = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    last_synced = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", backref="plaid_items")


class ESPPGrant(Base):
    """Store ESPP purchase grants with full tax lot tracking"""
    __tablename__ = "espp_grants"
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("portfolio_accounts.id"), nullable=False)
    
    symbol = Column(String(20), nullable=False, index=True)
    record_type = Column(String(50), nullable=True)  # e.g., "Employee Stock Purchase Plan"
    purchase_date = Column(Date, nullable=True)
    purchase_price = Column(Numeric(12, 4), nullable=True)  # Price per share at purchase
    purchased_qty = Column(Numeric(16, 6), nullable=True)  # Original purchased quantity
    sellable_qty = Column(Numeric(16, 6), nullable=True)  # Current sellable quantity
    expected_gain_loss = Column(Numeric(12, 2), nullable=True)
    est_market_value = Column(Numeric(12, 2), nullable=True)
    
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", backref="espp_grants")
    account = relationship("PortfolioAccount", backref="espp_grants")


class RSUGrant(Base):
    """Store RSU grants with vesting schedule tracking"""
    __tablename__ = "rsu_grants"
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("portfolio_accounts.id"), nullable=False)
    
    symbol = Column(String(20), nullable=False, index=True)
    record_type = Column(String(50), nullable=True)  # e.g., "Restricted Stock Units"
    grant_number = Column(String(50), nullable=True, index=True)  # Grant identifier
    grant_date = Column(Date, nullable=True)
    settlement_type = Column(String(50), nullable=True)
    
    granted_qty = Column(Numeric(16, 6), nullable=True)  # Total granted shares
    withheld_qty = Column(Numeric(16, 6), nullable=True)  # Shares withheld for taxes
    vested_qty = Column(Numeric(16, 6), nullable=True)  # Total vested shares
    unvested_qty = Column(Numeric(16, 6), nullable=True)  # Shares still vesting
    sellable_qty = Column(Numeric(16, 6), nullable=True)  # Shares available to sell
    est_market_value = Column(Numeric(12, 2), nullable=True)
    
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", backref="rsu_grants")
    account = relationship("PortfolioAccount", backref="rsu_grants")


class MortgageAccount(Base):
    """Mortgage loan details for non-Plaid servicers like RoundPoint"""
    __tablename__ = "mortgage_accounts"
    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    servicer_name = Column(String(100), nullable=False)           # e.g., RoundPoint
    loan_number = Column(String(50), nullable=True)
    property_address = Column(String(250), nullable=True)
    original_balance = Column(Numeric(12, 2), nullable=True)
    interest_rate = Column(Numeric(6, 4), nullable=True)          # e.g., 6.875
    loan_term_months = Column(Integer, nullable=True)             # 360 = 30yr
    origination_date = Column(Date, nullable=True)
    maturity_date = Column(Date, nullable=True)
    monthly_payment = Column(Numeric(12, 2), nullable=True)       # P+I+Escrow
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="mortgage_accounts")
    statements = relationship("MortgageStatement", back_populates="mortgage",
                              cascade="all, delete-orphan", order_by="MortgageStatement.statement_date.desc()")


class MortgageStatement(Base):
    """One record per uploaded monthly statement"""
    __tablename__ = "mortgage_statements"
    id = Column(Integer, primary_key=True, index=True)

    mortgage_id = Column(Integer, ForeignKey("mortgage_accounts.id"), nullable=False)
    statement_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    unpaid_principal = Column(Numeric(12, 2), nullable=True)
    interest_rate = Column(Numeric(6, 4), nullable=True)
    payment_amount = Column(Numeric(12, 2), nullable=True)        # Total amount due
    principal_portion = Column(Numeric(12, 2), nullable=True)
    interest_portion = Column(Numeric(12, 2), nullable=True)
    escrow_portion = Column(Numeric(12, 2), nullable=True)
    escrow_balance = Column(Numeric(12, 2), nullable=True)
    ytd_interest = Column(Numeric(12, 2), nullable=True)
    ytd_taxes = Column(Numeric(12, 2), nullable=True)
    raw_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    mortgage = relationship("MortgageAccount", back_populates="statements")


class TaxDocument(Base):
    """Tax document vault — store and track annual tax forms (W-2, 1099s, 1098s, etc.)"""
    __tablename__ = "tax_documents"
    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tax_year = Column(Integer, nullable=False, index=True)
    # W2 | 1099_INT | 1098_T | 1098 | 3922 | 1099_CONSOLIDATED
    form_type = Column(String(40), nullable=False)
    issuer = Column(String(150), nullable=True)       # Employer, bank, brokerage, university
    description = Column(String(255), nullable=True)  # e.g., "Primary employment", "Brokerage XXXX"
    # expected = received but not yet uploaded / uploaded = file stored / filed = used in return
    status = Column(String(20), default="uploaded")
    extracted_data = Column(Text, nullable=True)      # JSON blob of form-specific key figures
    file_name = Column(String(255), nullable=True)    # stored filename on disk
    original_name = Column(String(255), nullable=True)
    content_type = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="tax_documents")


class BusinessTransaction(Base):
    """Wave CSV imported transactions for Schedule C / sole proprietorship P&L"""
    __tablename__ = "business_transactions"
    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tax_year = Column(Integer, nullable=False, index=True)

    transaction_date = Column(Date, nullable=False)
    description = Column(String(255), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)        # positive = income, negative = expense
    account_name = Column(String(150), nullable=True)
    wave_category = Column(String(150), nullable=True)     # raw Wave category name
    schedule_c_line = Column(String(10), nullable=True)    # e.g. "1", "8", "18", "24b"
    schedule_c_label = Column(String(150), nullable=True)  # human label for that line
    is_income = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    import_batch = Column(String(36), nullable=True)       # UUID — lets user replace a batch
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="business_transactions")
