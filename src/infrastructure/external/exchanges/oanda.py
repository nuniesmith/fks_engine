from typing import Literal, Optional

import oandapyV20
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.pricing as pricing
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from .exchange_interface import ExchangeAdapterInterface

# Create a FastAPI router instance for this adapter
router = APIRouter()


class OandaAdapter(ExchangeAdapterInterface):
    """
    Adapter for interacting with the OANDA API.
    """

    def __init__(self, api_key: str, account_id: str, environment: str = "practice"):
        """
        Initialize the OANDA adapter.
        """
        try:
            self.account_id = account_id
            api_url = (
                "https://api-fxpractice.oanda.com/v3"
                if environment == "practice"
                else "https://api-fxtrade.oanda.com/v3"
            )
            self.client = oandapyV20.API(access_token=api_key, environment=api_url)
            logger.info(
                f"OANDA Adapter initialized for account {account_id} in {environment} environment."
            )
        except Exception as e:
            logger.error(f"Error initializing OANDA Adapter: {e}")
            raise RuntimeError("Failed to initialize OANDA Adapter.") from e

    def get_market_price(self, symbol: str) -> float:
        """
        Get the current market price for a symbol.
        """
        try:
            logger.debug(f"Fetching market price for symbol: {symbol}")
            params = {"instruments": symbol}
            r = pricing.PricingInfo(accountID=self.account_id, params=params)
            response = self.client.request(r)
            response_dict = dict(response)
            prices = response_dict.get(
                "prices",
            )
            if not prices:
                raise ValueError(f"No prices returned for symbol {symbol}.")
            price = float(prices["bids"]["price"])
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
        Place an order on OANDA.
        """
        try:
            logger.debug(
                f"Placing {order_type} {side} order for {quantity} units of {symbol}."
            )
            order_data = {
                "order": {
                    "instrument": symbol,
                    "units": str(quantity if side.lower() == "buy" else -quantity),
                    "type": "MARKET" if order_type.lower() == "market" else "LIMIT",
                    "positionFill": "DEFAULT",
                }
            }
            if order_type == "limit":
                if price is None:
                    raise ValueError("Price is required for limit orders")
                order_data["order"]["price"] = str(price)
            r = orders.OrderCreate(accountID=self.account_id, data=order_data)
            response = self.client.request(r)
            logger.info(f"Order placed successfully: {response}")
            return dict(response)
        except Exception as e:
            logger.error(f"Error placing {side} order on OANDA for {symbol}: {e}")
            raise RuntimeError(
                f"Failed to place {side} order on OANDA for {symbol}."
            ) from e

    def get_balance(self) -> dict:
        """
        Retrieve the account balance.
        """
        try:
            logger.debug("Fetching account balance from OANDA.")
            r = accounts.AccountDetails(accountID=self.account_id)
            response = self.client.request(r)
            response_dict = dict(response)
            balance = response_dict.get("account", {}).get("balance")
            if balance is None:
                raise ValueError("Failed to retrieve balance from OANDA.")
            balance_info = {"balance": float(balance)}
            logger.info(f"Account balance retrieved successfully: {balance_info}")
            return balance_info
        except Exception as e:
            logger.error(f"Error retrieving account balance from OANDA: {e}")
            raise RuntimeError("Failed to retrieve account balance from OANDA.") from e

    def get_open_orders(self) -> list:
        """
        Retrieve a list of open orders.
        """
        try:
            logger.debug("Fetching open orders from OANDA.")
            r = orders.OrderList(accountID=self.account_id)
            response = self.client.request(r)
            response_dict = dict(response)
            open_orders = response_dict.get("orders", [])
            logger.info(
                f"Open orders retrieved successfully: {len(open_orders)} orders."
            )
            return open_orders if open_orders is not None else []
        except Exception as e:
            logger.error(f"Error retrieving open orders from OANDA: {e}")
            raise RuntimeError("Failed to retrieve open orders from OANDA.") from e


# API Endpoints using the router and OandaAdapter


def get_oanda_adapter(
    api_key: str = "YOUR_API_KEY",  # Replace with your actual API key
    account_id: str = "YOUR_ACCOUNT_ID",  # Replace with your actual account ID
    environment: str = "practice",
):
    return OandaAdapter(api_key, account_id, environment)


@router.get("/market_price/{symbol}")
async def get_oanda_market_price(
    symbol: str, oanda_adapter: OandaAdapter = Depends(get_oanda_adapter)
):
    """
    Endpoint to get market price from OANDA.
    """
    try:
        price = oanda_adapter.get_market_price(symbol)
        return {"symbol": symbol, "price": price, "exchange": "OANDA"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"OANDA API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.post("/order")
async def place_oanda_order(
    symbol: str,
    side: Literal["buy", "sell"],
    quantity: float,
    order_type: Literal["market", "limit"] = "market",
    price: Optional[float] = None,
    oanda_adapter: OandaAdapter = Depends(get_oanda_adapter),
):
    """
    Endpoint to place an order on OANDA.
    """
    try:
        order_details = oanda_adapter.place_order(
            symbol, side, quantity, order_type, price
        )
        return {"order_details": order_details, "exchange": "OANDA"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"OANDA API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/balance")
async def get_oanda_balance(oanda_adapter: OandaAdapter = Depends(get_oanda_adapter)):
    """
    Endpoint to get account balance from OANDA.
    """
    try:
        balance = oanda_adapter.get_balance()
        return {"balance_info": balance, "exchange": "OANDA"}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"OANDA API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/open_orders")
async def get_oanda_open_orders(
    oanda_adapter: OandaAdapter = Depends(get_oanda_adapter),
):
    """
    Endpoint to get open orders from OANDA.
    """
    try:
        open_orders = oanda_adapter.get_open_orders()
        return {"open_orders": open_orders, "exchange": "OANDA"}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"OANDA API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
