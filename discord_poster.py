import base64
import time
import requests

# Em-dash required — signal_parser._NEW_PATTERNS[0] matches: SYMBOL/USDT — LONG/SHORT
_EM_DASH = "—"


def format_signal(symbol: str, side: str, entry: float | None, sl: float | None,
                  tps: list[float], is_market: bool = False, notes: str = "") -> str:
    """Produce Discord message text matching signal_parser._NEW_PATTERNS[0]."""
    # Normalize symbol to COIN/USDT format
    sym = symbol.replace("-", "/").upper()
    if not sym.endswith("/USDT"):
        sym = sym.split("/")[0] + "/USDT"

    direction = "LONG" if side.lower() in ("buy", "long") else "SHORT"
    lines = [f"{sym} {_EM_DASH} {direction}"]

    if is_market or entry is None:
        lines.append("Entry at CMP")
    else:
        lines.append(f"Entry ${entry:g}")

    if sl is not None:
        lines.append(f"Stop Loss ${sl:g}")

    clean_tps = [t for t in tps if t is not None]
    if len(clean_tps) == 1:
        lines.append(f"Take Profit ${clean_tps[0]:g}")
    else:
        for i, tp in enumerate(clean_tps, 1):
            lines.append(f"Take Profit {i} ${tp:g}")

    if notes and notes.strip():
        lines.append(notes.strip())

    return "\n".join(lines)


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
    """Decode base64 PNG string from the frontend screenshot."""
    if not b64_str:
        return None
    try:
        # strip data URI prefix if present
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        return base64.b64decode(b64_str)
    except Exception:
        return None
