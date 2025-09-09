import os
import time
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from infrastructure.external.data_providers.clients.base import BaseClient
from loguru import logger


class AlphaVantageClient(BaseClient):
    """
    A client class for interacting with the Alpha Vantage API.
    """

    BASE_URL = "https://www.alphavantage.co/query"
    SYMBOL_SEARCH_FUNCTION = "SYMBOL_SEARCH"  # For health check
    FUNCTION_MAP = {
        "1m": "TIME_SERIES_INTRADAY",
        "5m": "TIME_SERIES_INTRADAY",
        "15m": "TIME_SERIES_INTRADAY",
        "30m": "TIME_SERIES_INTRADAY",
        "1h": "TIME_SERIES_INTRADAY",
        "4h": "TIME_SERIES_INTRADAY",
        "1d": "TIME_SERIES_DAILY",
        "1w": "TIME_SERIES_WEEKLY",
        "1mo": "TIME_SERIES_MONTHLY",
    }
    OPEN_COL = "1. open"
    HIGH_COL = "2. high"
    LOW_COL = "3. low"
    CLOSE_COL = "4. close"
    VOLUME_COL = "5. volume"

    def __init__(self, api_key: Optional[str] = None, metrics: Optional[Any] = None):
        """
        Initialize the AlphaVantageClient.
        """
        super().__init__(name="AlphaVantageClient", metrics=metrics)
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")

        if not self.api_key:
            raise ValueError(
                "❌ Alpha Vantage API key is required. Set ALPHA_VANTAGE_API_KEY in environment variables."
            )

        self.rate_limited = False  # Track if we hit the rate limit

    def fetch_data(self, symbol: str, timeframe: str = "1d") -> Optional[pd.DataFrame]:
        """
        Fetch OHLC data from Alpha Vantage API.
        """
        if timeframe not in self.FUNCTION_MAP:
            logger.error(
                f"❌ Invalid timeframe: '{timeframe}'. Supported timeframes are: {list(self.FUNCTION_MAP.keys())}"
            )
            return None

        if self.rate_limited:
            logger.warning(
                f"⚠️ API rate limit exceeded. Skipping {symbol} - {timeframe}."
            )
            return None

        logger.info(f"📡 Fetching Alpha Vantage data for {symbol} - {timeframe}")
        function = self.FUNCTION_MAP.get(timeframe, "TIME_SERIES_DAILY")
        params = {
            "function": function,
            "symbol": symbol,
            "apikey": self.api_key,
        }
        if function == "TIME_SERIES_INTRADAY":
            params["interval"] = timeframe

        start_time = time.time()  # Record start time for metrics

        # Use base class method to make the request
        endpoint = f"fetch_data_{timeframe}"
        data = self._make_request(
            url=self.BASE_URL,
            params=params,
            timeout=30,
            max_retries=3,
            endpoint=endpoint,
        )

        if not data:
            return None

        # Check for Rate Limit Response
        if "Information" in data and "rate limit" in data["Information"].lower():
            logger.warning(f"⚠️ Rate limit exceeded. Setting rate_limited flag.")
            self.rate_limited = True
            self.metrics.record_rate_limit(
                client_name=self.name, remaining=0, limit=5
            )  # Assuming default limit
            return None

        if "Error Message" in data:
            logger.error(f"❌ API Error for {symbol}: {data}")
            return None

        df = self._process_data(data)

        # Record operation duration
        duration = time.time() - start_time
        self.record_operation_duration(
            operation_name="fetch_data",
            symbol=symbol,
            timeframe=timeframe,
            duration=duration,
            update_type="alpha_vantage",
        )

        return df

    def _process_data(self, data: dict) -> Optional[pd.DataFrame]:
        """
        Process Alpha Vantage response into a Pandas DataFrame.
        """
        key = next((k for k in data.keys() if "Time Series" in k), None)
        if not key:
            logger.warning(
                f"⚠️ No market data key found in response. Keys: {list(data.keys())}."
            )
            return None

        df = pd.DataFrame(data[key]).T
        df.index = pd.to_datetime(df.index)
        df = df.rename(
            columns={
                self.OPEN_COL: "Open",
                self.HIGH_COL: "High",
                self.LOW_COL: "Low",
                self.CLOSE_COL: "Close",
                self.VOLUME_COL: "Volume",
            }
        )

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        required_columns = {"Open", "High", "Low", "Close", "Volume"}
        if not required_columns.issubset(df.columns):
            logger.error(f"⚠️ Missing required columns in API response: {df.columns}")
            return None

        df.index.name = "Timestamp"
        df.sort_index(inplace=True)
        return df

    def get(
        self, symbol: str, timeframe: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[pd.DataFrame]:
        """
        Public method to fetch OHLCV data.
        """
        return self.fetch_data(symbol, timeframe=timeframe)

    def get_health_status(self) -> bool:
        """
        Check the health of the Alpha Vantage API using the SYMBOL_SEARCH endpoint.
        """
        params = {
            "function": self.SYMBOL_SEARCH_FUNCTION,
            "keywords": "AAPL",
            "apikey": self.api_key,
        }

        data = self._make_request(
            url=self.BASE_URL, params=params, timeout=30, endpoint="health_check"
        )

        health_status = (
            data is not None
            and "bestMatches" in data
            and isinstance(data["bestMatches"], list)
        )

        # Record health check result
        self.metrics.record_health_check(client_name=self.name, success=health_status)
        self.metrics.record_client_availability(
            client_name=self.name, available=health_status
        )

        return health_status


# ==========================
# FastAPI Router Integration
# ==========================

router = APIRouter(prefix="/alpha", tags=["AlphaVantageClient"])

# Create a global instance of the client
alpha_client = AlphaVantageClient()


@router.get("/health", summary="Check Alpha Vantage API health")
def health_check():
    """
    Endpoint to perform a health check on the Alpha Vantage API.
    """
    is_healthy = alpha_client.get_health_status()
    if not is_healthy:
        raise HTTPException(status_code=503, detail="Alpha Vantage API is not healthy.")
    return {"status": "Alpha Vantage API is healthy."}


@router.get("/data", summary="Fetch OHLCV data from Alpha Vantage")
def fetch_data(
    symbol: str = Query(..., description="Asset symbol (e.g., AAPL, BTCUSD)"),
    timeframe: str = Query("1d", description="Timeframe (e.g., 1m, 5m, 1d, 1w, 1mo)"),
):
    """
    Endpoint to fetch OHLCV data for a given asset symbol and timeframe.
    """
    df = alpha_client.fetch_data(symbol, timeframe=timeframe)
    if df is None:
        raise HTTPException(
            status_code=404, detail="No data found or API error occurred."
        )
    # Convert DataFrame to JSON (using records orientation for simplicity)
    data = df.reset_index().to_dict(orient="records")
    return {"symbol": symbol.upper(), "timeframe": timeframe, "data": data}
