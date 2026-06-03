"""Bybit USDT linear perpetuals via ccxt."""

import ccxt
from exchange_adapters import ExchangeAdapter


class BybitAdapter(ExchangeAdapter):
    def __init__(self, credentials: dict):
        self._ex = ccxt.bybit({
            "apiKey": credentials["api_key"],
            "secret": credentials["secret"],
            "options": {"defaultType": "linear"},
        })

    def _sym(self, symbol: str) -> str:
        # ccxt Bybit uses "BTC/USDT:USDT" for linear perps
        base = symbol.replace("-USDT", "").replace("/USDT", "").upper()
        return f"{base}/USDT:USDT"

    def get_balance(self) -> float:
        try:
            bal = self._ex.fetch_balance({"type": "linear"})
            return float(bal.get("USDT", {}).get("free", 0) or 0)
        except Exception:
            return 0.0

    def get_market_price(self, symbol: str) -> float:
        try:
            ticker = self._ex.fetch_ticker(self._sym(symbol))
            return float(ticker.get("last", 0) or 0)
        except Exception:
            return 0.0

    def get_contract_specs(self, symbol: str) -> dict:
        try:
            self._ex.load_markets()
            market = self._ex.market(self._sym(symbol))
            return {
                "contract_value": float(market.get("contractSize", 1) or 1),
                "lot_size": float(market["precision"].get("amount", 0.001) or 0.001),
                "min_size": float(market["limits"]["amount"].get("min", 0.001) or 0.001),
                "max_leverage": 100.0,
            }
        except Exception:
            return {"contract_value": 1.0, "lot_size": 0.001, "min_size": 0.001, "max_leverage": 100.0}

    def set_leverage(self, symbol: str, leverage: int) -> int:
        try:
            self._ex.set_leverage(leverage, self._sym(symbol), {"marginMode": "cross"})
        except Exception:
            pass
        return leverage

    def place_order(self, symbol: str, side: str, size: float,
                    entry: float, sl: float | None, tp: float | None) -> dict:
        order_side = "buy" if side.lower() in ("buy", "long") else "sell"
        params: dict = {"positionIdx": 1 if order_side == "buy" else 2}
        if sl is not None:
            params["stopLoss"] = {"triggerPrice": str(sl)}
        if tp is not None:
            params["takeProfit"] = {"triggerPrice": str(tp)}
        try:
            resp = self._ex.create_limit_order(self._sym(symbol), order_side, size, entry, params)
            return {"order_id": str(resp.get("id", "")), "raw": resp}
        except Exception as e:
            return {"order_id": "", "error": str(e)}

    def place_market_order(self, symbol: str, side: str, size: float,
                           sl: float | None, tp: float | None) -> dict:
        order_side = "buy" if side.lower() in ("buy", "long") else "sell"
        params: dict = {"positionIdx": 1 if order_side == "buy" else 2}
        if sl is not None:
            params["stopLoss"] = {"triggerPrice": str(sl)}
        if tp is not None:
            params["takeProfit"] = {"triggerPrice": str(tp)}
        try:
            resp = self._ex.create_market_order(self._sym(symbol), order_side, size, params=params)
            return {"order_id": str(resp.get("id", "")), "raw": resp}
        except Exception as e:
            return {"order_id": "", "error": str(e)}

    def get_symbols(self) -> list[str]:
        try:
            self._ex.load_markets()
            return [
                k.split("/")[0] + "-USDT"
                for k, m in self._ex.markets.items()
                if m.get("type") == "swap" and m.get("quote") == "USDT"
                and m.get("settle") == "USDT" and m.get("active")
            ]
        except Exception:
            return []
