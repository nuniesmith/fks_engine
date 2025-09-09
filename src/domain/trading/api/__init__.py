"""
FKS API Module
REST API and WebSocket endpoints for the trading system
"""

from .main import app, manager
from .routes import *

__all__ = ["app", "manager"]
