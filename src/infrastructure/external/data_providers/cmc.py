import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from infrastructure.external.data_providers.clients.base import BaseClient
from loguru import logger
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential


class CoinMarketCapClient(BaseClient):
    """
    A client class for interacting with the CoinMarketCap API (real-time quotes).
    """

    BASE_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    LISTINGS_LATEST_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"  # For health check

    QUOTE_KEY = "quote"
    USD_KEY = "USD"
    PRICE_KEY = "price"
    VOLUME_24H_KEY = "volume_24h"
    MARKET_CAP_KEY = "market_cap"
    LAST_UPDATED_KEY = "last_updated"
    SYMBOL_KEY = "symbol"
    DATA_KEY = "data"

    def __init__(self, api_key: Optional[str] = None, metrics: Optional[Any] = None):
        """
        Initialize the CoinMarketCap client.
        """
        super().__init__(name="CoinMarketCapClient", metrics=metrics)
        self.cmc_api_key = api_key or os.getenv("CMC_API_KEY")

        if not self.cmc_api_key:
            raise ValueError(
                "❌ CoinMarketCap API key is required. Set CMC_API_KEY in environment variables."
            )

        self.rate_limited = False  # Track if we hit the rate limit

        # Initialize a requests session for HTTP requests
        import requests

        self._session = requests.Session()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        reraise=True,
    )
    def fetch_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch real-time cryptocurrency data from CoinMarketCap API.

        Args:
            symbol (str): The cryptocurrency symbol (e.g., "BTC").

        Returns:
            Optional[pd.DataFrame]: DataFrame with real-time price, volume, market cap,
                                     or None if data fetching fails after retries.
        """
        if not isinstance(symbol, str) or not symbol.isalpha():
            logger.error(f"❌ Invalid symbol format: {symbol}")
            return None

        symbol = symbol.upper()
        logger.info(f"📡 Fetching CoinMarketCap data for {symbol}")

        params = {"symbol": symbol, "convert": "USD"}
        headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": self.cmc_api_key}

        start_time = time.time()  # Record the start time for metrics

        # Use custom request for CoinMarketCap with headers
        try:
            response = self._make_custom_request(
                url=self.BASE_URL,
                params=params,
                headers=headers,
                timeout=60,
                endpoint=f"fetch_data_{symbol}",
            )

            if (
                not response
                or self.DATA_KEY not in response
                or symbol not in response[self.DATA_KEY]
            ):
                logger.warning(
                    f"⚠️ No data found for {symbol} in CoinMarketCap response."
                )
                return None

            df = self._process_data(response[self.DATA_KEY][symbol])

            duration = time.time() - start_time
            self.record_operation_duration(
                operation_name="fetch_data",
                symbol=symbol,
                timeframe="realtime",
                duration=duration,
                update_type="coinmarketcap",
            )

            return df

        except Exception as e:
            logger.error(f"🚨 API error fetching CoinMarketCap data ({symbol}): {e}")
            raise

    def _make_custom_request(
        self,
        url: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
        timeout: int = 30,
        endpoint: str = "unknown",
    ) -> Optional[Dict[str, Any]]:
        """Custom request method for CoinMarketCap API that requires headers."""
        start_time = time.time()

        try:
            response = self._session.get(
                url, params=params, headers=headers, timeout=timeout
            )

            # Record the API call duration
            api_call_duration = (time.time() - start_time) * 1000

            if response.status_code == 429:
                logger.warning(f"⏳ Rate limit reached. Waiting...")
                self.metrics.record_rate_limit(
                    client_name=self.name,
                    remaining=0,
                    limit=int(response.headers.get("X-RateLimit-Limit", 0)),
                )
                return None

            # Record the API call result
            self.metrics.record_api_call(
                client_name=self.name,
                endpoint=endpoint,
                success=(response.status_code == 200),
                duration_ms=api_call_duration,
            )

            if response.status_code != 200:
                logger.error(f"❌ API error: {response.status_code} - {response.text}")
                return None

            return response.json()

        except Exception as e:
            # Record failed API call
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_api_call(
                client_name=self.name,
                endpoint=endpoint,
                success=False,
                duration_ms=duration_ms,
            )
            logger.error(f"🚨 Request error: {e}")
            return None

    def _process_data(self, data: dict) -> pd.DataFrame:
        """
        Convert API response to a standardized pandas DataFrame.
        """
        quote = data.get(self.QUOTE_KEY, {}).get(self.USD_KEY, {})
        if not quote:
            logger.error(
                f"❌ Missing USD quote data in response. Data: {data.get(self.QUOTE_KEY, {})}"
            )
            return pd.DataFrame()

        df = pd.DataFrame(
            [
                {
                    "Timestamp": pd.to_datetime(
                        quote.get(self.LAST_UPDATED_KEY), errors="coerce"
                    ),
                    "Symbol": data.get(self.SYMBOL_KEY),
                    "Price": pd.to_numeric(quote.get(self.PRICE_KEY), errors="coerce"),
                    "Volume": pd.to_numeric(
                        quote.get(self.VOLUME_24H_KEY), errors="coerce"
                    ),
                    "MarketCap": pd.to_numeric(
                        quote.get(self.MARKET_CAP_KEY), errors="coerce"
                    ),
                }
            ]
        )
        df.set_index("Timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    def get_latest_listings(
        self, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch latest cryptocurrency listings from CoinMarketCap API.
        Used for health checks.
        """
        headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": self.cmc_api_key}
        return self._make_custom_request(
            url=self.LISTINGS_LATEST_URL,
            params=params or {},
            headers=headers,
            timeout=30,
            endpoint="get_latest_listings",
        )

    def get_health_status(self) -> bool:
        """
        Check health of the CoinMarketCap API.
        """
        listings = self.get_latest_listings({"limit": 1})
        health_status = listings is not None and "data" in listings

        # Record health check result
        self.metrics.record_health_check(client_name=self.name, success=health_status)
        self.metrics.record_client_availability(
            client_name=self.name, available=health_status
        )

        return health_status

    def get(self, symbol: str, **kwargs) -> Optional[pd.DataFrame]:
        """
        Standardized get method to match the BaseClient interface.
        """
        return self.fetch_data(symbol)


def update_missing_data(
    csv_path: str, cmc_client: CoinMarketCapClient, symbol: str
) -> None:
    """
    Ensures no missing data by fetching sequential updates.

    Args:
        csv_path (str): Path to the CSV file where data is stored.
        cmc_client (CoinMarketCapClient): CMC API client.
        symbol (str): The asset symbol.
    """
    from pathlib import Path

    file_path = Path(csv_path)

    if file_path.exists():
        try:
            df = pd.read_csv(file_path, parse_dates=["Timestamp"])
            df.sort_values("Timestamp", inplace=True)
        except Exception as e:
            logger.error(f"Error reading CSV file at {file_path}: {e}")
            df = pd.DataFrame(columns=["Price", "Volume", "MarketCap", "Timestamp"])
        last_recorded_time = df["Timestamp"].iloc[-1] if not df.empty else None
        if last_recorded_time:
            last_recorded_timestamp = int(last_recorded_time.timestamp())
            logger.info(
                f"🕒 Last recorded timestamp for {symbol}: {last_recorded_time}"
            )
        else:
            last_recorded_timestamp = int(time.time()) - 86400
            logger.warning(
                f"⚠️ No records found in CSV for {symbol}. Starting from 24 hours ago."
            )
    else:
        logger.warning(f"⚠️ No CSV found for {symbol}. Fetching fresh data.")
        df = pd.DataFrame(columns=["Price", "Volume", "MarketCap", "Timestamp"])
        last_recorded_timestamp = int(time.time()) - 86400

    current_timestamp = int(time.time())

    if last_recorded_timestamp < current_timestamp - 60:
        logger.info(
            f"🔍 Fetching missing data from {last_recorded_timestamp} to {current_timestamp}."
        )
        new_data = cmc_client.fetch_data(symbol)
        if new_data is not None and not new_data.empty:
            df = (
                pd.concat([df, new_data])
                .drop_duplicates(subset=["Timestamp"])
                .reset_index(drop=True)
            )
            df.to_csv(file_path, index=False)
            logger.info(
                f"✅ Updated {symbol} data saved to {csv_path}. Total records: {len(df)}"
            )
        else:
            logger.warning(
                f"⚠️ No new data available for {symbol} from {last_recorded_timestamp} to {current_timestamp}."
            )
    else:
        logger.info(f"✅ No missing data for {symbol}. Data is up to date.")


# ==========================
# FastAPI Router Integration
# ==========================

router = APIRouter(prefix="/cmc", tags=["CoinMarketCapClient"])

# Global CoinMarketCap client instance
cmc_client = CoinMarketCapClient()


# Pydantic models for endpoints
class SymbolPayload(BaseModel):
    symbol: str


class UpdateMissingPayload(BaseModel):
    csv_path: str
    symbol: str


@router.get("/health", summary="Check CoinMarketCap API health")
def cmc_health():
    """
    Endpoint to check the health of the CoinMarketCap API using the latest listings.
    """
    is_healthy = cmc_client.get_health_status()
    if not is_healthy:
        raise HTTPException(
            status_code=503, detail="CoinMarketCap API health check failed."
        )
    return {"status": "CoinMarketCap API is healthy."}


@router.get("/data", summary="Fetch real-time cryptocurrency data from CoinMarketCap")
def fetch_cmc_data(
    symbol: str = Query(..., description="Cryptocurrency symbol (e.g., BTC)")
):
    """
    Endpoint to fetch real-time cryptocurrency data for a given symbol.
    """
    df = cmc_client.fetch_data(symbol)
    if df is None or df.empty:
        raise HTTPException(
            status_code=404, detail=f"No data found for symbol {symbol}."
        )
    # Convert DataFrame to JSON using record orientation
    data = df.reset_index().to_dict(orient="records")
    return {"symbol": symbol.upper(), "data": data}


@router.post("/update_missing", summary="Update missing data for a symbol")
def update_missing_endpoint(payload: UpdateMissingPayload):
    """
    Endpoint to update missing data by fetching sequential updates.
    Expects a CSV file path and a symbol.
    """
    try:
        update_missing_data(payload.csv_path, cmc_client, payload.symbol)
        return {"status": f"Missing data for {payload.symbol} updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
