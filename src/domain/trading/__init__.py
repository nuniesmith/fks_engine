"""
FKS Trading Systems - Python Implementation
==========================================

A comprehensive trading system for NinjaTrader integration with Python-based
analytics, monitoring, and signal generation.

Modules:
- core: Core enums, models, and configurations
- infrastructure: Error handling, memory management, performance tracking
- calculations: Technical indicators, caching, and state management
- market: Market regime analysis and state detection
- signals: Signal generation and coordination
- indicators: Custom trading indicators (AI, AO, Info)
- utils: Helper utilities and common functions
- monitoring: Real-time monitoring and metrics collection
- bridge: NinjaTrader-Python bridge for communication
- api: REST API and WebSocket endpoints
"""

__version__ = "1.0.0"
__author__ = "FKS Trading Systems"

# Core imports for easy access
from .core.enums import MarketRegime, SignalDirection, TrendDirection
from .core.models import MarketData, SignalQuality, TradingSetup

__all__ = [
    "SignalDirection",
    "TrendDirection",
    "MarketRegime",
    "MarketData",
    "TradingSetup",
    "SignalQuality",
]
