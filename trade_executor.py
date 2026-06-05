"""
trade_executor.py — orchestrates the full analyst trade flow:
  validate ticket → get balance → size position → set leverage
  → place order → post Discord → log everything
"""

import math
from exchange_adapters import get_adapter
import analyst_db as db
from discord_poster import format_signal, post_to_discord, png_from_b64


def _normalize_symbol(raw: str) -> str:
    """Accept BTC, BTC/USDT, BTC-USDT → return BTC-USDT."""
    s = raw.strip().upper().replace("/", "-")
    if not s.endswith("-USDT"):
        s = s.split("-")[0] + "-USDT"
    return s


def _calculate_size(balance: float, risk_pct: float, entry: float | None,
                    sl: float | None, specs: dict) -> float | None:
    """
    Return contract size rounded to lot_size, or None if the trade can't be sized.
    For market orders with no entry, falls back to 1% of balance notional.
    """
    contract_value = specs.get("contract_value", 1.0) or 1.0
    lot_size = specs.get("lot_size", 0.001) or 0.001
    min_size = specs.get("min_size", 0.0)

    risk_budget = balance * risk_pct

    if entry and sl and abs(entry - sl) > 0:
        # Standard risk-based sizing
        coins_wanted = risk_budget / abs(entry - sl)
        contracts = coins_wanted / contract_value
    elif entry and entry > 0:
        # No SL provided: size by notional (1 risk_pct worth of notional)
        contracts = risk_budget / (entry * contract_value)
    else:
        # Market order, no entry: size by 1% notional at a rough guess
        return None

    contracts = math.floor(contracts / lot_size) * lot_size
    contracts = round(contracts, 8)

    if contracts < min_size:
        return None
    return contracts


def execute_and_post(analyst_id: int, ticket: dict) -> dict:
    """
    Execute a trade and broadcast the signal to Discord.

    ticket keys:
        exchange      str      "blofin" | "mexc" | "bybit"
        symbol        str      "BTC-USDT" or "BTC" or "BTC/USDT"
        side          str      "long" | "short"
        entry         float|None  None = market order
        sl            float|None
        tps           list[float]   up to 5 TP levels
        leverage      int
        risk_pct      float    e.g. 0.01 for 1%
        notes         str      optional, appended to Discord message
        chart_png_b64 str|None base64-encoded PNG screenshot
        dry_run       bool     if True, skip exchange call
    """
    exchange    = ticket.get("exchange", "blofin")
    symbol      = _normalize_symbol(ticket.get("symbol", "BTC-USDT"))
    side        = ticket.get("side", "long").lower()
    entry       = ticket.get("entry")
    sl          = ticket.get("sl")
    tps: list[float] = [t for t in (ticket.get("tps") or []) if t is not None]
    tp_first    = tps[0] if tps else None
    leverage    = int(ticket.get("leverage", 75))
    risk_pct    = float(ticket.get("risk_pct", 0.01))
    notes       = ticket.get("notes", "")
    chart_b64   = ticket.get("chart_png_b64", "")
    dry_run     = ticket.get("dry_run", False)
    trade_type  = ticket.get("trade_type", "leverage")
    sl_type     = ticket.get("sl_type", "hard")
    sl_tf       = ticket.get("sl_tf", "")
    dcas        = ticket.get("dcas") or []
    is_market   = ticket.get("is_market", entry is None)

    # Basic sanity checks
    if side not in ("long", "short"):
        return {"ok": False, "error": f"Invalid side: {side}"}

    if not is_market:
        entry = float(entry)
    if sl is not None:
        sl = float(sl)
    tps = [float(t) for t in tps]

    # Price/direction sanity for limit orders with SL
    if not is_market and sl is not None:
        if side == "long" and not (sl < entry):
            return {"ok": False, "error": f"LONG: SL ({sl}) must be below entry ({entry})"}
        if side == "short" and not (sl > entry):
            return {"ok": False, "error": f"SHORT: SL ({sl}) must be above entry ({entry})"}

    # Load analyst profile for webhook URL
    analyst = db.get_analyst_by_id(analyst_id)
    if not analyst:
        return {"ok": False, "error": "Analyst not found"}

    webhook_url = analyst["discord_webhook_url"]

    # Load exchange credentials
    creds = db.get_credentials(analyst_id, exchange)
    if not creds:
        return {"ok": False, "error": f"No {exchange} credentials saved. Go to Settings."}

    order_id = None
    if not dry_run:
        try:
            adapter = get_adapter(exchange, creds)
            balance = adapter.get_balance()
            if balance <= 0:
                return {"ok": False, "error": "Balance is zero or unavailable — check API key and endpoint"}

            specs = adapter.get_contract_specs(symbol)
            size = _calculate_size(balance, risk_pct, entry, sl, specs)
            if size is None:
                return {"ok": False, "error": "Position too small to size (below minimum contract size)"}

            actual_leverage = adapter.set_leverage(symbol, leverage)

            if is_market:
                result = adapter.place_market_order(symbol, side, size, sl, tp_first)
            else:
                result = adapter.place_order(symbol, side, size, entry, sl, tp_first)

            if result.get("error"):
                return {"ok": False, "error": f"Exchange error: {result['error']}"}

            order_id = result.get("order_id", "")

            # Store position
            db.open_position(analyst_id, exchange, symbol, side, entry or 0.0, sl or 0.0, tps, size, order_id,
                             trade_type=trade_type, sl_type=sl_type, sl_tf=sl_tf, dcas=dcas, notes=notes)

        except Exception as e:
            return {"ok": False, "error": f"Exchange execution failed: {e}"}

    # Post to Discord
    text = format_signal(symbol, side, entry, sl, tps, is_market, notes,
                         trade_type=trade_type, sl_type=sl_type, sl_tf=sl_tf, dcas=dcas)
    png_bytes = png_from_b64(chart_b64) if chart_b64 else None
    discord_ok = post_to_discord(webhook_url, text, png_bytes)

    # Log signal
    db.log_signal(analyst_id, symbol, side, entry, sl, tps, exchange, order_id, discord_ok,
                  notes=notes, trade_type=trade_type, sl_type=sl_type, dcas=dcas)

    result_msg = "dry_run — no order placed" if dry_run else f"order_id={order_id}"
    return {
        "ok": True,
        "order_id": order_id,
        "discord_ok": discord_ok,
        "dry_run": dry_run,
        "message": result_msg,
    }
