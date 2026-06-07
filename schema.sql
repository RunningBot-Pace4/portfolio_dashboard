CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    purchase_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    investment_amount NUMERIC(18, 6) NOT NULL CHECK (investment_amount > 0),
    purchase_units NUMERIC(18, 6) NOT NULL CHECK (purchase_units > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_symbol ON transactions(symbol);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(purchase_date);
