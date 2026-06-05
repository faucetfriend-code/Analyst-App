import os
import sqlite3
import json
from datetime import datetime, timezone

import bcrypt
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "analyst.db")

def _fernet() -> Fernet:
    key = os.environ.get("ANALYST_CRED_KEY", "")
    if not key:
        raise RuntimeError("ANALYST_CRED_KEY not set in .env — run: python setup.py init")
    return Fernet(key.encode())

def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()

def _decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS analyst_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            discord_webhook_url TEXT NOT NULL,
            default_exchange TEXT NOT NULL DEFAULT 'blofin',
            default_risk_pct REAL NOT NULL DEFAULT 0.01,
            default_leverage INTEGER NOT NULL DEFAULT 75,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS analyst_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analyst_id INTEGER NOT NULL REFERENCES analyst_profiles(id),
            exchange TEXT NOT NULL,
            api_key_enc TEXT NOT NULL,
            secret_enc TEXT NOT NULL,
            passphrase_enc TEXT,
            UNIQUE(analyst_id, exchange)
        );

        CREATE TABLE IF NOT EXISTS analyst_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analyst_id INTEGER NOT NULL REFERENCES analyst_profiles(id),
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            trade_type TEXT NOT NULL DEFAULT 'leverage',
            side TEXT NOT NULL,
            entry REAL,
            sl REAL,
            sl_type TEXT NOT NULL DEFAULT 'hard',
            sl_tf TEXT,
            tps_json TEXT,
            tps_hit INTEGER NOT NULL DEFAULT 0,
            dcas_json TEXT,
            size REAL,
            order_id TEXT,
            notes TEXT,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            close_price REAL,
            close_type TEXT,
            close_pct REAL,
            close_notes TEXT,
            status TEXT NOT NULL DEFAULT 'open'
        );

        CREATE TABLE IF NOT EXISTS analyst_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analyst_id INTEGER NOT NULL REFERENCES analyst_profiles(id),
            ts TEXT NOT NULL,
            symbol TEXT NOT NULL,
            trade_type TEXT NOT NULL DEFAULT 'leverage',
            side TEXT NOT NULL,
            entry REAL,
            sl REAL,
            sl_type TEXT NOT NULL DEFAULT 'hard',
            tps_json TEXT,
            dcas_json TEXT,
            exchange TEXT NOT NULL,
            order_id TEXT,
            discord_ok INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS position_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL REFERENCES analyst_positions(id),
            analyst_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            detail_json TEXT
        );
        """)

# ── Analyst profiles ──────────────────────────────────────────────────────────

def create_analyst(username: str, password: str, display_name: str,
                   discord_webhook_url: str, default_exchange: str = "blofin",
                   default_risk_pct: float = 0.01, default_leverage: int = 75) -> int:
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO analyst_profiles (username, password_hash, display_name, "
            "discord_webhook_url, default_exchange, default_risk_pct, default_leverage, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (username, pw_hash, display_name, discord_webhook_url,
             default_exchange, default_risk_pct, default_leverage, ts)
        )
        return cur.lastrowid

def get_analyst_by_username(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM analyst_profiles WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None

def verify_password(analyst: dict, password: str) -> bool:
    return bcrypt.checkpw(password.encode(), analyst["password_hash"].encode())

def get_analyst_by_id(analyst_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM analyst_profiles WHERE id=?", (analyst_id,)).fetchone()
        return dict(row) if row else None

def update_analyst_defaults(analyst_id: int, default_exchange: str,
                             default_risk_pct: float, default_leverage: int):
    with _conn() as c:
        c.execute(
            "UPDATE analyst_profiles SET default_exchange=?, default_risk_pct=?, default_leverage=? WHERE id=?",
            (default_exchange, default_risk_pct, default_leverage, analyst_id)
        )

# ── Exchange credentials ───────────────────────────────────────────────────────

def save_credentials(analyst_id: int, exchange: str,
                     api_key: str, secret: str, passphrase: str = ""):
    key_enc = _encrypt(api_key)
    sec_enc = _encrypt(secret)
    pp_enc = _encrypt(passphrase) if passphrase else ""
    with _conn() as c:
        c.execute(
            "INSERT INTO analyst_credentials (analyst_id, exchange, api_key_enc, secret_enc, passphrase_enc) "
            "VALUES (?,?,?,?,?) ON CONFLICT(analyst_id, exchange) DO UPDATE SET "
            "api_key_enc=excluded.api_key_enc, secret_enc=excluded.secret_enc, passphrase_enc=excluded.passphrase_enc",
            (analyst_id, exchange, key_enc, sec_enc, pp_enc)
        )

def get_credentials(analyst_id: int, exchange: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM analyst_credentials WHERE analyst_id=? AND exchange=?",
            (analyst_id, exchange)
        ).fetchone()
    if not row:
        return None
    return {
        "exchange": row["exchange"],
        "api_key": _decrypt(row["api_key_enc"]),
        "secret": _decrypt(row["secret_enc"]),
        "passphrase": _decrypt(row["passphrase_enc"]) if row["passphrase_enc"] else "",
    }

def get_configured_exchanges(analyst_id: int) -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT exchange FROM analyst_credentials WHERE analyst_id=?", (analyst_id,)
        ).fetchall()
    return [r["exchange"] for r in rows]

def get_credentials_masked(analyst_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT exchange, api_key_enc FROM analyst_credentials WHERE analyst_id=?",
            (analyst_id,)
        ).fetchall()
    result = []
    for row in rows:
        key = _decrypt(row["api_key_enc"])
        result.append({"exchange": row["exchange"], "key_preview": f"****{key[-4:]}" if len(key) > 4 else "****"})
    return result

# ── Positions ─────────────────────────────────────────────────────────────────

def open_position(analyst_id: int, exchange: str, symbol: str, side: str,
                  entry: float, sl: float, tps: list, size: float, order_id: str,
                  trade_type: str = "leverage", sl_type: str = "hard",
                  sl_tf: str = "", dcas: list = None, notes: str = "") -> int:
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO analyst_positions (analyst_id, exchange, symbol, trade_type, side, entry, sl, "
            "sl_type, sl_tf, tps_json, dcas_json, size, order_id, notes, opened_at, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open')",
            (analyst_id, exchange, symbol, trade_type, side, entry, sl,
             sl_type, sl_tf, json.dumps(tps), json.dumps(dcas or []),
             size, order_id, notes, ts)
        )
        return cur.lastrowid

def get_open_positions(analyst_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM analyst_positions WHERE analyst_id=? AND status='open' ORDER BY opened_at DESC",
            (analyst_id,)
        ).fetchall()
    return [_enrich_position(dict(r)) for r in rows]

def get_closed_positions(analyst_id: int, limit: int = 30) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM analyst_positions WHERE analyst_id=? AND status='closed' ORDER BY closed_at DESC LIMIT ?",
            (analyst_id, limit)
        ).fetchall()
    return [_enrich_position(dict(r)) for r in rows]

def get_position(position_id: int, analyst_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM analyst_positions WHERE id=? AND analyst_id=?",
            (position_id, analyst_id)
        ).fetchone()
    return _enrich_position(dict(row)) if row else None

def _enrich_position(d: dict) -> dict:
    d["tps"]  = json.loads(d.get("tps_json")  or "[]")
    d["dcas"] = json.loads(d.get("dcas_json") or "[]")
    return d

def update_position_sl(position_id: int, analyst_id: int, new_sl: float):
    with _conn() as c:
        c.execute("UPDATE analyst_positions SET sl=? WHERE id=? AND analyst_id=?",
                  (new_sl, position_id, analyst_id))

def mark_tp_hit(position_id: int, analyst_id: int, tp_index: int):
    with _conn() as c:
        c.execute("UPDATE analyst_positions SET tps_hit=? WHERE id=? AND analyst_id=?",
                  (tp_index, position_id, analyst_id))

def mark_dca_filled(position_id: int, analyst_id: int, dca_index: int, fill_price: float):
    pos = get_position(position_id, analyst_id)
    if not pos:
        return
    dcas = pos["dcas"]
    if 0 <= dca_index < len(dcas):
        dcas[dca_index]["filled"] = True
        dcas[dca_index]["fill_price"] = fill_price
        # Recalculate weighted average entry
        filled = [d for d in dcas if d.get("filled")]
        if filled:
            total_alloc = sum(d.get("alloc", 0) for d in filled)
            if total_alloc > 0:
                avg = sum(d["fill_price"] * d.get("alloc", 0) for d in filled) / total_alloc
                with _conn() as c:
                    c.execute("UPDATE analyst_positions SET dcas_json=?, entry=? WHERE id=? AND analyst_id=?",
                              (json.dumps(dcas), avg, position_id, analyst_id))
                return
    with _conn() as c:
        c.execute("UPDATE analyst_positions SET dcas_json=? WHERE id=? AND analyst_id=?",
                  (json.dumps(dcas), position_id, analyst_id))

def close_position(position_id: int, analyst_id: int, close_price: float,
                   close_type: str, close_pct: float, close_notes: str = ""):
    ts = datetime.now(timezone.utc).isoformat()
    status = "closed" if close_pct >= 100 else "open"
    with _conn() as c:
        c.execute(
            "UPDATE analyst_positions SET status=?, closed_at=?, close_price=?, "
            "close_type=?, close_pct=?, close_notes=? WHERE id=? AND analyst_id=?",
            (status, ts if status == "closed" else None,
             close_price, close_type, close_pct, close_notes,
             position_id, analyst_id)
        )

def add_position_event(position_id: int, analyst_id: int, event_type: str, detail: dict):
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO position_events (position_id, analyst_id, ts, event_type, detail_json) VALUES (?,?,?,?,?)",
            (position_id, analyst_id, ts, event_type, json.dumps(detail))
        )

def get_position_events(position_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM position_events WHERE position_id=? ORDER BY ts ASC",
            (position_id,)
        ).fetchall()
    return [dict(r) for r in rows]

# ── Signal log ────────────────────────────────────────────────────────────────

def log_signal(analyst_id: int, symbol: str, side: str, entry: float | None,
               sl: float | None, tps: list, exchange: str, order_id: str | None,
               discord_ok: bool, notes: str = "", trade_type: str = "leverage",
               sl_type: str = "hard", dcas: list = None):
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO analyst_signals (analyst_id, ts, symbol, trade_type, side, entry, sl, "
            "sl_type, tps_json, dcas_json, exchange, order_id, discord_ok, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (analyst_id, ts, symbol, trade_type, side, entry, sl, sl_type,
             json.dumps(tps), json.dumps(dcas or []), exchange,
             order_id, 1 if discord_ok else 0, notes)
        )

def get_analyst_signals(analyst_id: int, limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM analyst_signals WHERE analyst_id=? ORDER BY ts DESC LIMIT ?",
            (analyst_id, limit)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["tps"]  = json.loads(d.get("tps_json")  or "[]")
        d["dcas"] = json.loads(d.get("dcas_json") or "[]")
        result.append(d)
    return result
