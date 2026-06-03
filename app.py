import os
import functools
from flask import (Flask, render_template, request, session,
                   redirect, url_for, jsonify, abort)
from dotenv import load_dotenv

import analyst_db as db
from trade_executor import execute_and_post
from exchange_adapters import get_adapter

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")

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


@app.route("/api/signals")
@login_required
def get_signals():
    signals = db.get_analyst_signals(session["analyst_id"], limit=20)
    return jsonify(signals)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5051))
    app.run(host="0.0.0.0", port=port, debug=False)
