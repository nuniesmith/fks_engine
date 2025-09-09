from abc import ABC, abstractmethod
from typing import Optional


class ExchangeAdapterInterface(ABC):
    """
    Interface for interacting with different exchange APIs.
    """

    @abstractmethod
    def get_market_price(self, symbol: str) -> float:
        """
        Get the current market price of a symbol.

        Args:
            symbol: The trading symbol.

        Returns:
            The latest market price.
        """
        pass  # Implementation will be provided by concrete adapters

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> dict:
        """
        Place an order on the exchange.

        Args:
            symbol: The trading symbol.
            side: 'buy' or 'sell'.
            quantity: Order quantity.
            order_type: Order type (default: 'market').
            price: Price for limit orders (optional).

        Returns:
            Details of the placed order.
        """
        pass  # Implementation will be provided by concrete adapters

    @abstractmethod
    def get_balance(
        self, symbol: str = "BTCUSDT"
    ) -> dict:  # Added symbol for consistency and potential use
        """
        Retrieve account balance information.

        Returns:
            Account balance details.
        """
        pass  # Implementation will be provided by concrete adapters

    @abstractmethod
    def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """
        Retrieve a list of open orders.

        Returns:
            List of open orders.
        """
        pass  # Implementation will be provided by concrete adapters
