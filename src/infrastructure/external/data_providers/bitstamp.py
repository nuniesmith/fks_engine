import time
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from fastapi import APIRouter, HTTPException, Query
from infrastructure.external.data_providers.clients.base import BaseClient
from loguru import logger


class BitstampClient(BaseClient):
    """
    A client class for fetching OHLCV data from Bitstamp API.
    """

    BASE_URL = "https://www.bitstamp.net/api/v2/ohlc"
    TRADING_PAIRS_URL = "https://www.bitstamp.net/api/v2/trading-pairs-info/"
    REQUIRED_COLUMNS = {"Open", "High", "Low", "Close", "Volume", "Timestamp"}
    MAX_CANDLES_PER_REQUEST = 1000  # Bitstamp allows max 1000 candles per request
    log_prefix = "[BitstampClient]"

    def __init__(self, metrics: Optional[Any] = None):
        """Initialize the Bitstamp client."""
        super().__init__(name="BitstampClient", metrics=metrics)

    def fetch_data(
        self,
        symbol: str,
        start_timestamp: int,
        end_timestamp: int,
        timeframe: int = 60,
        max_retries: int = 3,
        limit: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data from Bitstamp API in chunks.
        """
        log_prefix = f"{self.log_prefix} - fetch_data"
        symbol = symbol.lower()
        url = f"{self.BASE_URL}/{symbol}/"
        data_frames = []
        current_start = start_timestamp
        timeframe = int(timeframe)
        total_fetched_candles = 0

        overall_start_time = time.time()

        for attempt in range(max_retries):
            while current_start < end_timestamp:
                current_end = min(
                    current_start + (self.MAX_CANDLES_PER_REQUEST * timeframe),
                    end_timestamp,
                )
                api_start_timestamp = int(current_start)
                api_end_timestamp = int(current_end)
                params = {
                    "start": api_start_timestamp,
                    "end": api_end_timestamp,
                    "step": timeframe,
                    "limit": self.MAX_CANDLES_PER_REQUEST,
                }
                logger.debug(f"{log_prefix} API request params: {params}")

                # Use base class method to make the request
                endpoint = f"fetch_data_{timeframe}"
                json_data = self._make_request(
                    url=url,
                    params=params,
                    timeout=60,
                    max_retries=1,  # We're already handling retries in the outer loop
                    endpoint=endpoint,
                )

                if not json_data:
                    time.sleep(2**attempt)
                    continue

                batch_data = json_data.get("data", {}).get("ohlc", [])
                if not batch_data:
                    logger.warning(f"⚠️ No further data found (start={current_start}).")
                    break

                batch_df = self._process_data(batch_data)
                if not batch_df.empty:
                    data_frames.append(batch_df)
                    num_candles = len(batch_df)
                    total_fetched_candles += num_candles
                    last_timestamp = batch_df.index[-1]
                    current_start = (
                        int(pd.Timestamp(last_timestamp).timestamp()) + timeframe
                    )
                    logger.debug(
                        f"Fetched {num_candles} candles; total: {total_fetched_candles}, new start: {current_start}"
                    )
                    if limit and total_fetched_candles >= limit:
                        logger.info(f"ℹ️ Candle limit of {limit} reached.")
                        break
                else:
                    logger.warning("⚠️ Batch returned empty DataFrame.")

                if current_start < end_timestamp:
                    time.sleep(2)
                if limit and total_fetched_candles >= limit:
                    break

            if (
                data_frames
                or current_start >= end_timestamp
                or (limit and total_fetched_candles >= limit)
            ):
                break

        if data_frames:
            final_df = pd.concat(data_frames).drop_duplicates().sort_index()
            duration = time.time() - overall_start_time
            logger.info(
                f"✅ Fetched {len(final_df)} rows for {symbol} [{timeframe}s] in {duration:.2f} seconds."
            )

            # Record operation duration
            self.record_operation_duration(
                operation_name="fetch_data",
                symbol=symbol,
                timeframe=str(timeframe),
                duration=duration,
                update_type="ohlcv",
            )

            return final_df

        logger.error(
            f"❌ Failed to fetch any data for {symbol} after {max_retries} retries."
        )
        return None

    def _process_data(self, data: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Convert JSON 'ohlc' batch into a standardized pandas DataFrame.
        """
        processed_data = []
        for record in data:
            logger.debug(f"API Record in _process_data: {record}")
            try:
                processed_record = {
                    "Open": pd.to_numeric([record.get("open")], errors="coerce")[0],
                    "High": pd.to_numeric([record.get("high")], errors="coerce")[0],
                    "Low": pd.to_numeric([record.get("low")], errors="coerce")[0],
                    "Close": pd.to_numeric([record.get("close")], errors="coerce")[0],
                    "Volume": pd.to_numeric([record.get("volume")], errors="coerce")[0],
                    "Timestamp": pd.to_datetime(
                        int(record["timestamp"]), unit="s", utc=True
                    ),
                }
                processed_data.append(processed_record)
            except KeyError as e:
                logger.error(f"🚨 Missing key in record: {record}. KeyError: {e}")
                continue
        df = pd.DataFrame(processed_data)
        if not df.empty:
            nan_counts = df.isnull().sum().sum()
            if nan_counts > 0:
                logger.info(f"ℹ️ Converted {nan_counts} missing values to NaN.")
            df = df[["Open", "High", "Low", "Close", "Volume", "Timestamp"]]
            df.set_index("Timestamp", inplace=True)
            df.sort_index(inplace=True)
        return df

    def get(
        self,
        symbol: str,
        timeframe: int = 60,
        params: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Public method to fetch OHLCV data for a symbol.
        """
        now = int(time.time())
        start_timestamp = (
            int(params.get("start", now - 86400)) if params else now - 86400
        )
        end_timestamp = int(params.get("end", now)) if params else now
        return self.fetch_data(
            symbol,
            start_timestamp,
            end_timestamp,
            timeframe=int(timeframe),
            limit=limit,
        )

    def get_markets(self) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch trading pairs info from Bitstamp API (used for health checks).
        """
        # Use base class method to make the request
        data = self._make_request(
            url=self.TRADING_PAIRS_URL, params={}, timeout=30, endpoint="get_markets"
        )

        # Record health and availability
        is_healthy = data is not None and isinstance(data, list) and len(data) > 0
        self.metrics.record_health_check(client_name=self.name, success=is_healthy)
        self.metrics.record_client_availability(
            client_name=self.name, available=is_healthy
        )

        if not isinstance(data, list):
            return None
        return data

    def get_health_status(self) -> bool:
        """
        Check the health of the Bitstamp API using the trading pairs info.
        """
        markets = self.get_markets()
        return markets is not None and isinstance(markets, list) and len(markets) > 0


# ==========================
# FastAPI Router Integration
# ==========================

router = APIRouter(prefix="/bitstamp", tags=["BitstampClient"])

# Create a global instance of BitstampClient
bitstamp_client = BitstampClient()


@router.get("/markets", summary="Get Bitstamp trading pairs info")
def get_markets():
    """
    Endpoint to fetch trading pairs info from Bitstamp API.
    """
    markets = bitstamp_client.get_markets()
    if markets is None:
        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve trading pairs info from Bitstamp.",
        )
    return {"markets": markets}


@router.get("/data", summary="Fetch OHLCV data from Bitstamp")
def fetch_data(
    symbol: str = Query(..., description="Asset symbol (e.g., btcusd)"),
    timeframe: int = Query(
        60, description="Timeframe in seconds (e.g., 60 for 1 minute)"
    ),
    start: Optional[int] = Query(None, description="Start timestamp (Unix epoch)"),
    end: Optional[int] = Query(None, description="End timestamp (Unix epoch)"),
    limit: Optional[int] = Query(
        None, description="Maximum number of candles to fetch"
    ),
):
    """
    Endpoint to fetch OHLCV data for a given asset symbol and timeframe.
    """
    # Default to past 24 hours if not provided
    now = int(time.time())
    params = {
        "start": start if start is not None else now - 86400,
        "end": end if end is not None else now,
    }
    df = bitstamp_client.get(symbol, timeframe=timeframe, params=params, limit=limit)
    if df is None or df.empty:
        raise HTTPException(
            status_code=404, detail="No data found or API error occurred."
        )
    # Convert DataFrame to JSON using record orientation
    data = df.reset_index().to_dict(orient="records")
    return {"symbol": symbol.upper(), "timeframe": timeframe, "data": data}
