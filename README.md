# Share Portfolio Dashboard — Vercel + Neon Version

This version is built for:

- **Vercel**: one stable public URL for the web dashboard
- **Neon Postgres**: persistent database storage
- **FastAPI**: Python web app and API
- **Yahoo Finance chart endpoint**: lightweight market quote lookup

No Excel and no CSV are needed. You add/edit/delete share purchases directly in the web dashboard.

## Features

- Live market dashboard for:
  `NVDA, ORCL, GOOGL, NU, GRAB, TSM, HROW, SAIL, TLX, META, MSFT, AVGO, GLDM`
- Add / edit / delete share purchase records
- Share code dropdown with custom code support
- Summary dashboard by share:
  - total invested
  - total units
  - average price
  - current market price
  - current value
  - total earn/loss
  - return %
- Neon Postgres persistence
- Optional password protection with HTTP Basic Auth

## Project Structure

```text
portfolio_dashboard/
  index.py
  app/
    main.py
    templates/
      dashboard.html
  scripts/
    migrate_sqlite_to_neon.py
  schema.sql
  requirements.txt
  pyproject.toml
  vercel.json
  .env.example
```

## 1. Create Neon database

1. Sign in to Neon.
2. Create a new project.
3. Open **Connect**.
4. Copy the Postgres connection string.
5. Use the connection string as `DATABASE_URL`.

It should look like:

```text
postgresql://USER:PASSWORD@HOST/neondb?sslmode=require&channel_binding=require
```

## 2. Deploy to Vercel

### Option A — GitHub + Vercel Dashboard

1. Upload this folder to a GitHub repository.
2. In Vercel, click **Add New Project**.
3. Import the GitHub repository.
4. Add these environment variables:

```text
DATABASE_URL=your_neon_connection_string
BASIC_AUTH_USERNAME=admin
BASIC_AUTH_PASSWORD=your_private_password
PRICE_CACHE_SECONDS=300
```

5. Click **Deploy**.

Your stable production URL will be:

```text
https://your-project-name.vercel.app
```

### Option B — Vercel CLI

Install Vercel CLI:

```bash
npm i -g vercel
```

Deploy:

```bash
vercel
```

Set environment variables:

```bash
vercel env add DATABASE_URL production
vercel env add BASIC_AUTH_USERNAME production
vercel env add BASIC_AUTH_PASSWORD production
vercel env add PRICE_CACHE_SECONDS production
```

Then deploy production:

```bash
vercel --prod
```

## 3. Local run on Windows

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set your Neon `DATABASE_URL`.

Run:

```powershell
python -m uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000
```

## 4. Test deployment

Open:

```text
https://your-project-name.vercel.app/healthz
```

Expected result:

```json
{
  "status": "ok",
  "database": "postgres",
  "auth": "enabled"
}
```

## 5. Migrate old local SQLite data to Neon

If you already have records in an older `data/portfolio.db`, copy that file into this project, then run:

```powershell
$env:DATABASE_URL="your_neon_connection_string"
python scripts/migrate_sqlite_to_neon.py --sqlite data/portfolio.db
```

## 6. Share code format

The app uses Yahoo-style lookup symbols.

Examples:

```text
NASDAQ:NVDA  -> NVDA
NYSE:ORCL    -> ORCL
HKG:0700     -> 0700.HK
SGX:D05      -> D05.SI
KLSE:MAYBANK -> MAYBANK.KL
TLX          -> TLX.AX
```

## Notes

- Prices are for personal tracking only.
- Market prices may be delayed and may differ from your broker.
- The quote lookup is not a guaranteed official market-data feed.
- Because a Vercel URL is public, set `BASIC_AUTH_USERNAME` and `BASIC_AUTH_PASSWORD`.
