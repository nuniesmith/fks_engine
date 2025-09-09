# services/app/strategies/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


@dataclass
class TradingSignal:
    strategy_id: str
    symbol: str
    action: str  # BUY, SELL, HOLD
    quantity: float
    confidence: float
    reason: str
    metadata: Dict[str, Any]
    timestamp: datetime


@dataclass
class StrategyMetrics:
    """Basic strategy metrics placeholder."""

    strategy_id: str
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0


@dataclass
class MarketData:
    """Market data placeholder."""

    price: float
    volume: float
    timestamp: str


@dataclass
class MarketEvent:
    """Market event placeholder."""

    event_type: str
    data: Dict[str, Any]


class StrategyState(Enum):
    """Strategy state enum."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"


class BaseStrategy(ABC):
    """Base class for all trading strategies"""

    def __init__(self, strategy_id: str, config: Dict[str, Any]):
        self.strategy_id = strategy_id
        self.config = config
        self.is_active = True
        self.state = {}
        self.metrics = StrategyMetrics(strategy_id=strategy_id)

    @abstractmethod
    async def analyze(self, market_data: MarketData) -> Optional[TradingSignal]:
        """Analyze market data and generate signal"""
        pass

    async def process(self, event: MarketEvent) -> Optional[TradingSignal]:
        """Process event with pre/post processing"""
        # Pre-process
        if not await self.should_process(event):
            return None

        # Update state
        await self.update_state(event)

        # Generate signal
        # Convert event data to MarketData format
        market_data = MarketData(
            price=event.data.get("price", 0.0),
            volume=event.data.get("volume", 0.0),
            timestamp=event.data.get("timestamp", ""),
        )
        signal = await self.analyze(market_data)

        # Post-process
        if signal:
            signal = await self.validate_signal(signal)
            # self.metrics.record_signal(signal)  # TODO: Implement

        return signal

    async def update_state(self, event: MarketEvent) -> None:
        """Update strategy state"""
        # Default implementation - strategies can override
        symbol = event.data.get("symbol", "")
        if symbol not in self.state:
            self.state[symbol] = StrategyState.IDLE

        # TODO: Update state based on event data

    async def should_process(self, event: MarketEvent) -> bool:
        """Check if event should be processed"""
        return self.is_active and event.event_type in ["price_update", "market_data"]

    async def validate_signal(self, signal: TradingSignal) -> TradingSignal:
        """Validate generated signal"""
        # Default validation - strategies can override
        return signal
