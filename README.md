# Market Share Live Portfolio Dashboard

A small FastAPI + Neon Postgres dashboard for tracking share purchases.

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
```

Select Production, Preview, and Development, then redeploy.

`PRICE_CACHE_SECONDS=120` keeps the backend quote cache aligned with the dashboard auto-refresh interval of 2 minutes.

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

`TLX` is mapped to `TLX.AX` by default. Change `SYMBOL_OVERRIDES` in `app/market_data.py` if needed.

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
