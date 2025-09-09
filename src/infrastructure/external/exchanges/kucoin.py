from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from kucoin.client import Market as KuCoinMarketClient
from kucoin.client import Trade as KuCoinTradeClient
from kucoin.client import User as KuCoinUserClient
from loguru import logger

from .exchange_interface import ExchangeAdapterInterface

# Create a FastAPI router instance for this adapter
router = APIRouter()


class KuCoinAdapter(ExchangeAdapterInterface):
    """
    Adapter for interacting with the KuCoin API.
    """

    def __init__(
        self, api_key: str, api_secret: str, api_passphrase: str, testnet: bool = False
    ):
        """
        Initialize the KuCoin adapter.
        """
        try:
            # Use the appropriate URL based on the testnet flag
            base_url = (
                "https://api.kucoin.com"
                if not testnet
                else "https://openapi-sandbox.kucoin.com"
            )

            self.market_client = KuCoinMarketClient(
                api_key, api_secret, api_passphrase, url=base_url
            )
            self.trade_client = KuCoinTradeClient(
                api_key, api_secret, api_passphrase, url=base_url
            )
            self.user_client = KuCoinUserClient(
                api_key, api_secret, api_passphrase, url=base_url
            )
            logger.info("KuCoin Adapter initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize KuCoin Adapter: {e}")
            raise RuntimeError("KuCoin Adapter initialization failed.") from e

    def get_market_price(self, symbol: str) -> float:
        """
        Get the current market price for a symbol.
        """
        try:
            logger.debug(f"Fetching market price for symbol: {symbol}")
            ticker = self.market_client.get_ticker(symbol)
            if ticker is None:
                raise ValueError(f"Could not retrieve ticker for {symbol}")
            price = float(ticker["price"])
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
        Place an order on KuCoin.
        """
        try:
            logger.debug(
                f"Placing {order_type} order for {quantity} {symbol} as {side}."
            )
            if order_type == "market":
                order = self.trade_client.create_market_order(
                    symbol=symbol, side=side, size=str(quantity)
                )
            elif order_type == "limit":
                if price is None:
                    raise ValueError("Price is required for limit orders")
                order = self.trade_client.create_limit_order(
                    symbol=symbol, side=side, price=str(price), size=str(quantity)
                )
            else:
                raise ValueError(f"Unsupported order type: {order_type}")
            logger.info(f"Order placed successfully on KuCoin: {order}")
            if order is None:
                raise RuntimeError("Received None as order response from KuCoin API.")
            return order
        except Exception as e:
            logger.error(f"Error placing {side} order for {symbol}: {e}")
            raise RuntimeError(f"Failed to place {side} order for {symbol}.") from e

    def get_balance(self) -> dict:
        """
        Retrieve the account balance.
        """
        try:
            logger.debug("Fetching account balance from KuCoin.")
            accounts = self.user_client.get_account_list()
            if accounts is None:
                raise RuntimeError("Could not retrieve account list")
            balance = {
                acc["currency"]: acc["balance"]
                for acc in accounts
                if acc["type"] == "trade"
            }
            logger.info("Account balance retrieved successfully.")
            return balance
        except Exception as e:
            logger.error(f"Error retrieving account balance from KuCoin: {e}")
            raise RuntimeError("Failed to fetch account balance.") from e

    def get_open_orders(self) -> list:
        """
        Retrieve a list of open orders.
        """
        try:
            logger.debug("Fetching open orders from KuCoin.")
            open_orders = self.trade_client.get_order_list()
            if open_orders is None:
                raise RuntimeError("Could not retrieve open orders")
            logger.info(f"Open orders retrieved successfully: {open_orders['items']}")
            return open_orders["items"]
        except Exception as e:
            logger.error(f"Error retrieving open orders from KuCoin: {e}")
            raise RuntimeError("Failed to fetch open orders.") from e


# API Endpoints using the router and KuCoinAdapter


def get_kucoin_adapter(
    api_key: str = "YOUR_API_KEY",  # Replace with your actual API key
    api_secret: str = "YOUR_API_SECRET",  # Replace with your actual API secret
    api_passphrase: str = "YOUR_API_PASSPHRASE",  # Replace with your actual API passphrase
):
    return KuCoinAdapter(api_key, api_secret, api_passphrase)


@router.get("/market_price/{symbol}")
async def get_kucoin_market_price(
    symbol: str, kucoin_adapter: KuCoinAdapter = Depends(get_kucoin_adapter)
):
    """
    Endpoint to get market price from KuCoin.
    """
    try:
        price = kucoin_adapter.get_market_price(symbol)
        return {"symbol": symbol, "price": price, "exchange": "KuCoin"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"KuCoin API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.post("/order")
async def place_kucoin_order(
    symbol: str,
    side: Literal["buy", "sell"],
    quantity: float,
    order_type: Literal["market", "limit"] = "market",
    price: Optional[float] = None,
    kucoin_adapter: KuCoinAdapter = Depends(get_kucoin_adapter),
):
    """
    Endpoint to place an order on KuCoin.
    """
    try:
        order_details = kucoin_adapter.place_order(
            symbol, side, quantity, order_type, price
        )
        return {"order_details": order_details, "exchange": "KuCoin"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"KuCoin API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/balance")
async def get_kucoin_balance(
    kucoin_adapter: KuCoinAdapter = Depends(get_kucoin_adapter),
):
    """
    Endpoint to get account balance from KuCoin.
    """
    try:
        balance = kucoin_adapter.get_balance()
        return {"balance_info": balance, "exchange": "KuCoin"}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"KuCoin API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/open_orders")
async def get_kucoin_open_orders(
    kucoin_adapter: KuCoinAdapter = Depends(get_kucoin_adapter),
):
    """
    Endpoint to get open orders from KuCoin.
    """
    try:
        open_orders = kucoin_adapter.get_open_orders()
        return {"open_orders": open_orders, "exchange": "KuCoin"}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"KuCoin API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
