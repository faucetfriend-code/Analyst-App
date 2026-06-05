import base64
import time
import requests

# Em-dash — signal_parser._NEW_PATTERNS[0] matches: SYMBOL/USDT — LONG/SHORT
_EM_DASH = "—"

CLOSE_TYPE_LABELS = {
    "profit":      "Closed in Profit",
    "stopped":     "Stopped Out",
    "cut":         "Cut Early",
    "be":          "Closed Breakeven",
    "invalidation":"Invalidated",
    "partial":     "Partial Close",
}


def _fmt_price(p: float) -> str:
    """Format a price cleanly — no trailing zeros, comma thousands separator."""
    if p is None:
        return "?"
    if p >= 1000:
        return f"${p:,.2f}".rstrip("0").rstrip(".")
    if p >= 1:
        return f"${p:.4f}".rstrip("0").rstrip(".")
    return f"${p:.8f}".rstrip("0").rstrip(".")


def _pct(entry: float, level: float, side: str) -> str:
    if not entry or not level:
        return ""
    diff = (level - entry) / entry * 100
    if side.lower() in ("short", "sell"):
        diff = -diff
    sign = "+" if diff >= 0 else ""
    return f" ({sign}{diff:.2f}%)"


def format_signal(symbol: str, side: str, entry: float | None, sl: float | None,
                  tps: list[float], is_market: bool = False, notes: str = "",
                  trade_type: str = "leverage", sl_type: str = "hard",
                  sl_tf: str = "", dcas: list = None) -> str:
    """
    Produce Discord message text aligned with Unity Signal Bot format.
    Also matches signal_parser._NEW_PATTERNS[0] so the follower bot parses it.
    """
    sym = symbol.replace("-", "/").upper()
    if not sym.endswith("/USDT"):
        sym = sym.split("/")[0] + "/USDT"

    direction = "LONG" if side.lower() in ("buy", "long") else "SHORT"
    type_label = {"leverage": "Leverage", "spot": "Spot", "stock": "Stock"}.get(trade_type, "Leverage")

    lines = [f"{sym} {_EM_DASH} {direction} ({type_label})"]

    # Entry
    if is_market or entry is None:
        lines.append("Entry at CMP")
    elif dcas:
        # Show DCA structure
        for i, d in enumerate(dcas, 1):
            p = d.get("price") or d.get("entry")
            alloc = d.get("alloc", "")
            if p:
                alloc_str = f" [{alloc}%]" if alloc else ""
                lines.append(f"Entry {i} {_fmt_price(p)}{alloc_str}")
    else:
        lines.append(f"Entry {_fmt_price(entry)}")

    # Stop Loss
    if sl is not None:
        sl_suffix = ""
        if sl_type == "soft" and sl_tf:
            sl_suffix = f" (Soft — {sl_tf} candle close)"
        pct_str = _pct(entry, sl, direction) if entry else ""
        lines.append(f"Stop Loss {_fmt_price(sl)}{pct_str}{sl_suffix}")

    # Take Profits
    clean_tps = [t for t in (tps or []) if t is not None]
    if len(clean_tps) == 1:
        pct_str = _pct(entry, clean_tps[0], direction) if entry else ""
        lines.append(f"Take Profit {_fmt_price(clean_tps[0])}{pct_str}")
    else:
        for i, tp in enumerate(clean_tps, 1):
            pct_str = _pct(entry, tp, direction) if entry else ""
            lines.append(f"Take Profit {i} {_fmt_price(tp)}{pct_str}")

    # Notes
    if notes and notes.strip():
        lines.append("")
        lines.append(notes.strip())

    return "\n".join(lines)


def format_trade_update(symbol: str, side: str, event_type: str, detail: dict) -> str:
    """Format a trade management event (TP hit, SL move, close, etc.)"""
    sym = symbol.replace("-", "/").upper()
    if not sym.endswith("/USDT"):
        sym = sym.split("/")[0] + "/USDT"
    direction = "LONG" if side.lower() in ("buy", "long") else "SHORT"

    if event_type == "tp_hit":
        tp_num  = detail.get("tp_num", "")
        trim    = detail.get("trim_pct", 100)
        price   = detail.get("price")
        msg = f"✅ {sym} {direction} — TP{tp_num} Hit"
        if price:
            msg += f" @ {_fmt_price(price)}"
        if trim < 100:
            msg += f" (trimmed {trim}%)"
        return msg

    if event_type == "sl_be":
        return f"➡️ {sym} {direction} — Stop Loss moved to Breakeven"

    if event_type == "move_sl":
        new_sl = detail.get("new_sl")
        return f"➡️ {sym} {direction} — Stop Loss moved to {_fmt_price(new_sl)}"

    if event_type == "dca_filled":
        level = detail.get("dca_num", "")
        price = detail.get("price")
        avg   = detail.get("new_avg")
        msg = f"➡️ {sym} {direction} — DCA {level} filled"
        if price:
            msg += f" @ {_fmt_price(price)}"
        if avg:
            msg += f" | New avg entry: {_fmt_price(avg)}"
        return msg

    if event_type == "close":
        close_type  = detail.get("close_type", "profit")
        close_price = detail.get("price")
        close_pct   = detail.get("pct", 100)
        notes       = detail.get("notes", "")
        label = CLOSE_TYPE_LABELS.get(close_type, "Closed")
        emoji = "✅" if close_type == "profit" else ("❌" if close_type in ("stopped","cut") else "➡️")
        msg = f"{emoji} {sym} {direction} — {label}"
        if close_price:
            msg += f" @ {_fmt_price(close_price)}"
        if close_pct < 100:
            msg += f" ({close_pct}%)"
        if notes:
            msg += f"\n{notes}"
        return msg

    return f"{sym} {direction} — {event_type}"


def post_to_discord(webhook_url: str, text: str, png_bytes: bytes | None = None) -> bool:
    """POST signal text (+ optional chart image) to a Discord channel webhook."""
    for attempt in range(2):
        try:
            if png_bytes:
                resp = requests.post(
                    webhook_url,
                    data={"content": text},
                    files={"file": ("chart.png", png_bytes, "image/png")},
                    timeout=10,
                )
            else:
                resp = requests.post(
                    webhook_url,
                    json={"content": text},
                    timeout=10,
                )
            if resp.status_code == 429 and attempt == 0:
                retry_after = float(resp.json().get("retry_after", 1))
                time.sleep(retry_after)
                continue
            return resp.status_code in (200, 204)
        except requests.RequestException:
            return False
    return False


def png_from_b64(b64_str: str) -> bytes | None:
    if not b64_str:
        return None
    try:
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        return base64.b64decode(b64_str)
    except Exception:
        return None
