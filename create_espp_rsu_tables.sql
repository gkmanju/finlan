-- Create ESPP grants table
CREATE TABLE IF NOT EXISTS espp_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    record_type VARCHAR(50),
    purchase_date DATE,
    purchase_price DECIMAL(12, 4),
    purchased_qty DECIMAL(16, 6),
    sellable_qty DECIMAL(16, 6),
    expected_gain_loss DECIMAL(12, 2),
    est_market_value DECIMAL(12, 2),
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_espp_grants_user_id ON espp_grants(user_id);
CREATE INDEX IF NOT EXISTS idx_espp_grants_symbol ON espp_grants(symbol);
CREATE INDEX IF NOT EXISTS idx_espp_grants_account_id ON espp_grants(account_id);

-- Create RSU grants table
CREATE TABLE IF NOT EXISTS rsu_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    record_type VARCHAR(50),
    grant_number VARCHAR(50),
    grant_date DATE,
    settlement_type VARCHAR(50),
    granted_qty DECIMAL(16, 6),
    withheld_qty DECIMAL(16, 6),
    vested_qty DECIMAL(16, 6),
    unvested_qty DECIMAL(16, 6),
    sellable_qty DECIMAL(16, 6),
    est_market_value DECIMAL(12, 2),
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_rsu_grants_user_id ON rsu_grants(user_id);
CREATE INDEX IF NOT EXISTS idx_rsu_grants_symbol ON rsu_grants(symbol);
CREATE INDEX IF NOT EXISTS idx_rsu_grants_grant_number ON rsu_grants(grant_number);
CREATE INDEX IF NOT EXISTS idx_rsu_grants_account_id ON rsu_grants(account_id);
