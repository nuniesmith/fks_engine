"""
Fixed window rate limiting algorithm implementation.
"""

import time
from typing import Any, Dict

from .base import RateLimitAlgorithm, RateLimitResult


class FixedWindowAlgorithm(RateLimitAlgorithm):
    """
    Fixed window rate limiting algorithm.

    This algorithm divides time into fixed windows and counts requests within
    each window. When a window expires, the counter resets to zero. This is
    memory efficient but can allow burst traffic at window boundaries.

    Best for: High-throughput scenarios where memory efficiency is important
    and exact rate limiting precision is less critical.
    """

    def __init__(self, max_requests: int, time_window: int, name: str = "fixed_window"):
        """
        Initialize fixed window algorithm.

        Args:
            max_requests: Maximum number of requests allowed per time window
            time_window: Time window in seconds
            name: Name identifier for this algorithm instance
        """
        super().__init__(max_requests, time_window, name)

    def _get_current_window_start(self, current_time: float) -> int:
        """Calculate the start time of the current window."""
        return int(current_time // self.time_window) * self.time_window

    def _get_client_data(self, client_id: str) -> Dict[str, Any]:
        """Get or initialize fixed window data for a client."""
        if client_id not in self._client_data:
            current_time = time.time()
            window_start = self._get_current_window_start(current_time)
            self._client_data[client_id] = {
                "count": 0,
                "window_start": window_start,
                "last_seen": current_time,
            }
        return self._client_data[client_id]

    def _reset_window_if_needed(
        self, client_data: Dict[str, Any], current_time: float
    ) -> bool:
        """Reset the window if we've moved to a new time window."""
        current_window_start = self._get_current_window_start(current_time)

        if client_data["window_start"] < current_window_start:
            client_data["count"] = 0
            client_data["window_start"] = current_window_start
            return True

        return False

    def _check_limit(self, client_id: str, current_time: float) -> RateLimitResult:
        """Check if a request should be allowed for a client."""
        client_data = self._get_client_data(client_id)

        # Reset window if needed
        window_reset = self._reset_window_if_needed(client_data, current_time)
        self._update_last_seen(client_id, current_time)

        # Check if we're under the limit
        current_count = client_data["count"]
        allowed = current_count < self.max_requests
        remaining = max(0, self.max_requests - current_count)

        # Calculate reset time (end of current window)
        window_end = client_data["window_start"] + self.time_window
        reset_time = window_end

        # Calculate retry_after
        if allowed:
            retry_after = 0.0
        else:
            retry_after = max(0.0, reset_time - current_time)

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            reset_time=reset_time,
            retry_after=retry_after,
            total_limit=self.max_requests,
            current_usage=current_count,
        )

    def _consume_token(self, client_id: str, current_time: float) -> bool:
        """Increment the request count for the current window."""
        client_data = self._get_client_data(client_id)

        # Make sure window is current
        self._reset_window_if_needed(client_data, current_time)

        # Check if we can increment the counter
        if client_data["count"] < self.max_requests:
            client_data["count"] += 1
            return True

        return False

    def get_window_info(self, client_id: str) -> Dict[str, Any]:
        """
        Get detailed window information for a client.

        Args:
            client_id: Unique identifier for the client

        Returns:
            Dictionary with window details
        """
        with self._lock:
            current_time = time.time()
            client_data = self._get_client_data(client_id)

            # Update window if needed
            window_reset = self._reset_window_if_needed(client_data, current_time)

            window_start = client_data["window_start"]
            window_end = window_start + self.time_window
            window_progress = (current_time - window_start) / self.time_window

            # Calculate current rate
            time_elapsed = current_time - window_start
            if time_elapsed > 0:
                current_rate = client_data["count"] / time_elapsed
            else:
                current_rate = 0.0

            return {
                "client_id": client_id,
                "current_count": client_data["count"],
                "max_requests": self.max_requests,
                "window_start": window_start,
                "window_end": window_end,
                "window_progress": f"{window_progress:.1%}",
                "time_remaining": max(0, window_end - current_time),
                "window_was_reset": window_reset,
                "current_rate_per_second": current_rate,
            }

    def get_global_window_info(self) -> Dict[str, Any]:
        """
        Get information about the current global window.

        This is useful for understanding the fixed window boundaries
        that all clients share.

        Returns:
            Dictionary with global window information
        """
        current_time = time.time()
        current_window_start = self._get_current_window_start(current_time)
        window_end = current_window_start + self.time_window
        window_progress = (current_time - current_window_start) / self.time_window

        return {
            "current_window_start": current_window_start,
            "current_window_end": window_end,
            "window_size_seconds": self.time_window,
            "window_progress": f"{window_progress:.1%}",
            "time_remaining": max(0, window_end - current_time),
            "next_reset_in": max(0, window_end - current_time),
        }
