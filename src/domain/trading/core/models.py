"""
Core models and data structures for the FKS trading system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .enums import MarketRegime, SignalDirection, TrendDirection


@dataclass
class MarketData:
    """Comprehensive market data container with validation"""

    timestamp: datetime
    price: float
    current_price: float
    volume: float
    current_volume: float
    average_volume: float
    atr: float
    volatility: float
    current_trend: TrendDirection = TrendDirection.SIDEWAYS
    time_frame: str = ""
    volume_history: List[float] = field(default_factory=list)
    price_change: float = 0.0
    market_regime: MarketRegime = MarketRegime.NEUTRAL
    range_low: float = 0.0
    range_high: float = 0.0
    label: float = 0.0

    @property
    def volume_ratio(self) -> float:
        return (
            self.current_volume / self.average_volume
            if self.average_volume > 0
            else 1.0
        )

    @property
    def volatility_percent(self) -> float:
        return (
            (self.volatility / self.current_price * 100)
            if self.current_price > 0
            else 0
        )

    @property
    def is_high_volume(self) -> bool:
        return self.volume_ratio > 1.5

    @property
    def is_low_volume(self) -> bool:
        return self.volume_ratio < 0.7

    def is_valid(self) -> bool:
        """Validate market data integrity"""
        return (
            self.price > 0
            and self.volume >= 0
            and self.atr >= 0
            and not any(
                map(
                    lambda x: x != x or x == float("inf"),
                    [self.price, self.volume, self.atr],
                )
            )
        )


@dataclass
class Candle:
    """OHLCV candle data with technical analysis properties"""

    open: float
    high: float
    low: float
    close: float
    volume: float
    time: datetime

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body_ratio(self) -> float:
        return self.body_size / self.range if self.range > 0 else 0

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        return abs(self.close - self.open) < (self.range * 0.1)

    @property
    def is_hammer(self) -> bool:
        return self.lower_wick > (self.body_size * 2) and self.upper_wick < (
            self.body_size * 0.5
        )

    @property
    def is_shooting_star(self) -> bool:
        return self.upper_wick > (self.body_size * 2) and self.lower_wick < (
            self.body_size * 0.5
        )


@dataclass
class ComponentSignal:
    """Component signal with comprehensive validation and metrics"""

    source: str
    direction: SignalDirection
    score: float
    confidence: float
    is_active: bool
    timestamp: datetime
    reasons: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    @property
    def strength(self) -> float:
        return abs(self.score) * self.confidence

    @property
    def is_strong(self) -> bool:
        return self.confidence >= 0.8 and abs(self.score) >= 0.7

    @property
    def is_weak(self) -> bool:
        return self.confidence < 0.6 or abs(self.score) < 0.4

    @property
    def age(self) -> timedelta:
        return datetime.now() - self.timestamp

    @property
    def is_stale(self) -> bool:
        return self.age.total_seconds() > 600  # 10 minutes

    def is_valid(self) -> bool:
        """Validate signal integrity"""
        return (
            bool(self.source)
            and not any(
                map(
                    lambda x: x != x or x == float("inf"), [self.score, self.confidence]
                )
            )
            and -1 <= self.score <= 1
            and 0 <= self.confidence <= 1
            and not self.is_stale
        )


@dataclass
class SignalQuality:
    """Enhanced signal quality scoring system"""

    base_score: float = 0.0
    confluence_score: float = 0.0
    timing_score: float = 0.0
    market_context_score: float = 0.0
    risk_reward_score: float = 0.0

    @property
    def overall_score(self) -> float:
        return (
            self.base_score * 0.3
            + self.confluence_score * 0.25
            + self.timing_score * 0.15
            + self.market_context_score * 0.20
            + self.risk_reward_score * 0.10
        )

    @property
    def is_bulletproof(self) -> bool:
        return (
            self.overall_score >= 0.85
            and self.confluence_score >= 0.8
            and self.risk_reward_score >= 0.7
        )

    def get_quality_grade(self) -> str:
        score = self.overall_score
        if score >= 0.9:
            return "A+"
        elif score >= 0.85:
            return "A"
        elif score >= 0.80:
            return "B+"
        elif score >= 0.75:
            return "B"
        elif score >= 0.70:
            return "C+"
        elif score >= 0.65:
            return "C"
        else:
            return "F"


@dataclass
class TradingSetup:
    """Comprehensive trading setup with enhanced validation"""

    name: str
    direction: SignalDirection
    confidence: float
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward_ratio: float = 0.0
    quality: SignalQuality = field(default_factory=SignalQuality)
    reasons: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_valid(self) -> bool:
        return (
            self.entry_price > 0
            and self.stop_loss > 0
            and self.take_profit > 0
            and self.confidence > 0
        )

    @property
    def risk_amount(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_amount(self) -> float:
        return abs(self.take_profit - self.entry_price)
