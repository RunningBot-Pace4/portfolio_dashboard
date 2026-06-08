# Market Share Live Portfolio Dashboard

A small FastAPI + Neon Postgres dashboard for tracking share BUY and SELL transactions.

## Important Vercel structure

Keep this structure:

```text
api/index.py
app/__init__.py
app/main.py
app/db.py
app/market_data.py
app/models.py
app/templates/dashboard.html
requirements.txt
vercel.json
```

Do **not** create root `app.py` or root `index.py`. Those files can make Vercel download files or import the wrong module.

## Environment variables

Add these in Vercel Project Settings → Environment Variables:

```env
DATABASE_URL=your_neon_connection_string
BASIC_AUTH_USERNAME=admin
BASIC_AUTH_PASSWORD=your_private_password
PRICE_CACHE_SECONDS=120
PORTFOLIO_CURRENCY=USD
```

Select Production, Preview, and Development, then redeploy.

`PRICE_CACHE_SECONDS=120` keeps the backend quote cache aligned with the dashboard auto-refresh interval of 2 minutes.

`PORTFOLIO_CURRENCY=USD` means all portfolio summary, profit/loss, and charts are calculated in USD. Non-USD market quotes such as `TLX.AX` in AUD are converted to USD using the same market-data provider FX quote.

## Deploy to Vercel

1. Push this folder to GitHub.
2. In Vercel, Add New → Project.
3. Import your GitHub repo.
4. Set Framework Preset to `Other`.
5. Set Root Directory to the folder that contains `api/`, `app/`, `requirements.txt`, and `vercel.json`.
6. Add the environment variables above.
7. Deploy.

Test:

```text
https://your-project.vercel.app/healthz
```

Expected:

```json
{
  "status": "ok",
  "database": "postgres",
  "auth": "enabled"
}
```

Then open:

```text
https://your-project.vercel.app
```

## Run locally

PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env with your Neon DATABASE_URL
python -m uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000
```

## Share code mapping

The app accepts normal codes like:

```text
NVDA, ORCL, GOOGL, NU, GRAB, TSM, HROW, SAIL, META, MSFT, AVGO, GLDM
```

It also accepts GoogleFinance-style codes like:

```text
NASDAQ:NVDA
NYSE:ORCL
ASX:TLX
HKG:0700
SGX:D05
KLSE:MAYBANK
```

`TLX` is mapped to `TLX.AX` by default. `TLX.AX` is quoted in AUD, so the app now converts it to `PORTFOLIO_CURRENCY` for summary and profit/loss calculations. Change `SYMBOL_OVERRIDES` in `app/market_data.py` if needed.

## Clear test data directly in Neon

This project does not include a dashboard clear-all button. To clear test data, use Neon SQL Editor and run:

```sql
TRUNCATE TABLE portfolio_records RESTART IDENTITY;
```

## Export PDF report

The dashboard now includes:

```text
Export PDF
```

This downloads:

```text
marketsharelive-portfolio-report.pdf
```

The PDF includes portfolio metrics, summary by share code, and purchase records.

## v12 UI Theme Fix

- Fixed light mode live badge text visibility.
- Improved light mode contrast for market cards, labels, badges, and action buttons.
- Live and summary data still auto-refresh every 2 minutes.


## Buy / Sell transaction support

The dashboard now supports:

```text
BUY  = Buy Amount / Share Unit = Average Buy Price
SELL = Sell Amount / Share Unit = Sell Price
```

Sell profit uses the **average cost method** and does not include broker fees.

Example:

```text
Bought 2 GOOGL at average cost 169.95
Sold 1 GOOGL for 500.00

Realized Profit = 500.00 - 169.95
```

Existing Neon tables are migrated automatically. Old rows are treated as `BUY`.


## v15 Features

- Dashboard filters for summary and transaction records by share code, transaction type, and date range.
- Transaction count beside the Buy / Sell Transaction Records title.
- Portfolio charts: holding allocation, profit/loss by share, and buy vs sell amount.


## v16 Currency conversion

- Market quotes that are not in the portfolio currency are converted automatically.
- Live Market Dashboard shows both converted price and native market price when conversion happens.
- Summary Dashboard, metrics, charts, and PDF report use the converted portfolio currency value.
- Default portfolio currency is USD. Change it with `PORTFOLIO_CURRENCY`.


## v17 UI updates

- Premium modern dashboard redesign for dark and light mode.
- Live Market Dashboard cards redesigned with quote status, converted price, native price and FX note.
- Smart Filters now include search, share code, transaction type, date range and holding status.
- Summary and transaction table headers are clickable for sorting visible rows.
