import asyncio
import os
import threading
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from loguru import logger

# Load environment variables
load_dotenv()

# Import API clients
from infrastructure.external.data_providers.clients.base import BaseClient

from .alpha import AlphaVantageClient
from .bitstamp import BitstampClient
from .cmc import CoinMarketCapClient
from .polygon_api import PolygonClient
from .polygon_s3 import PolygonS3Client


# Exception definition
class ClientNotFoundError(Exception):
    """Exception raised when a requested client is not found."""

    pass


class ClientManager:
    """
    Manages multiple API clients with proactive rate limiting and health checks.

    with:
      - Proactive rate limiting using asyncio.Semaphore.
      - Periodic health checks to verify client availability.
      - Configurable rate limits and health check intervals.
    """

    MAX_RETRIES: int = 3  # Prevent infinite loops
    COOLDOWN: int = 30  # Cooldown in seconds
    HEALTH_CHECK_INTERVAL: int = 60 * 5  # 5 minutes for health checks
    DEFAULT_RATE_LIMITS = {  # Default rate limits per client
        "cmc": 10,
        "polygon": 5,
        "alpha_vantage": 5,
        "bitstamp": 1000,
    }

    def __init__(
        self,
        assets: List[str],
        metrics_manager: Optional[Any] = None,
        rate_limits: Optional[Dict[str, int]] = None,
        event_loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """
        Initialize the ClientManager with API clients, rate limiting, and health checks.
        """
        self._lock = threading.RLock()
        self.failed_clients: Dict[str, float] = (
            {}
        )  # Tracks failed clients with timestamp
        self._health_check_tasks: Dict[str, Optional[asyncio.Task]] = (
            {}
        )  # Health check tasks

        # Use provided metrics_manager or default to PrometheusMetrics
        if metrics_manager is None:
            from framework.middleware.metrics import PrometheusMetrics

            metrics_manager = PrometheusMetrics()  # Create an instance
            logger.debug(
                "No metrics_manager provided; using default PrometheusMetrics instance."
            )
        self.metrics_manager = metrics_manager

        # Store configuration parameters
        self.assets = assets
        self.rate_limits = rate_limits or self.DEFAULT_RATE_LIMITS

        # Use provided event loop or the current one
        self._event_loop = event_loop or asyncio.get_event_loop()

        logger.debug(
            f"[ClientManager.__init__] Initializing with assets: {self.assets} and rate_limits: {self.rate_limits}"
        )

        # Load API keys from environment variables
        self.api_keys: Dict[str, Any] = {
            "cmc": os.getenv("CMC_API_KEY"),
            "polygon": os.getenv("POLYGON_API_KEY"),
            "bitstamp": {},  # Bitstamp doesn't require an API key
            "alpha_vantage": os.getenv("ALPHA_VANTAGE_API_KEY"),
        }
        self._validate_api_keys()

        # Initialize API clients and corresponding rate limit semaphores.
        self.clients: Dict[str, BaseClient] = {}  # Updated type hint
        self._rate_limit_semaphores: Dict[str, asyncio.Semaphore] = {}

        # Initialize all clients
        self._initialize_clients()

        # Configure preferred clients for each asset (using upper-case symbols)
        self.preferred_clients: Dict[str, List[str]] = {}
        for asset in self.assets:
            self.preferred_clients[asset.upper()] = [
                "bitstamp",
                "polygon",
                "polygon_s3",
                "cmc",
                "alpha_vantage",
            ]
        logger.debug(
            f"[ClientManager.__init__] Preferred clients configured: {self.preferred_clients}"
        )

        # Start health check tasks on the event loop
        asyncio.run_coroutine_threadsafe(self._start_health_checks(), self._event_loop)

    def _initialize_clients(self) -> None:
        """Initialize all API clients with proper configuration"""

        # Bitstamp client (no API key required)
        try:
            self.clients["bitstamp"] = BitstampClient(metrics=self.metrics_manager)
            self._rate_limit_semaphores["bitstamp"] = asyncio.Semaphore(
                self.rate_limits["bitstamp"]
            )
            logger.info("BitstampClient initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize BitstampClient: {e}")

        # Initialize clients that require API keys
        self._initialize_client_with_key(
            "cmc", CoinMarketCapClient, self.api_keys["cmc"]
        )
        self._initialize_client_with_key(
            "polygon", PolygonClient, self.api_keys["polygon"]
        )
        self._initialize_client_with_key(
            "alpha_vantage", AlphaVantageClient, self.api_keys["alpha_vantage"]
        )

        # Polygon S3 Client - Initialize S3 client; handle missing credentials gracefully.
        try:
            polygon_s3_client = PolygonS3Client(metrics=self.metrics_manager)
            self.clients["polygon_s3"] = polygon_s3_client
            logger.info("PolygonS3Client initialized successfully")
        except ValueError as e:
            logger.warning(f"PolygonS3Client not initialized: {e}")

    def _initialize_client_with_key(
        self, client_name: str, client_class, api_key: Optional[str]
    ) -> None:
        """Helper method to initialize a client that requires an API key"""
        if not api_key:
            logger.warning(
                f"{client_name.upper()}_API_KEY not provided; {client_class.__name__} may not function correctly."
            )
            return

        try:
            client = client_class(api_key, metrics=self.metrics_manager)
            self.clients[client_name] = client
            self._rate_limit_semaphores[client_name] = asyncio.Semaphore(
                self.rate_limits.get(client_name, 5)
            )
            logger.info(f"{client_class.__name__} initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize {client_class.__name__}: {e}")

    async def _start_health_checks(self) -> None:
        """
        Starts periodic health check tasks for each client.
        """
        for client_name in self.clients:
            health_task = self._health_check_tasks.get(client_name)
            if health_task is None or health_task.done():
                self._health_check_tasks[client_name] = asyncio.create_task(
                    self._periodic_health_check(client_name)
                )
                logger.debug(
                    f"[ClientManager._start_health_checks] Started health check for {client_name}"
                )
            else:
                logger.debug(
                    f"[ClientManager._start_health_checks] Health check already running for {client_name}"
                )
        logger.info(
            "[ClientManager._start_health_checks] Health checks started for all clients."
        )

    async def _periodic_health_check(self, client_name: str) -> None:
        """
        Periodically checks the health of a specific API client.
        Marks the client as failed if the health check fails.
        """
        while True:
            await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
            if client_name in self.clients:
                if client_name in self.failed_clients:
                    logger.debug(
                        f"[ClientManager._periodic_health_check] Skipping health check for '{client_name}' (marked as failed)."
                    )
                    continue
                try:
                    client = self.clients[client_name]
                    logger.debug(
                        f"[ClientManager._periodic_health_check] Performing health check for {client_name}..."
                    )
                    healthy = await self._run_health_check(client)
                    if healthy:
                        logger.info(f"✅ Health check passed for {client_name}.")
                    else:
                        logger.warning(
                            f"❌ Health check failed for {client_name}. Reporting failure."
                        )
                        self.report_failure(client_name)
                except Exception as e:
                    logger.error(
                        f"⚠️ Error during health check for {client_name}: {e}",
                        exc_info=True,
                    )
                    self.report_failure(client_name)
            else:
                logger.warning(
                    f"[ClientManager._periodic_health_check] Client '{client_name}' no longer managed; stopping health checks."
                )
                break

    async def _run_health_check(self, client: BaseClient) -> bool:
        """
        Executes the health check for a given client.
        Returns True if healthy, False otherwise.
        """
        try:
            # All clients now implement get_health_status()
            is_healthy = await asyncio.get_running_loop().run_in_executor(
                None, client.get_health_status
            )
            return is_healthy
        except Exception as e:
            logger.error(f"Health check failed for {client.name}: {e}", exc_info=True)
            return False

    def _validate_api_keys(self) -> None:
        missing_keys = [
            key
            for key, value in self.api_keys.items()
            if key != "bitstamp" and not value
        ]
        if missing_keys:
            logger.warning(
                f"⚠️ Missing API keys for: {missing_keys}. Some services may not work."
            )

    async def acquire_semaphore(self, client_name: str) -> asyncio.Semaphore:
        semaphore = self._rate_limit_semaphores.get(client_name)
        if not semaphore:
            raise ClientNotFoundError(f"No semaphore found for client: {client_name}")
        await semaphore.acquire()
        return semaphore

    def release_semaphore(self, client_name: str, semaphore: asyncio.Semaphore) -> None:
        if semaphore and client_name in self._rate_limit_semaphores:
            semaphore.release()
        elif client_name not in self._rate_limit_semaphores:
            logger.warning(
                f"Semaphore release attempted for non-existent client: {client_name}"
            )
        else:
            logger.warning(
                f"Semaphore release attempted with invalid semaphore for client: {client_name}"
            )

    def get_client(self, symbol: str, retry_count: int = 0) -> BaseClient:
        """
        Retrieves a client for the given asset symbol based on preferred order.
        Retries up to MAX_RETRIES if no client is immediately available.
        """
        with self._lock:
            symbol = symbol.upper()
            client_list = self.preferred_clients.get(symbol, [])
            for client_name in client_list:
                if (
                    client_name in self.clients
                    and client_name not in self.failed_clients
                ):
                    logger.info(f"✅ Using {client_name} for symbol '{symbol}'.")
                    return self.clients[client_name]
            if retry_count < self.MAX_RETRIES:
                logger.warning(
                    f"⚠️ No available API clients for symbol='{symbol}'. Retrying {retry_count + 1}/{self.MAX_RETRIES}..."
                )
                self._retry_failed_clients()
                return self.get_client(symbol, retry_count + 1)
            else:
                logger.error(
                    f"❌ Still no clients for symbol='{symbol}' after {self.MAX_RETRIES} retries."
                )
                raise ClientNotFoundError(
                    f"No available clients for {symbol} after {self.MAX_RETRIES} retries."
                )

    def report_failure(self, client_name: str) -> None:
        """
        Report a client failure, mark it as unavailable, and cancel its health check.
        """
        with self._lock:
            logger.warning(
                f"⚠️ API limit or error on client '{client_name}'. Marking as failed."
            )
            self.failed_clients[client_name] = time.time()
            logger.info("🔄 Attempting to switch to a different provider if available.")

            # Record client availability in metrics if client exists
            if client_name in self.clients:
                try:
                    # Set availability to false in metrics
                    client = self.clients[client_name]
                    client.metrics.record_client_availability(
                        client_name=client.name, available=False
                    )
                except Exception as e:
                    logger.error(f"Failed to record client unavailability: {e}")

            # Cancel health check task if it exists
            health_task = self._health_check_tasks.get(client_name)
            if (
                isinstance(health_task, asyncio.Task)
                and not health_task.cancelled()
                and not health_task.done()
            ):
                health_task.cancel()
                logger.debug(
                    f"[ClientManager.report_failure] Cancelled health check for failed client: {client_name}"
                )

    def _retry_failed_clients(self) -> None:
        """
        Retry clients that have been in cooldown long enough.
        """
        current_time = time.time()
        with self._lock:
            retried_clients = []
            for client_name, fail_time in list(self.failed_clients.items()):
                if (current_time - fail_time) >= self.COOLDOWN:
                    logger.info(
                        f"🔄 Retrying client '{client_name}' after cooldown of {self.COOLDOWN}s."
                    )
                    del self.failed_clients[client_name]
                    retried_clients.append(client_name)

                    # Mark client as potentially available in metrics
                    if client_name in self.clients:
                        try:
                            client = self.clients[client_name]
                            client.metrics.record_client_availability(
                                client_name=client.name, available=True
                            )
                        except Exception as e:
                            logger.error(f"Failed to record client availability: {e}")

            # Restart health checks for retried clients
            for client_name in retried_clients:
                if client_name in self.clients:
                    health_task = self._health_check_tasks.get(client_name)
                    if health_task is None or health_task.done():
                        self._health_check_tasks[client_name] = asyncio.create_task(
                            self._periodic_health_check(client_name)
                        )
                        logger.debug(
                            f"[ClientManager._retry_failed_clients] Restarted health check for retried client: {client_name}"
                        )

    def get_client_by_name(self, client_name: str) -> BaseClient:
        """
        Get a specific client by its name.
        """
        client_name = client_name.strip().lower()
        with self._lock:
            client = self.clients.get(client_name)
            if client:
                logger.info(f"✅ Using client '{client_name}' (by name).")
                return client
            available = ", ".join(self.clients.keys()) if self.clients else "None"
            raise ClientNotFoundError(
                f"❌ No client found for API='{client_name}'. Available clients: {available}"
            )

    async def get_client_async(self, client_name: str) -> Optional[BaseClient]:
        """
        Asynchronously get a client by name.
        """
        try:
            return self.get_client_by_name(client_name)
        except ClientNotFoundError:
            logger.error(f"❌ Async: No client found for '{client_name}'.")
            return None

    def get_all_clients(self) -> Dict[str, BaseClient]:
        """
        Get a dictionary of all available clients.
        """
        return self.clients

    # Expose preferred clients configuration
    @property
    def preferred_clients_config(self) -> Dict[str, List[str]]:
        """
        Get the preferred clients configuration for all assets.
        """
        return self.preferred_clients


# ----------------------------
# FastAPI Router Integration
# ----------------------------
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/manager", tags=["ClientManager"])

# For demonstration, create a global ClientManager instance.
# In production, you might want to configure this differently.
assets = ["BTC", "ETH", "AAPL"]
client_manager = ClientManager(assets=assets)


class SymbolPayload(BaseModel):
    symbol: str


@router.get("/client", summary="Get preferred client for an asset symbol")
def get_client_for_asset(
    symbol: str = Query(..., description="Asset symbol (e.g., BTC)")
) -> Dict[str, Any]:
    """
    Retrieve the preferred API client for a given asset symbol.
    Returns the client's name.
    """
    try:
        client = client_manager.get_client(symbol)
        return {"symbol": symbol.upper(), "client": client.name}
    except ClientNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/clients", summary="List all available API clients")
def list_all_clients() -> Dict[str, Any]:
    """
    List the names of all available API clients.
    """
    clients = list(client_manager.get_all_clients().keys())
    return {"clients": clients}


@router.get("/status", summary="Get client health status")
def get_status() -> Dict[str, Any]:
    """
    Retrieve the current status of the API clients.
    Returns a list of failed clients (with timestamps) along with all client names.
    """
    return {
        "failed_clients": client_manager.failed_clients,
        "all_clients": list(client_manager.clients.keys()),
    }


@router.get("/preferred", summary="Get preferred clients for an asset")
def get_preferred_clients(
    symbol: str = Query(..., description="Asset symbol (e.g., BTC)")
) -> Dict[str, Any]:
    """
    Retrieve the configured preferred API clients for the given asset.
    """
    symbol = symbol.upper()
    preferred = client_manager.preferred_clients.get(symbol)
    if not preferred:
        raise HTTPException(
            status_code=404,
            detail=f"No preferred clients configured for symbol {symbol}",
        )
    return {"symbol": symbol, "preferred_clients": preferred}
