from typing import Literal, Optional

import krakenex
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from .exchange_interface import ExchangeAdapterInterface

# Create a FastAPI router instance for this adapter
router = APIRouter()


class KrakenAdapter(ExchangeAdapterInterface):
    """
    Adapter for interacting with the Kraken API.
    """

    def __init__(self, api_key: str, api_secret: str):
        """
        Initialize the Kraken adapter.
        """
        try:
            self.client = krakenex.API(api_key, api_secret)
            logger.info("Kraken Adapter initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Kraken Adapter: {e}")
            raise RuntimeError("Kraken Adapter initialization failed.") from e

    def get_market_price(self, symbol: str) -> float:
        """
        Get the current market price for a symbol.
        """
        try:
            logger.debug(f"Fetching market price for symbol: {symbol}")
            response = self.client.query_public("Ticker", {"pair": symbol})
            self._handle_api_error(response)

            price = float(response["result"][symbol]["c"])
            logger.info(f"Market price for {symbol}: {price}")
            return price
        except Exception as e:
            logger.error(f"Error fetching market price for {symbol}: {e}")
            raise RuntimeError(f"Failed to fetch market price for {symbol}.") from e

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> dict:
        """
        Place an order on Kraken.
        """
        try:
            logger.debug(
                f"Placing {side} order for {quantity} {symbol} as {order_type}."
            )
            order_data = {
                "pair": symbol,
                "type": side,
                "ordertype": order_type,
                "volume": quantity,
            }
            if price:
                order_data["price"] = str(price)  # Add price for limit orders

            order = self.client.query_private("AddOrder", order_data)
            self._handle_api_error(order)

            logger.info(f"Order placed successfully on Kraken: {order['result']}")
            return order["result"]
        except Exception as e:
            logger.error(f"Error placing {side} order on Kraken for {symbol}: {e}")
            raise RuntimeError(f"Failed to place {side} order for {symbol}.") from e

    def get_balance(self) -> dict:
        """
        Retrieve the account balance.
        """
        try:
            logger.debug("Fetching account balance from Kraken.")
            balance = self.client.query_private("Balance")
            self._handle_api_error(balance)

            logger.info("Account balance retrieved successfully.")
            return balance["result"]
        except Exception as e:
            logger.error(f"Error retrieving account balance from Kraken: {e}")
            raise RuntimeError("Failed to fetch account balance.") from e

    def get_open_orders(self) -> list:
        """
        Retrieve a list of open orders.
        """
        try:
            logger.debug("Fetching open orders from Kraken.")
            open_orders = self.client.query_private("OpenOrders")
            self._handle_api_error(open_orders)

            logger.info(
                f"Open orders retrieved successfully: {open_orders['result']['open']}"
            )
            return open_orders["result"]["open"]
        except Exception as e:
            logger.error(f"Error retrieving open orders from Kraken: {e}")
            raise RuntimeError("Failed to fetch open orders.") from e

    @staticmethod
    def _handle_api_error(response: dict) -> None:
        """
        Handle potential API errors from Kraken's responses.
        """
        if response.get("error"):
            error_message = "; ".join(response["error"])
            logger.error(f"Kraken API error: {error_message}")
            raise ValueError(f"Kraken API error: {error_message}")


# API Endpoints using the router and KrakenAdapter


def get_kraken_adapter(
    api_key: str = "YOUR_API_KEY", api_secret: str = "YOUR_API_SECRET"
):
    return KrakenAdapter(api_key, api_secret)


@router.get("/market_price/{symbol}")
async def get_kraken_market_price(
    symbol: str, kraken_adapter: KrakenAdapter = Depends(get_kraken_adapter)
):
    """
    Endpoint to get market price from Kraken.
    """
    try:
        price = kraken_adapter.get_market_price(symbol)
        return {"symbol": symbol, "price": price, "exchange": "Kraken"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Kraken API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.post("/order")
async def place_kraken_order(
    symbol: str,
    side: Literal["buy", "sell"],
    quantity: float,
    order_type: Literal["market", "limit"] = "market",
    price: Optional[float] = None,
    kraken_adapter: KrakenAdapter = Depends(get_kraken_adapter),
):
    """
    Endpoint to place an order on Kraken.
    """
    try:
        order_details = kraken_adapter.place_order(
            symbol, side, quantity, order_type, price
        )
        return {"order_details": order_details, "exchange": "Kraken"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Kraken API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/balance")
async def get_kraken_balance(
    kraken_adapter: KrakenAdapter = Depends(get_kraken_adapter),
):
    """
    Endpoint to get account balance from Kraken.
    """
    try:
        balance = kraken_adapter.get_balance()
        return {"balance_info": balance, "exchange": "Kraken"}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Kraken API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/open_orders")
async def get_kraken_open_orders(
    kraken_adapter: KrakenAdapter = Depends(get_kraken_adapter),
):
    """
    Endpoint to get open orders from Kraken.
    """
    try:
        open_orders = kraken_adapter.get_open_orders()
        return {"open_orders": open_orders, "exchange": "Kraken"}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Kraken API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
