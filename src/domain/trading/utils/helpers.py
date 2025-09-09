"""
Helper utilities for FKS trading system
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class FKSUtils:
    """Utility functions for FKS trading system"""

    @staticmethod
    def safe_divide(
        numerator: float, denominator: float, default: float = 0.0
    ) -> float:
        """Safely divide two numbers, returning default if denominator is zero"""
        try:
            if denominator == 0 or denominator != denominator:  # Check for NaN
                return default
            result = numerator / denominator
            return result if result == result else default  # Check for NaN result
        except (ZeroDivisionError, TypeError, ValueError):
            return default

    @staticmethod
    def is_valid_number(value: Any) -> bool:
        """Check if a value is a valid number (not NaN or infinite)"""
        try:
            return isinstance(value, (int, float)) and not (
                np.isnan(value) or np.isinf(value)
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp a value between min and max bounds"""
        return max(min_val, min(max_val, value))

    @staticmethod
    def calculate_percentage_change(old_value: float, new_value: float) -> float:
        """Calculate percentage change between two values"""
        if old_value == 0:
            return 0.0
        return ((new_value - old_value) / old_value) * 100

    @staticmethod
    def normalize_value(value: float, min_val: float, max_val: float) -> float:
        """Normalize a value to 0-1 range based on min/max bounds"""
        if max_val == min_val:
            return 0.5
        return (value - min_val) / (max_val - min_val)

    @staticmethod
    def round_to_tick(price: float, tick_size: float) -> float:
        """Round price to nearest tick size"""
        if tick_size <= 0:
            return price
        return round(price / tick_size) * tick_size

    @staticmethod
    def calculate_risk_reward_ratio(entry: float, stop: float, target: float) -> float:
        """Calculate risk/reward ratio for a trade"""
        risk = abs(entry - stop)
        reward = abs(target - entry)
        return FKSUtils.safe_divide(reward, risk, 0.0)

    @staticmethod
    def is_market_hours(current_time: Optional[datetime] = None) -> bool:
        """Check if current time is within market hours (simplified)"""
        if current_time is None:
            current_time = datetime.now()

        # Simple market hours check (9:30 AM - 4:00 PM ET, weekdays)
        weekday = current_time.weekday()
        if weekday >= 5:  # Weekend
            return False

        hour = current_time.hour
        minute = current_time.minute
        time_minutes = hour * 60 + minute

        market_open = 9 * 60 + 30  # 9:30 AM
        market_close = 16 * 60  # 4:00 PM

        return market_open <= time_minutes <= market_close

    @staticmethod
    def get_session_type(current_time: Optional[datetime] = None) -> str:
        """Determine current trading session"""
        if current_time is None:
            current_time = datetime.now()

        hour = current_time.hour

        if 20 <= hour <= 23 or 0 <= hour <= 2:
            return "asian"
        elif 3 <= hour <= 11:
            return "london"
        elif 9 <= hour <= 16:
            return "new_york"
        else:
            return "after_hours"

    @staticmethod
    def format_price(price: float, decimals: int = 2) -> str:
        """Format price for display"""
        if not FKSUtils.is_valid_number(price):
            return "N/A"
        return f"{price:.{decimals}f}"

    @staticmethod
    def calculate_position_size(
        account_balance: float,
        risk_percent: float,
        entry_price: float,
        stop_loss: float,
        point_value: float = 1.0,
    ) -> int:
        """Calculate position size based on risk management"""
        if not all(
            FKSUtils.is_valid_number(x)
            for x in [account_balance, risk_percent, entry_price, stop_loss]
        ):
            return 0

        risk_amount = account_balance * (risk_percent / 100)
        price_risk = abs(entry_price - stop_loss)

        if price_risk == 0:
            return 0

        position_size = risk_amount / (price_risk * point_value)
        return max(0, int(position_size))

    @staticmethod
    def log_trade_metrics(
        symbol: str, direction: str, entry: float, exit_price: float, quantity: int
    ) -> Dict[str, Any]:
        """Log and return trade metrics"""
        pnl = (
            (exit_price - entry) * quantity
            if direction.upper() == "LONG"
            else (entry - exit_price) * quantity
        )
        pnl_percent = FKSUtils.calculate_percentage_change(entry, exit_price)

        metrics = {
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(f"Trade executed: {metrics}")
        return metrics

    @staticmethod
    def create_time_key(timestamp: Optional[datetime] = None) -> str:
        """Create a time-based key for caching/storage"""
        if timestamp is None:
            timestamp = datetime.now()
        return timestamp.strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def retry_with_backoff(func, max_retries: int = 3, backoff_factor: float = 1.0):
        """Retry a function with exponential backoff"""
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                wait_time = backoff_factor * (2**attempt)
                logger.warning(
                    f"Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}"
                )
                time.sleep(wait_time)
