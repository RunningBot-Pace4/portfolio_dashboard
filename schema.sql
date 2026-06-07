CREATE TABLE IF NOT EXISTS portfolio_records (
    id BIGSERIAL PRIMARY KEY,
    purchase_date DATE NOT NULL,
    share_code TEXT NOT NULL,
    investment_amount NUMERIC(18, 4) NOT NULL CHECK (investment_amount >= 0),
    purchase_units NUMERIC(18, 8) NOT NULL CHECK (purchase_units > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_records_share_code
    ON portfolio_records (share_code);

CREATE INDEX IF NOT EXISTS idx_portfolio_records_purchase_date
    ON portfolio_records (purchase_date);
