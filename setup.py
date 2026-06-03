"""
setup.py — CLI admin tool for the Analyst App.

Usage:
  python setup.py init          # create DB tables + generate ANALYST_CRED_KEY
  python setup.py add-analyst   # add a new analyst account
"""

import sys
import os
import secrets
from getpass import getpass
from cryptography.fernet import Fernet
from dotenv import load_dotenv, set_key

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH)


def cmd_init():
    # Generate SECRET_KEY if missing
    env_text = ""
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            env_text = f.read()

    if "ANALYST_CRED_KEY=" not in env_text or not os.environ.get("ANALYST_CRED_KEY"):
        key = Fernet.generate_key().decode()
        set_key(ENV_PATH, "ANALYST_CRED_KEY", key)
        print(f"Generated ANALYST_CRED_KEY and saved to .env")
    else:
        print("ANALYST_CRED_KEY already set.")

    if "SECRET_KEY=" not in env_text or not os.environ.get("SECRET_KEY"):
        sk = secrets.token_hex(32)
        set_key(ENV_PATH, "SECRET_KEY", sk)
        print(f"Generated SECRET_KEY and saved to .env")
    else:
        print("SECRET_KEY already set.")

    # Re-load so analyst_db can use the key
    load_dotenv(ENV_PATH, override=True)

    import analyst_db as db
    db.init_db()
    print("Database tables created (or already exist).")
    print("\nSetup complete. Run: python app.py")


def cmd_add_analyst():
    load_dotenv(ENV_PATH, override=True)
    if not os.environ.get("ANALYST_CRED_KEY"):
        print("ERROR: Run 'python setup.py init' first.")
        sys.exit(1)

    import analyst_db as db
    db.init_db()

    print("\n=== Add Analyst Account ===")
    username = input("Username (login): ").strip()
    if not username:
        print("Username required.")
        sys.exit(1)

    password = getpass("Password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    display_name = input("Display name (must match Discord name for follower bot): ").strip()
    webhook_url = input("Discord channel webhook URL: ").strip()
    default_exchange = input("Default exchange [blofin/mexc/bybit] (default: blofin): ").strip() or "blofin"
    risk_pct_str = input("Default risk % per trade (e.g. 1 for 1%, default 1): ").strip() or "1"
    leverage_str = input("Default leverage (default 75): ").strip() or "75"

    try:
        risk_pct = float(risk_pct_str) / 100
        leverage = int(leverage_str)
    except ValueError:
        print("Invalid risk% or leverage value.")
        sys.exit(1)

    try:
        analyst_id = db.create_analyst(
            username=username,
            password=password,
            display_name=display_name,
            discord_webhook_url=webhook_url,
            default_exchange=default_exchange,
            default_risk_pct=risk_pct,
            default_leverage=leverage,
        )
        print(f"\nAnalyst created (id={analyst_id}): {display_name} / @{username}")
        print("They can now log in at http://localhost:5051 and add their exchange keys in Settings.")
    except Exception as e:
        print(f"Error creating analyst: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "init":
        cmd_init()
    elif cmd == "add-analyst":
        cmd_add_analyst()
    else:
        print("Usage:")
        print("  python setup.py init          # first-time setup")
        print("  python setup.py add-analyst   # add a new analyst")
        sys.exit(1)
