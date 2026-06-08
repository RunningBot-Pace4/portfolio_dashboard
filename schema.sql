CREATE TABLE IF NOT EXISTS portfolio_records (
    id BIGSERIAL PRIMARY KEY,
    purchase_date DATE NOT NULL,
    share_code TEXT NOT NULL,
    transaction_type TEXT NOT NULL DEFAULT 'BUY'
        CHECK (UPPER(TRIM(transaction_type)) IN ('BUY', 'SELL')),
    investment_amount NUMERIC(18, 4) NOT NULL CHECK (investment_amount >= 0),
    purchase_units NUMERIC(18, 8) NOT NULL CHECK (purchase_units > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE portfolio_records
    ADD COLUMN IF NOT EXISTS transaction_type TEXT NOT NULL DEFAULT 'BUY';

UPDATE portfolio_records
SET transaction_type = 'BUY'
WHERE transaction_type IS NULL OR TRIM(transaction_type) = '';

CREATE INDEX IF NOT EXISTS idx_portfolio_records_share_code
    ON portfolio_records (share_code);

CREATE INDEX IF NOT EXISTS idx_portfolio_records_purchase_date
    ON portfolio_records (purchase_date);

CREATE INDEX IF NOT EXISTS idx_portfolio_records_transaction_type
    ON portfolio_records (transaction_type);
