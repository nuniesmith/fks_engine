from fastapi import APIRouter

# Re-export the base client
from infrastructure.external.data_providers.clients.base import BaseClient

# Import all client modules
from .alpha import AlphaVantageClient
from .alpha import router as alpha_router
from .bitstamp import BitstampClient
from .bitstamp import router as bitstamp_router
from .cmc import CoinMarketCapClient
from .cmc import router as cmc_router
from .manager import ClientManager
from .manager import router as client_manager_router
from .polygon_api import PolygonClient
from .polygon_api import router as polygon_api_router
from .polygon_s3 import PolygonS3Client
from .polygon_s3 import router as polygon_s3_router

# Create a list of routers for all adapters
routers = [
    alpha_router,
    bitstamp_router,
    cmc_router,
    client_manager_router,
    polygon_api_router,
    polygon_s3_router,
]

# Export everything needed
__all__ = [
    "routers",  # Export the list of routers
    "BaseClient",  # Export the base client class
    "AlphaVantageClient",
    "BitstampClient",
    "CoinMarketCapClient",
    "ClientManager",
    "PolygonClient",
    "PolygonS3Client",
]
