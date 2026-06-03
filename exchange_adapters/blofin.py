"""
BloFin exchange adapter — uses the blofin SDK directly with per-analyst credentials.
Completely independent of the follower bot's blofin_client.py module.
"""

import sys
from exchange_adapters import ExchangeAdapter

from blofin import BloFinClient
from blofin.utils import send_request


class BloFinAdapter(ExchangeAdapter):
    def __init__(self, credentials: dict):
        """
        credentials: {api_key, secret, passphrase, base_url (optional)}
        base_url defaults to the demo endpoint; pass live URL for live trading.
        """
        self.base_url = credentials.get("base_url", "https://demo-trading-openapi.blofin.com")
        self._patch_url()
        self._client = BloFinClient(
            api_key=credentials["api_key"],
            api_secret=credentials["secret"],
            passphrase=credentials.get("passphrase", ""),
        )
        self._instruments: dict | None = None

    def _patch_url(self):
        """Point every loaded blofin.* module at the configured endpoint."""
        url = self.base_url.rstrip("/")
        for mod_name, mod in list(sys.modules.items()):
            if mod_name.startswith("blofin") and hasattr(mod, "REST_API_URL"):
                setattr(mod, "REST_API_URL", url)

    def _load_instruments(self) -> dict:
        if self._instruments is None:
            try:
                resp = self._client.public.get_instruments()
                data = resp.get("data", []) or []
                self._instruments = {d["instId"]: d for d in data if d.get("instId")}
            except Exception:
                self._instruments = {}
        return self._instruments

    def _inst_id(self, symbol: str) -> str:
        if "-USDT" in symbol:
            return symbol
        return symbol.upper() + "-USDT"

    def get_contract_specs(self, symbol: str) -> dict:
        inst = self._load_instruments().get(self._inst_id(symbol), {})
        return {
            "contract_value": float(inst.get("contractValue", 0) or 0),
            "lot_size": float(inst.get("lotSize", 1) or 1),
            "min_size": float(inst.get("minSize", 0) or 0),
            "max_leverage": float(inst.get("maxLeverage", 100) or 100),
        }

    def get_balance(self) -> float:
        try:
            resp = self._client.account.get_balance(account_type="futures")
            data = resp.get("data", {})
            rows = data if isinstance(data, list) else data.get("details", [])
            for asset in rows:
                if asset.get("currency", "").upper() == "USDT":
                    return float(asset.get("available", 0) or 0)
        except Exception:
            pass
        return 0.0

    def get_market_price(self, symbol: str) -> float:
        try:
            resp = self._client.public.get_tickers(inst_id=self._inst_id(symbol))
            data = resp.get("data", [])
            if isinstance(data, list) and data:
                return float(data[0].get("last", 0) or 0)
        except Exception:
            pass
        return 0.0

    def set_leverage(self, symbol: str, leverage: int) -> int:
        specs = self.get_contract_specs(symbol)
        max_lev = int(specs.get("max_leverage", leverage))
        lev = max(1, min(int(leverage), max_lev))
        data = {"instId": self._inst_id(symbol), "leverage": str(lev), "marginMode": "cross"}
        try:
            send_request("POST", "/api/v1/account/set-leverage",
                         self._client.auth, data=data, authenticate=True)
        except Exception:
            pass
        return lev

    def place_order(self, symbol: str, side: str, size: float,
                    entry: float, sl: float | None, tp: float | None) -> dict:
        position_side = "long" if side.lower() in ("buy", "long") else "short"
        order_side = "buy" if position_side == "long" else "sell"
        params = dict(
            inst_id=self._inst_id(symbol),
            margin_mode="cross",
            position_side=position_side,
            side=order_side,
            order_type="limit",
            price=str(entry),
            size=str(size),
        )
        if tp is not None:
            params["tp_trigger_px"] = str(tp)
        if sl is not None:
            params["sl_trigger_px"] = str(sl)
        resp = self._client.trading.place_order(**params)
        order_id = resp.get("data", {})
        if isinstance(order_id, dict):
            order_id = order_id.get("ordId", "")
        elif isinstance(order_id, list) and order_id:
            order_id = order_id[0].get("ordId", "")
        return {"order_id": str(order_id), "raw": resp}

    def place_market_order(self, symbol: str, side: str, size: float,
                           sl: float | None, tp: float | None) -> dict:
        position_side = "long" if side.lower() in ("buy", "long") else "short"
        order_side = "buy" if position_side == "long" else "sell"
        params = dict(
            inst_id=self._inst_id(symbol),
            margin_mode="cross",
            position_side=position_side,
            side=order_side,
            order_type="market",
            size=str(size),
        )
        if tp is not None:
            params["tp_trigger_px"] = str(tp)
        if sl is not None:
            params["sl_trigger_px"] = str(sl)
        resp = self._client.trading.place_order(**params)
        order_id = resp.get("data", {})
        if isinstance(order_id, dict):
            order_id = order_id.get("ordId", "")
        elif isinstance(order_id, list) and order_id:
            order_id = order_id[0].get("ordId", "")
        return {"order_id": str(order_id), "raw": resp}

    def get_symbols(self) -> list[str]:
        instruments = self._load_instruments()
        return [k for k in instruments if k.endswith("-USDT")]
