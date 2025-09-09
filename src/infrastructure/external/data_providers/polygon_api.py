import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from infrastructure.external.data_providers.clients.base import BaseClient
from loguru import logger
from pydantic import BaseModel


class PolygonClient(BaseClient):
    """
    A client class for interacting with the Polygon.io API to fetch OHLC data,
    with support for pagination and multi-day backfills, and a custom throttle
    of 5 requests/minute.
    """

    BASE_URL = "https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{multiplier}/{interval}/{start}/{end}"
    EXCHANGES_URL = "https://api.polygon.io/v3/reference/exchanges"  # Health check
    TIMEFRAME_MAP: Dict[str, Tuple[int, str]] = {
        "1m": (1, "minute"),
        "5m": (5, "minute"),
        "15m": (15, "minute"),
        "30m": (30, "minute"),
        "1h": (1, "hour"),
        "1d": (1, "day"),
        "1w": (1, "week"),
        "1mo": (1, "month"),
    }
    RESULTS_KEY = "results"
    NEXT_URL_KEY = "next_url"
    OPEN_KEY = "o"
    HIGH_KEY = "h"
    LOW_KEY = "l"
    CLOSE_KEY = "c"
    VOLUME_KEY = "v"
    TIMESTAMP_KEY = "t"
    COLUMN_OPEN = "Open"
    COLUMN_HIGH = "High"
    COLUMN_LOW = "Low"
    COLUMN_CLOSE = "Close"
    COLUMN_VOLUME = "Volume"
    COLUMN_TIMESTAMP = "Timestamp"

    def __init__(
        self, api_key: Optional[str] = None, metrics: Optional[Any] = None
    ) -> None:
        """
        Initialize the Polygon.io client.
        """
        super().__init__(name="PolygonClient", metrics=metrics)
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")

        if not self.api_key:
            raise ValueError(
                "❌ Polygon API key is required. Set POLYGON_API_KEY in environment variables."
            )

        # Custom throttling: maximum 5 requests per 60 seconds.
        self._requests_made = 0
        self._window_start = time.time()
        self._MAX_REQUESTS_PER_WINDOW = 5
        self._WINDOW_DURATION = 60.0  # seconds

    def get(
        self,
        symbol: str,
        timeframe: str,
        start_timestamp: int,
        end_timestamp: int,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[pd.DataFrame]:
        """
        High-level method to fetch OHLCV data for a given symbol and timeframe.
        """
        symbol = symbol.upper()
        return self.fetch_data(symbol, timeframe, start_timestamp, end_timestamp)

    def fetch_data(
        self,
        symbol: str,
        timeframe: str,
        start_timestamp: int,
        end_timestamp: int,
        max_retries: int = 3,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data from Polygon.io in chunks and concatenate them.
        """
        if timeframe not in self.TIMEFRAME_MAP:
            logger.error(
                f"❌ Invalid timeframe: {timeframe}. Supported: {list(self.TIMEFRAME_MAP.keys())}"
            )
            return None
        if not isinstance(start_timestamp, int) or not isinstance(end_timestamp, int):
            logger.error(
                f"❌ start_timestamp and end_timestamp must be integers. Got: {start_timestamp}, {end_timestamp}"
            )
            return None

        symbol = symbol.upper()
        multiplier, interval = self.TIMEFRAME_MAP[timeframe]
        start_ms = start_timestamp * 1000  # Convert seconds to milliseconds
        end_ms = end_timestamp * 1000

        url = self.BASE_URL.format(
            symbol=symbol,
            multiplier=multiplier,
            interval=interval,
            start=start_ms,
            end=end_ms,
        )
        query_params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": self.api_key,
        }

        all_results: List[Dict[str, Union[int, float]]] = []
        next_url = url

        overall_start_time = time.time()

        while next_url:
            page_data = self._fetch_single_page(next_url, query_params, max_retries)
            if page_data is None:
                break

            batch = page_data.get(self.RESULTS_KEY, [])
            all_results.extend(batch)
            next_url = page_data.get(self.NEXT_URL_KEY)

        if not all_results:
            logger.warning(f"⚠️ No data returned for {symbol} - {timeframe}.")
            return None

        df = self._process_data(all_results)
        duration = time.time() - overall_start_time
        logger.info(
            f"✅ Fetched data for {symbol} [{timeframe}] in {duration:.2f} seconds."
        )

        # Record operation duration
        self.record_operation_duration(
            operation_name="fetch_data",
            symbol=symbol,
            timeframe=timeframe,
            duration=duration,
            update_type="polygon",
        )

        return df

    def _fetch_single_page(
        self, url: str, params: Dict[str, Any], max_retries: int
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch a single page from Polygon, enforcing throttling and retries.
        """
        now = time.time()
        if (now - self._window_start) >= self._WINDOW_DURATION:
            self._requests_made = 0
            self._window_start = now

        for attempt in range(max_retries):
            self._throttle()

            # Use base class method to make the request with custom endpoint name
            endpoint = f"fetch_page_{attempt}"
            data = self._make_request(
                url=url,
                params=params,
                timeout=60,
                max_retries=1,  # We handle retries here
                endpoint=endpoint,
            )

            if data:
                return data

            # If we got rate limited, wait before retrying
            wait_time = 2**attempt
            logger.warning(f"⏳ Request failed, retrying in {wait_time}s...")
            time.sleep(wait_time)

        logger.error(f"❌ Gave up on {url} after {max_retries} retries.")
        return None

    def _throttle(self) -> None:
        """
        Enforce a maximum of 5 requests per 60 seconds.
        """
        now = time.time()
        if (now - self._window_start) < self._WINDOW_DURATION:
            if self._requests_made >= self._MAX_REQUESTS_PER_WINDOW:
                wait_secs = self._WINDOW_DURATION - (now - self._window_start)
                if wait_secs > 0:
                    logger.warning(
                        f"🔒 Throttling: {self._requests_made} requests in current window. Waiting {wait_secs:.2f}s..."
                    )
                    time.sleep(wait_secs)
                    self._requests_made = 0
                    self._window_start = time.time()
        else:
            self._requests_made = 0
            self._window_start = now

    def _process_data(self, data: list) -> pd.DataFrame:
        """
        Convert a list of bar dictionaries into a standardized pandas DataFrame.
        """
        if not isinstance(data, list) or not data:
            logger.warning("⚠️ No valid OHLC data found in response.")
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df.rename(
            columns={
                self.OPEN_KEY: self.COLUMN_OPEN,
                self.HIGH_KEY: self.COLUMN_HIGH,
                self.LOW_KEY: self.COLUMN_LOW,
                self.CLOSE_KEY: self.COLUMN_CLOSE,
                self.VOLUME_KEY: self.COLUMN_VOLUME,
                self.TIMESTAMP_KEY: self.COLUMN_TIMESTAMP,
            },
            inplace=True,
        )

        df[self.COLUMN_TIMESTAMP] = pd.to_datetime(
            df[self.COLUMN_TIMESTAMP], unit="ms", utc=True
        )
        df.set_index(self.COLUMN_TIMESTAMP, inplace=True)
        df.sort_index(inplace=True)
        return df

    def get_exchanges(self) -> Optional[Dict[str, Any]]:
        """
        Fetch exchanges list from Polygon API.
        Used for health checks.
        """
        query_params = {"apiKey": self.api_key}

        # Use base class to make the request
        return self._make_request(
            url=self.EXCHANGES_URL,
            params=query_params,
            timeout=30,
            endpoint="get_exchanges",
        )

    def get_health_status(self) -> bool:
        """
        Check the health of the Polygon API using the exchanges endpoint.
        """
        exchanges = self.get_exchanges()
        health_status = (
            exchanges is not None
            and "results" in exchanges
            and isinstance(exchanges["results"], list)
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

router = APIRouter(prefix="/polygon", tags=["PolygonClient"])

# Global Polygon client instance
polygon_client = PolygonClient()


# Pydantic models for endpoints
class FetchDataPayload(BaseModel):
    symbol: str
    timeframe: str
    start: int  # Unix timestamp in seconds
    end: int  # Unix timestamp in seconds


@router.get("/exchanges", summary="Get Polygon exchanges info")
def get_exchanges():
    """
    Endpoint to fetch exchanges info from Polygon API.
    """
    exchanges = polygon_client.get_exchanges()
    if exchanges is None:
        raise HTTPException(
            status_code=503, detail="Unable to retrieve exchanges info from Polygon."
        )
    return {"exchanges": exchanges}


@router.post("/data", summary="Fetch OHLCV data from Polygon")
def fetch_polygon_data(payload: FetchDataPayload):
    """
    Endpoint to fetch OHLCV data for a given symbol, timeframe, start, and end timestamps.
    """
    df = polygon_client.get(
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        start_timestamp=payload.start,
        end_timestamp=payload.end,
    )
    if df is None or df.empty:
        raise HTTPException(
            status_code=404, detail="No data found or API error occurred."
        )
    # Convert DataFrame to JSON using record orientation
    data = df.reset_index().to_dict(orient="records")
    return {
        "symbol": payload.symbol.upper(),
        "timeframe": payload.timeframe,
        "data": data,
    }
