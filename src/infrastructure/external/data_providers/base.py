import time
from typing import Any, Dict, List, Optional, Union

import pandas as pd
import requests
from framework.middleware.metrics import MetricType, PrometheusMetrics
from loguru import logger


class BaseClient:
    """
    Base client class that provides common functionality for all API clients.
    """

    def __init__(self, name: str, metrics: Optional[Any] = None):
        """Initialize the base client with common properties."""
        self.name = name
        # Create an instance of PrometheusMetrics if metrics is not provided
        self.metrics = metrics or PrometheusMetrics()

    def _make_request(
        self,
        url: str,
        params: Dict[str, Any],
        timeout: int = 30,
        max_retries: int = 3,
        endpoint: str = "unknown",
    ) -> Optional[Dict[str, Any]]:
        """
        Make an API request with retry logic and metric recording.

        Args:
            url: The API endpoint URL
            params: Request parameters
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            endpoint: Name of the endpoint for metrics recording

        Returns:
            Response JSON data if successful, None otherwise
        """
        start_time = time.time()
        success = False

        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, timeout=timeout)

                # Check for rate limiting
                if response.status_code == 429:
                    wait_time = (
                        int(response.headers.get("Retry-After", 5)) or 2**attempt
                    )
                    logger.warning(
                        f"⏳ Rate limit reached on attempt {attempt+1}/{max_retries}. Waiting {wait_time}s..."
                    )

                    # Record rate limit event
                    self.metrics.record_rate_limit(
                        client_name=self.name,
                        remaining=0,
                        limit=int(response.headers.get("X-RateLimit-Limit", 0)),
                    )

                    self.metrics.record_retry(client_name=self.name)
                    time.sleep(wait_time)
                    continue

                # Record the API call result
                api_call_duration = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    logger.error(
                        f"❌ API error: {response.status_code} - {response.text}"
                    )
                    # Record failed API call
                    self.metrics.record_api_call(
                        client_name=self.name,
                        endpoint=endpoint,
                        success=False,
                        duration_ms=api_call_duration,
                    )
                    return None

                response.raise_for_status()

                # Record successful API call
                self.metrics.record_api_call(
                    client_name=self.name,
                    endpoint=endpoint,
                    success=True,
                    duration_ms=api_call_duration,
                )

                success = True
                return response.json()

            except requests.exceptions.RequestException as e:
                wait_time = 2**attempt
                logger.error(
                    f"🚨 Request error on attempt {attempt+1}/{max_retries}: {e}. Retrying in {wait_time}s...",
                    exc_info=True,
                )

                # Record retry
                self.metrics.record_retry(client_name=self.name)

                time.sleep(wait_time)

        # Record failed API call after all retries
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_api_call(
            client_name=self.name,
            endpoint=endpoint,
            success=False,
            duration_ms=duration_ms,
        )

        return None

    def record_operation_duration(
        self,
        operation_name: str,
        symbol: str,
        timeframe: str,
        duration: float,
        update_type: str = "data_fetch",
    ) -> None:
        """Record the duration of an operation using metrics."""
        try:
            self.metrics.record_custom_metric(
                name="data_update_duration",
                metric_type=MetricType.HISTOGRAM,
                value=duration,
                asset=symbol,
                timeframe=str(timeframe),
                update_stage=operation_name,
                update_type=update_type,
            )
        except Exception as e:
            logger.error(f"Metrics error while recording duration: {e}")

    def get_health_status(self) -> bool:
        """
        Base health check method to be overridden by subclasses.
        """
        logger.warning(f"Health check not implemented for {self.name}")
        return True

    def _process_data(self, data: Any) -> pd.DataFrame:
        """
        Convert API response data to pandas DataFrame.
        To be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement _process_data method")

    def get(self, symbol: str, timeframe: str, **kwargs) -> Optional[pd.DataFrame]:
        """
        Generic method to fetch data for a symbol and timeframe.
        To be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement get method")
