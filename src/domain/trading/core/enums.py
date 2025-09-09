"""
Core enumerations for the FKS trading system.
"""

from enum import Enum, IntEnum


class SignalDirection(IntEnum):
    """Trading signal direction with strength indicators"""

    STRONG_SHORT = -2
    SHORT = -1
    NEUTRAL = 0
    LONG = 1
    STRONG_LONG = 2


class TrendDirection(IntEnum):
    """Market trend direction"""

    STRONG_DOWN = -2
    DOWN = -1
    SIDEWAYS = 0
    UP = 1
    STRONG_UP = 2
    NONE = 0


class MarketRegime(Enum):
    """Market regime classification"""

    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    STRONG_TREND = "strong_trend"
    WEAK_TREND = "weak_trend"
    CHOPPY = "choppy"
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    RANGE = "range"
    RANGE_BOUND = "range_bound"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    BREAKOUT = "breakout"
    REVERSAL = "reversal"
    NEWS_EVENT = "news_event"
    CONSOLIDATION = "consolidation"
    CALM = "calm"


class VolatilityRegime(Enum):
    """Volatility regime classification"""

    VERY_LOW = "very_low"
    LOW = "low"
    NORMAL = "normal"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class ComponentStatus(Enum):
    """Component health status"""

    HEALTHY = "healthy"
    WARNING = "warning"
    FAILED = "failed"
    INITIALIZING = "initializing"
    DISABLED = "disabled"
    ERROR = "error"
    DISPOSED = "disposed"


class SessionType(Enum):
    """Trading session types"""

    ASIAN_SESSION = "asian"
    LONDON_OPEN = "london_open"
    LONDON_SESSION = "london"
    NY_OPEN = "ny_open"
    NY_SESSION = "ny"
    LONDON_CLOSE = "london_close"
    NY_CLOSE = "ny_close"
    WEEKEND = "weekend"


class LogLevel(IntEnum):
    """Logging levels"""

    DEBUG = 0
    INFORMATION = 1
    WARNING = 2
    ERROR = 3
