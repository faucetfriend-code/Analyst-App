from abc import ABC, abstractmethod


class ExchangeAdapter(ABC):
    @abstractmethod
    def place_order(self, symbol: str, side: str, size: float,
                    entry: float, sl: float | None, tp: float | None) -> dict:
        """Place a limit order. Returns {order_id}."""

    @abstractmethod
    def place_market_order(self, symbol: str, side: str, size: float,
                           sl: float | None, tp: float | None) -> dict:
        """Place a market order. Returns {order_id}."""

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> int:
        """Set leverage, return the leverage actually applied."""

    @abstractmethod
    def get_balance(self) -> float:
        """Return available USDT balance."""

    @abstractmethod
    def get_market_price(self, symbol: str) -> float:
        """Return latest price for symbol."""

    @abstractmethod
    def get_contract_specs(self, symbol: str) -> dict:
        """Return {contract_value, lot_size, min_size}."""

    @abstractmethod
    def get_symbols(self) -> list[str]:
        """Return list of tradeable USDT-perp symbols, e.g. ['BTC-USDT', ...]."""


def get_adapter(exchange: str, credentials: dict) -> "ExchangeAdapter":
    """Factory — returns the right adapter for the given exchange name."""
    exchange = exchange.lower()
    if exchange == "blofin":
        from exchange_adapters.blofin import BloFinAdapter
        return BloFinAdapter(credentials)
    if exchange == "mexc":
        from exchange_adapters.mexc import MexcAdapter
        return MexcAdapter(credentials)
    if exchange == "bybit":
        from exchange_adapters.bybit import BybitAdapter
        return BybitAdapter(credentials)
    raise ValueError(f"Unknown exchange: {exchange}")
