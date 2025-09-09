"""
FKS Trading Systems - Market Data Domain Models

Defines the core domain models for market data including prices,
volumes, technical indicators, and market events.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional


class MarketDataType(Enum):
    """Types of market data."""

    TICK = "tick"
    QUOTE = "quote"
    TRADE = "trade"
    BAR = "bar"
    ORDER_BOOK = "order_book"
    LEVEL1 = "level1"
    LEVEL2 = "level2"


class TimeFrame(Enum):
    """Standard time frames for market data."""

    TICK = "tick"
    SECOND_1 = "1s"
    SECOND_5 = "5s"
    SECOND_10 = "10s"
    SECOND_15 = "15s"
    SECOND_30 = "30s"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1M"


class MarketStatus(Enum):
    """Market session status."""

    PRE_MARKET = "pre_market"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    AFTER_HOURS = "after_hours"
    HOLIDAY = "holiday"


@dataclass
class Instrument:
    """
    Represents a tradable financial instrument.
    """

    symbol: str
    name: str
    asset_class: str  # equity, bond, forex, crypto, commodity, derivative
    exchange: str
    currency: str
    tick_size: Decimal = Decimal("0.01")
    lot_size: int = 1
    min_quantity: Decimal = Decimal("1")
    max_quantity: Optional[Decimal] = None
    margin_requirement: Optional[Decimal] = None
    is_active: bool = True
    sector: Optional[str] = None
    industry: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate instrument data after initialization."""
        if not self.symbol:
            raise ValueError("Symbol cannot be empty")
        if self.tick_size <= 0:
            raise ValueError("Tick size must be positive")
        if self.lot_size <= 0:
            raise ValueError("Lot size must be positive")


@dataclass
class MarketData:
    """
    Base class for all market data.
    """

    symbol: str
    timestamp: datetime
    data_type: MarketDataType
    exchange: str
    source: str = "unknown"
    sequence: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate market data after initialization."""
        if not self.symbol:
            raise ValueError("Symbol cannot be empty")
        if not isinstance(self.timestamp, datetime):
            raise ValueError("Timestamp must be a datetime object")


@dataclass
class Tick(MarketData):
    """
    Individual tick data representing a single trade or quote.
    """

    price: Decimal
    size: Decimal
    side: Optional[str] = None  # 'buy', 'sell', or None for quotes
    trade_id: Optional[str] = None

    def __post_init__(self):
        super().__post_init__()
        self.data_type = MarketDataType.TICK

        if self.price <= 0:
            raise ValueError("Price must be positive")
        if self.size <= 0:
            raise ValueError("Size must be positive")


@dataclass
class Quote(MarketData):
    """
    Bid/ask quote data.
    """

    bid_price: Decimal
    bid_size: Decimal
    ask_price: Decimal
    ask_size: Decimal
    spread: Optional[Decimal] = None
    mid_price: Optional[Decimal] = None

    def __post_init__(self):
        super().__post_init__()
        self.data_type = MarketDataType.QUOTE

        if self.bid_price <= 0 or self.ask_price <= 0:
            raise ValueError("Bid and ask prices must be positive")
        if self.bid_size <= 0 or self.ask_size <= 0:
            raise ValueError("Bid and ask sizes must be positive")
        if self.bid_price >= self.ask_price:
            raise ValueError("Bid price must be less than ask price")

        # Calculate derived fields
        if self.spread is None:
            self.spread = self.ask_price - self.bid_price
        if self.mid_price is None:
            self.mid_price = (self.bid_price + self.ask_price) / 2


@dataclass
class Trade(MarketData):
    """
    Executed trade data.
    """

    price: Decimal
    volume: Decimal
    side: str  # 'buy' or 'sell'
    trade_id: str
    buyer_order_id: Optional[str] = None
    seller_order_id: Optional[str] = None
    trade_conditions: List[str] = field(default_factory=list)

    def __post_init__(self):
        super().__post_init__()
        self.data_type = MarketDataType.TRADE

        if self.price <= 0:
            raise ValueError("Price must be positive")
        if self.volume <= 0:
            raise ValueError("Volume must be positive")
        if self.side not in ["buy", "sell"]:
            raise ValueError("Side must be 'buy' or 'sell'")
        if not self.trade_id:
            raise ValueError("Trade ID cannot be empty")


@dataclass
class Bar(MarketData):
    """
    OHLCV bar data for a specific time period.
    """

    timeframe: TimeFrame
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: Optional[int] = None
    vwap: Optional[Decimal] = None  # Volume Weighted Average Price
    bar_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        super().__post_init__()
        self.data_type = MarketDataType.BAR

        if any(price <= 0 for price in [self.open, self.high, self.low, self.close]):
            raise ValueError("All prices must be positive")
        if self.volume < 0:
            raise ValueError("Volume cannot be negative")
        if not (
            self.low <= self.open <= self.high and self.low <= self.close <= self.high
        ):
            raise ValueError(
                "Price relationships are invalid (low <= open,close <= high)"
            )
        if not (self.low <= self.high):
            raise ValueError("Low price cannot be greater than high price")

        # Calculate VWAP if not provided and we have trade data
        if self.vwap is None and self.volume > 0:
            self.vwap = (self.high + self.low + self.close) / 3  # Approximation


@dataclass
class OrderBookLevel:
    """
    Single level in an order book.
    """

    price: Decimal
    size: Decimal
    order_count: Optional[int] = None

    def __post_init__(self):
        if self.price <= 0:
            raise ValueError("Price must be positive")
        if self.size < 0:
            raise ValueError("Size cannot be negative")


@dataclass
class OrderBook(MarketData):
    """
    Order book with bid and ask levels.
    """

    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
    depth: int = 10

    def __post_init__(self):
        super().__post_init__()
        self.data_type = MarketDataType.ORDER_BOOK

        # Validate bid/ask ordering
        for i in range(1, len(self.bids)):
            if self.bids[i].price >= self.bids[i - 1].price:
                raise ValueError("Bids must be in descending price order")

        for i in range(1, len(self.asks)):
            if self.asks[i].price <= self.asks[i - 1].price:
                raise ValueError("Asks must be in ascending price order")

        # Validate spread
        if self.bids and self.asks:
            if self.bids[0].price >= self.asks[0].price:
                raise ValueError("Best bid must be less than best ask")

    @property
    def best_bid(self) -> Optional[OrderBookLevel]:
        """Get best bid level."""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[OrderBookLevel]:
        """Get best ask level."""
        return self.asks[0] if self.asks else None

    @property
    def spread(self) -> Optional[Decimal]:
        """Get bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    @property
    def mid_price(self) -> Optional[Decimal]:
        """Get mid price."""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None


@dataclass
class TechnicalIndicator:
    """
    Technical indicator value with metadata.
    """

    name: str
    value: Decimal
    timestamp: datetime
    symbol: str
    timeframe: TimeFrame
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: Optional[float] = None

    def __post_init__(self):
        if not self.name:
            raise ValueError("Indicator name cannot be empty")
        if not self.symbol:
            raise ValueError("Symbol cannot be empty")


@dataclass
class MarketEvent:
    """
    Represents a significant market event.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""  # earnings, dividend, split, etc.
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    description: str = ""
    impact: str = ""  # high, medium, low
    source: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.symbol:
            raise ValueError("Symbol cannot be empty")
        if not self.event_type:
            raise ValueError("Event type cannot be empty")


@dataclass
class MarketSession:
    """
    Represents a trading session with market hours.
    """

    exchange: str
    date: datetime
    pre_market_start: Optional[datetime] = None
    market_open: Optional[datetime] = None
    market_close: Optional[datetime] = None
    after_hours_end: Optional[datetime] = None
    status: MarketStatus = MarketStatus.CLOSED
    is_trading_day: bool = True

    def __post_init__(self):
        if not self.exchange:
            raise ValueError("Exchange cannot be empty")

    def is_market_open(self, timestamp: datetime) -> bool:
        """Check if market is open at given timestamp."""
        if not self.is_trading_day:
            return False

        if self.market_open and self.market_close:
            return self.market_open <= timestamp <= self.market_close

        return False

    def is_pre_market(self, timestamp: datetime) -> bool:
        """Check if timestamp is in pre-market hours."""
        if not self.is_trading_day or not self.pre_market_start or not self.market_open:
            return False

        return self.pre_market_start <= timestamp < self.market_open

    def is_after_hours(self, timestamp: datetime) -> bool:
        """Check if timestamp is in after-hours."""
        if not self.is_trading_day or not self.market_close:
            return False

        if self.after_hours_end:
            return self.market_close < timestamp <= self.after_hours_end
        else:
            return timestamp > self.market_close


@dataclass
class MarketDataSnapshot:
    """
    Point-in-time snapshot of market data for multiple symbols.
    """

    timestamp: datetime
    quotes: Dict[str, Quote] = field(default_factory=dict)
    trades: Dict[str, Trade] = field(default_factory=dict)
    bars: Dict[str, Bar] = field(default_factory=dict)
    order_books: Dict[str, OrderBook] = field(default_factory=dict)
    indicators: Dict[str, List[TechnicalIndicator]] = field(default_factory=dict)

    def add_quote(self, quote: Quote) -> None:
        """Add quote to snapshot."""
        self.quotes[quote.symbol] = quote

    def add_trade(self, trade: Trade) -> None:
        """Add trade to snapshot."""
        self.trades[trade.symbol] = trade

    def add_bar(self, bar: Bar) -> None:
        """Add bar to snapshot."""
        self.bars[bar.symbol] = bar

    def add_order_book(self, order_book: OrderBook) -> None:
        """Add order book to snapshot."""
        self.order_books[order_book.symbol] = order_book

    def add_indicator(self, indicator: TechnicalIndicator) -> None:
        """Add technical indicator to snapshot."""
        if indicator.symbol not in self.indicators:
            self.indicators[indicator.symbol] = []
        self.indicators[indicator.symbol].append(indicator)

    def get_last_price(self, symbol: str) -> Optional[Decimal]:
        """Get last known price for symbol."""
        # Try trade first
        if symbol in self.trades:
            return self.trades[symbol].price

        # Then quote mid price
        if symbol in self.quotes:
            return self.quotes[symbol].mid_price

        # Then bar close
        if symbol in self.bars:
            return self.bars[symbol].close

        return None

    def get_symbols(self) -> List[str]:
        """Get all symbols in snapshot."""
        symbols = set()
        symbols.update(self.quotes.keys())
        symbols.update(self.trades.keys())
        symbols.update(self.bars.keys())
        symbols.update(self.order_books.keys())
        symbols.update(self.indicators.keys())
        return list(symbols)


# Utility functions for market data


def create_bar_from_ticks(ticks: List[Tick], timeframe: TimeFrame) -> Optional[Bar]:
    """
    Create a bar from a list of ticks.

    Args:
        ticks: List of tick data
        timeframe: Time frame for the bar

    Returns:
        Bar object or None if no ticks
    """
    if not ticks:
        return None

    # Sort ticks by timestamp
    sorted_ticks = sorted(ticks, key=lambda t: t.timestamp)

    # Calculate OHLCV
    open_price = sorted_ticks[0].price
    close_price = sorted_ticks[-1].price
    high_price = max(tick.price for tick in sorted_ticks)
    low_price = min(tick.price for tick in sorted_ticks)
    volume = sum(tick.size for tick in sorted_ticks)

    # Calculate VWAP
    total_value = sum(tick.price * tick.size for tick in sorted_ticks)
    vwap = total_value / volume if volume > 0 else close_price

    return Bar(
        symbol=sorted_ticks[0].symbol,
        timestamp=sorted_ticks[0].timestamp,
        exchange=sorted_ticks[0].exchange,
        source=sorted_ticks[0].source,
        timeframe=timeframe,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        trade_count=len(sorted_ticks),
        vwap=vwap,
    )


def normalize_symbol(symbol: str) -> str:
    """
    Normalize symbol format.

    Args:
        symbol: Raw symbol string

    Returns:
        Normalized symbol
    """
    return symbol.upper().strip()


def is_valid_trading_hours(timestamp: datetime, exchange: str = "NYSE") -> bool:
    """
    Check if timestamp is within trading hours.

    Args:
        timestamp: Timestamp to check
        exchange: Exchange identifier

    Returns:
        True if within trading hours
    """
    # Simple implementation for NYSE (9:30 AM - 4:00 PM ET)
    # This would be expanded for different exchanges and time zones

    # Check if weekday
    if timestamp.weekday() > 4:  # Weekend
        return False

    # Check time (simplified, assumes ET timezone)
    time_obj = timestamp.time()
    market_open = timestamp.replace(hour=9, minute=30, second=0, microsecond=0).time()
    market_close = timestamp.replace(hour=16, minute=0, second=0, microsecond=0).time()

    return market_open <= time_obj <= market_close
