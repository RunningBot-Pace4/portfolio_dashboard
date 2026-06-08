from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from .config import BASIC_AUTH_PASSWORD, BASIC_AUTH_USERNAME, DEFAULT_SHARE_CODES, PORTFOLIO_CURRENCY, auth_is_enabled
from .db import (
    DatabaseNotConfigured,
    delete_record,
    holdings_summary_rows,
    insert_record,
    list_records,
    ping_database,
    update_record,
)
from .market_data import fetch_market_price
from .models import PortfolioRecordIn
from .pdf_report import build_portfolio_pdf


app = FastAPI(title="Market Share Live Portfolio Dashboard", version="1.1.0")
security = HTTPBasic(auto_error=False)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    if not auth_is_enabled():
        return

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    username_ok = secrets.compare_digest(credentials.username, BASIC_AUTH_USERNAME)
    password_ok = secrets.compare_digest(credentials.password, BASIC_AUTH_PASSWORD)

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )


def build_summary_payload() -> dict:
    holdings = holdings_summary_rows()

    total_buy_amount = 0.0
    total_sell_amount = 0.0
    total_cost_basis = 0.0
    total_market_value = 0.0
    total_realized_return = 0.0
    total_unrealized_return = 0.0

    for row in holdings:
        quote = fetch_market_price(row["share_code"])
        price = quote.get("price")

        row["current_price"] = price
        row["currency"] = quote.get("currency", "")
        row["native_price"] = quote.get("native_price")
        row["native_currency"] = quote.get("native_currency", "")
        row["fx_rate"] = quote.get("fx_rate")
        row["fx_symbol"] = quote.get("fx_symbol")
        row["converted"] = quote.get("converted", False)
        row["conversion_error"] = quote.get("conversion_error")
        row["market_symbol"] = quote.get("market_symbol", row["share_code"])
        row["price_error"] = quote.get("error")

        remaining_units = float(row.get("remaining_units") or row.get("total_units") or 0)
        cost_basis = float(row.get("cost_basis") or row.get("total_invested") or 0)
        total_buy = float(row.get("total_buy_amount") or 0)
        total_sell = float(row.get("total_sell_amount") or 0)
        realized_return = float(row.get("realized_return") or 0)

        if price is not None:
            market_value = remaining_units * float(price)
            unrealized_return = market_value - cost_basis
        else:
            market_value = None
            unrealized_return = None

        total_return = realized_return + (unrealized_return or 0)
        return_percent = (total_return / total_buy * 100) if total_buy else 0

        row["market_value"] = market_value
        row["unrealized_return"] = unrealized_return
        row["total_return"] = total_return
        row["return_percent"] = return_percent

        # Backward-compatible aliases.
        row["total_invested"] = cost_basis
        row["total_units"] = remaining_units

        total_buy_amount += total_buy
        total_sell_amount += total_sell
        total_cost_basis += cost_basis
        total_realized_return += realized_return

        if market_value is not None:
            total_market_value += market_value
        if unrealized_return is not None:
            total_unrealized_return += unrealized_return

    total_return = total_realized_return + total_unrealized_return
    portfolio_return_percent = (total_return / total_buy_amount * 100) if total_buy_amount else 0

    return {
        "holdings": holdings,
        "portfolio": {
            "portfolio_currency": PORTFOLIO_CURRENCY,
            "total_buy_amount": total_buy_amount,
            "total_sell_amount": total_sell_amount,
            "cost_basis": total_cost_basis,
            "total_invested": total_cost_basis,
            "market_value": total_market_value,
            "realized_return": total_realized_return,
            "unrealized_return": total_unrealized_return,
            "total_return": total_return,
            "return_percent": portfolio_return_percent,
        },
    }


@app.get("/healthz")
def healthz() -> JSONResponse:
    database_state = "postgres"
    database_ok = False
    error = None

    try:
        database_ok = ping_database()
    except DatabaseNotConfigured as exc:
        database_state = "missing"
        error = str(exc)
    except Exception as exc:
        database_state = "error"
        error = str(exc)

    payload = {
        "status": "ok" if database_ok else "error",
        "database": database_state,
        "auth": "enabled" if auth_is_enabled() else "disabled",
    }
    if error:
        payload["error"] = error
    return JSONResponse(payload, status_code=200 if database_ok else 500)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(require_auth)):
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "share_codes": DEFAULT_SHARE_CODES,
            "portfolio_currency": PORTFOLIO_CURRENCY,
        },
    )


@app.get("/api/records")
def api_list_records(_: None = Depends(require_auth)):
    return {"records": list_records()}


@app.post("/api/records", status_code=201)
def api_create_record(record: PortfolioRecordIn, _: None = Depends(require_auth)):
    try:
        saved = insert_record(
            purchase_date=record.purchase_date.isoformat(),
            share_code=record.share_code,
            transaction_type=record.transaction_type,
            investment_amount=record.investment_amount,
            purchase_units=record.purchase_units,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"record": saved}


@app.put("/api/records/{record_id}")
def api_update_record(record_id: int, record: PortfolioRecordIn, _: None = Depends(require_auth)):
    try:
        saved = update_record(
            record_id=record_id,
            purchase_date=record.purchase_date.isoformat(),
            share_code=record.share_code,
            transaction_type=record.transaction_type,
            investment_amount=record.investment_amount,
            purchase_units=record.purchase_units,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not saved:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"record": saved}


@app.delete("/api/records/{record_id}")
def api_delete_record(record_id: int, _: None = Depends(require_auth)):
    deleted = delete_record(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"deleted": True}


@app.get("/api/quote/{share_code:path}")
def api_quote(share_code: str, _: None = Depends(require_auth)):
    return fetch_market_price(share_code)


@app.get("/api/market")
def api_market(_: None = Depends(require_auth)):
    return {"quotes": [fetch_market_price(code) for code in DEFAULT_SHARE_CODES]}


@app.get("/api/summary")
def api_summary(_: None = Depends(require_auth)):
    return build_summary_payload()


@app.get("/api/report.pdf")
def api_report_pdf(_: None = Depends(require_auth)):
    summary = build_summary_payload()
    records = list_records()
    pdf_bytes = build_portfolio_pdf(summary=summary, records=records)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="marketsharelive-portfolio-report.pdf"'},
    )


@app.get("/report.pdf")
def report_pdf(_: None = Depends(require_auth)):
    summary = build_summary_payload()
    records = list_records()
    pdf_bytes = build_portfolio_pdf(summary=summary, records=records)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="marketsharelive-portfolio-report.pdf"'},
    )
