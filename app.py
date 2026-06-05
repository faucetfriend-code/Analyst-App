import os
import functools
from flask import (Flask, render_template, request, session,
                   redirect, url_for, jsonify, abort, after_this_request)
from dotenv import load_dotenv

import analyst_db as db
from trade_executor import execute_and_post
from exchange_adapters import get_adapter

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")

# CORS for the Chrome extension (chrome-extension://* origins)
@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "")
    if origin.startswith("chrome-extension://") or origin.startswith("moz-extension://"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/api/<path:p>", methods=["OPTIONS"])
def options_handler(p):
    return "", 204

db.init_db()

EXCHANGE_LABELS = {
    "blofin": "BloFin",
    "mexc": "MEXC",
    "bybit": "Bybit",
}


# ── Auth helpers ──────────────────────────────────────────────────────────────

def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "analyst_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Not authenticated"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def current_analyst() -> dict:
    return db.get_analyst_by_id(session["analyst_id"])


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        analyst = db.get_analyst_by_username(username)
        if analyst and db.verify_password(analyst, password):
            session["analyst_id"] = analyst["id"]
            session["display_name"] = analyst["display_name"]
            return redirect(url_for("trader"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Main trader page ──────────────────────────────────────────────────────────

@app.route("/mobile")
@login_required
def mobile():
    analyst = current_analyst()
    exchanges = db.get_configured_exchanges(analyst["id"])
    exchange_labels = {k: EXCHANGE_LABELS.get(k, k.title()) for k in exchanges}
    return render_template("mobile.html",
                           analyst=analyst,
                           exchanges=exchanges,
                           exchange_labels=exchange_labels)


@app.route("/")
@login_required
def trader():
    analyst = current_analyst()
    exchanges = db.get_configured_exchanges(analyst["id"])
    exchange_labels = {k: EXCHANGE_LABELS.get(k, k.title()) for k in exchanges}
    return render_template("trader.html",
                           analyst=analyst,
                           exchanges=exchanges,
                           exchange_labels=exchange_labels)


# ── Settings page ─────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET"])
@login_required
def settings():
    analyst = current_analyst()
    configured = db.get_credentials_masked(analyst["id"])
    configured_map = {c["exchange"]: c["key_preview"] for c in configured}
    return render_template("settings.html",
                           analyst=analyst,
                           configured=configured_map,
                           all_exchanges=list(EXCHANGE_LABELS.keys()))


@app.route("/api/settings/credentials", methods=["POST"])
@login_required
def save_credentials():
    data = request.get_json(force=True) or {}
    exchange = data.get("exchange", "").lower()
    api_key = data.get("api_key", "").strip()
    secret = data.get("secret", "").strip()
    passphrase = data.get("passphrase", "").strip()

    if exchange not in EXCHANGE_LABELS:
        return jsonify({"ok": False, "error": "Unknown exchange"}), 400
    if not api_key or not secret:
        return jsonify({"ok": False, "error": "API key and secret are required"}), 400

    db.save_credentials(session["analyst_id"], exchange, api_key, secret, passphrase)
    return jsonify({"ok": True})


@app.route("/api/settings/defaults", methods=["POST"])
@login_required
def save_defaults():
    data = request.get_json(force=True) or {}
    try:
        db.update_analyst_defaults(
            session["analyst_id"],
            data.get("default_exchange", "blofin"),
            float(data.get("default_risk_pct", 0.01)),
            int(data.get("default_leverage", 75)),
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Trade execution ───────────────────────────────────────────────────────────

@app.route("/api/fire", methods=["POST"])
@login_required
def fire():
    ticket = request.get_json(force=True) or {}
    ticket["dry_run"] = ticket.get("dry_run", False)
    result = execute_and_post(session["analyst_id"], ticket)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


# ── Market data proxies ───────────────────────────────────────────────────────

@app.route("/api/price/<symbol>")
@login_required
def get_price(symbol):
    exchange = request.args.get("exchange", current_analyst()["default_exchange"])
    creds = db.get_credentials(session["analyst_id"], exchange)
    if not creds:
        return jsonify({"price": None, "error": "No credentials for this exchange"}), 200
    try:
        adapter = get_adapter(exchange, creds)
        price = adapter.get_market_price(symbol)
        return jsonify({"price": price})
    except Exception as e:
        return jsonify({"price": None, "error": str(e)}), 200


@app.route("/api/symbols/<exchange>")
@login_required
def get_symbols(exchange):
    creds = db.get_credentials(session["analyst_id"], exchange.lower())
    if not creds:
        return jsonify([])
    try:
        adapter = get_adapter(exchange.lower(), creds)
        symbols = sorted(adapter.get_symbols())
        return jsonify(symbols)
    except Exception:
        return jsonify([])


# ── Positions & history ───────────────────────────────────────────────────────

@app.route("/api/positions")
@login_required
def get_positions():
    positions = db.get_open_positions(session["analyst_id"])
    return jsonify(positions)


@app.route("/api/positions/closed")
@login_required
def get_closed_positions():
    limit = int(request.args.get("limit", 30))
    positions = db.get_closed_positions(session["analyst_id"], limit=limit)
    return jsonify(positions)


@app.route("/api/positions/<int:pos_id>")
@login_required
def get_position(pos_id):
    pos = db.get_position(pos_id, session["analyst_id"])
    if not pos:
        return jsonify({"ok": False, "error": "Not found"}), 404
    pos["events"] = db.get_position_events(pos_id)
    return jsonify(pos)


@app.route("/api/positions/<int:pos_id>/tp_hit", methods=["POST"])
@login_required
def tp_hit(pos_id):
    data = request.get_json(force=True) or {}
    tp_index = int(data.get("tp_index", 1)) - 1   # 1-based from UI → 0-based in DB
    trim_pct  = float(data.get("trim_pct", 100))
    price     = data.get("price")

    pos = db.get_position(pos_id, session["analyst_id"])
    if not pos:
        return jsonify({"ok": False, "error": "Not found"}), 404

    db.mark_tp_hit(pos_id, session["analyst_id"], tp_index + 1)
    detail = {"tp_num": tp_index + 1, "trim_pct": trim_pct}
    if price:
        detail["price"] = float(price)
    db.add_position_event(pos_id, session["analyst_id"], "tp_hit", detail)

    # Post update to Discord
    analyst = current_analyst()
    if analyst.get("discord_webhook_url"):
        from discord_poster import format_trade_update, post_to_discord
        msg = format_trade_update(pos["symbol"], pos["side"], "tp_hit", detail)
        post_to_discord(analyst["discord_webhook_url"], msg)

    return jsonify({"ok": True})


@app.route("/api/positions/<int:pos_id>/move_sl", methods=["POST"])
@login_required
def move_sl(pos_id):
    data = request.get_json(force=True) or {}
    new_sl = data.get("new_sl")
    be     = data.get("be", False)        # True = move to breakeven (entry price)

    pos = db.get_position(pos_id, session["analyst_id"])
    if not pos:
        return jsonify({"ok": False, "error": "Not found"}), 404

    if be:
        new_sl = pos["entry"]
        event_type = "sl_be"
        detail = {}
    else:
        if new_sl is None:
            return jsonify({"ok": False, "error": "new_sl required"}), 400
        new_sl = float(new_sl)
        event_type = "move_sl"
        detail = {"new_sl": new_sl}

    db.update_position_sl(pos_id, session["analyst_id"], new_sl)
    db.add_position_event(pos_id, session["analyst_id"], event_type, detail)

    analyst = current_analyst()
    if analyst.get("discord_webhook_url"):
        from discord_poster import format_trade_update, post_to_discord
        msg = format_trade_update(pos["symbol"], pos["side"], event_type, detail)
        post_to_discord(analyst["discord_webhook_url"], msg)

    return jsonify({"ok": True, "new_sl": new_sl})


@app.route("/api/positions/<int:pos_id>/dca_filled", methods=["POST"])
@login_required
def dca_filled(pos_id):
    data = request.get_json(force=True) or {}
    dca_index = int(data.get("dca_index", 1)) - 1   # 1-based → 0-based
    fill_price = float(data.get("fill_price", 0))

    pos = db.get_position(pos_id, session["analyst_id"])
    if not pos:
        return jsonify({"ok": False, "error": "Not found"}), 404

    db.mark_dca_filled(pos_id, session["analyst_id"], dca_index, fill_price)
    pos_updated = db.get_position(pos_id, session["analyst_id"])
    detail = {"dca_num": dca_index + 1, "price": fill_price,
              "new_avg": pos_updated.get("entry")}
    db.add_position_event(pos_id, session["analyst_id"], "dca_filled", detail)

    analyst = current_analyst()
    if analyst.get("discord_webhook_url"):
        from discord_poster import format_trade_update, post_to_discord
        msg = format_trade_update(pos["symbol"], pos["side"], "dca_filled", detail)
        post_to_discord(analyst["discord_webhook_url"], msg)

    return jsonify({"ok": True, "new_avg_entry": pos_updated.get("entry")})


@app.route("/api/positions/<int:pos_id>/close", methods=["POST"])
@login_required
def close_position(pos_id):
    data = request.get_json(force=True) or {}
    close_price = data.get("close_price")
    close_type  = data.get("close_type", "profit")
    close_pct   = float(data.get("close_pct", 100))
    close_notes = data.get("notes", "")

    VALID_CLOSE_TYPES = {"profit","stopped","cut","be","invalidation","partial"}
    if close_type not in VALID_CLOSE_TYPES:
        return jsonify({"ok": False, "error": f"close_type must be one of {VALID_CLOSE_TYPES}"}), 400

    pos = db.get_position(pos_id, session["analyst_id"])
    if not pos:
        return jsonify({"ok": False, "error": "Not found"}), 404

    # Resolve CMP
    if close_price in (None, "", "cmp"):
        try:
            exchange = pos["exchange"]
            creds = db.get_credentials(session["analyst_id"], exchange)
            adapter = get_adapter(exchange, creds)
            close_price = adapter.get_market_price(pos["symbol"])
        except Exception as e:
            return jsonify({"ok": False, "error": f"Could not fetch CMP: {e}"}), 400
    else:
        close_price = float(close_price)

    db.close_position(pos_id, session["analyst_id"],
                      close_price, close_type, close_pct, close_notes)
    detail = {"price": close_price, "close_type": close_type,
              "pct": close_pct, "notes": close_notes}
    db.add_position_event(pos_id, session["analyst_id"], "close", detail)

    analyst = current_analyst()
    if analyst.get("discord_webhook_url"):
        from discord_poster import format_trade_update, post_to_discord
        msg = format_trade_update(pos["symbol"], pos["side"], "close", detail)
        post_to_discord(analyst["discord_webhook_url"], msg)

    return jsonify({"ok": True, "close_price": close_price})


@app.route("/api/positions/<int:pos_id>/edit_close", methods=["POST"])
@login_required
def edit_close(pos_id):
    """Edit a closed position's close details (for Past Trades view)."""
    data = request.get_json(force=True) or {}
    pos = db.get_position(pos_id, session["analyst_id"])
    if not pos:
        return jsonify({"ok": False, "error": "Not found"}), 404

    close_price = float(data.get("close_price", pos.get("close_price") or 0))
    close_type  = data.get("close_type", pos.get("close_type", "profit"))
    close_notes = data.get("notes", pos.get("close_notes", ""))

    import sqlite3, os
    with sqlite3.connect(os.path.join(os.path.dirname(__file__), "analyst.db")) as c:
        c.execute(
            "UPDATE analyst_positions SET close_price=?, close_type=?, close_notes=? WHERE id=? AND analyst_id=?",
            (close_price, close_type, close_notes, pos_id, session["analyst_id"])
        )
    return jsonify({"ok": True})


@app.route("/api/signals")
@login_required
def get_signals():
    signals = db.get_analyst_signals(session["analyst_id"], limit=20)
    return jsonify(signals)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5051))
    app.run(host="0.0.0.0", port=port, debug=False)
