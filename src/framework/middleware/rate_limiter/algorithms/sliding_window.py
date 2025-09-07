"""
Sliding window rate limiting algorithm implementation.
"""

import time
from collections import deque
from typing import Any, Deque, Dict

from .base import RateLimitAlgorithm, RateLimitResult


class SlidingWindowAlgorithm(RateLimitAlgorithm):
    """
    Sliding window rate limiting algorithm.

    This algorithm maintains a sliding time window of requests for each client.
    It tracks the exact timestamps of requests and removes old requests as the
    window slides forward. This provides precise rate limiting but uses more
    memory than other algorithms.

    Best for: Scenarios requiring precise rate limiting with smooth distribution.
    """

    def __init__(
        self, max_requests: int, time_window: int, name: str = "sliding_window"
    ):
        """
        Initialize sliding window algorithm.

        Args:
            max_requests: Maximum number of requests allowed per time window
            time_window: Time window in seconds
            name: Name identifier for this algorithm instance
        """
        super().__init__(max_requests, time_window, name)

    def _get_client_data(self, client_id: str) -> Dict[str, Any]:
        """Get or initialize sliding window data for a client."""
        if client_id not in self._client_data:
            current_time = time.time()
            self._client_data[client_id] = {
                "requests": deque(),  # Store request timestamps
                "last_seen": current_time,
            }
        return self._client_data[client_id]

    def _clean_window(self, requests: Deque[float], current_time: float) -> None:
        """Remove requests that fall outside the current time window."""
        cutoff_time = current_time - self.time_window

        # Remove old requests from the left side of the deque
        while requests and requests[0] < cutoff_time:
            requests.popleft()

    def _check_limit(self, client_id: str, current_time: float) -> RateLimitResult:
        """Check if a request should be allowed for a client."""
        client_data = self._get_client_data(client_id)
        requests = client_data["requests"]

        # Clean old requests
        self._clean_window(requests, current_time)
        self._update_last_seen(client_id, current_time)

        # Check if we're under the limit
        current_count = len(requests)
        allowed = current_count < self.max_requests
        remaining = max(0, self.max_requests - current_count)

        # Calculate reset time and retry_after
        if requests:
            # Find the oldest request that would need to expire for a new request
            if current_count >= self.max_requests:
                oldest_request = requests[0]
                reset_time = oldest_request + self.time_window
                retry_after = max(0, reset_time - current_time)
            else:
                # We have capacity, so reset time is when oldest request expires
                oldest_request = requests[0]
                reset_time = oldest_request + self.time_window
                retry_after = 0.0
        else:
            # No requests in window
            reset_time = current_time + self.time_window
            retry_after = 0.0

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            reset_time=reset_time,
            retry_after=retry_after,
            total_limit=self.max_requests,
            current_usage=current_count,
        )

    def _consume_token(self, client_id: str, current_time: float) -> bool:
        """Add the current request to the sliding window."""
        client_data = self._get_client_data(client_id)
        requests = client_data["requests"]

        # Clean the window first
        self._clean_window(requests, current_time)

        # Check if we can add this request
        if len(requests) < self.max_requests:
            requests.append(current_time)
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
            requests = client_data["requests"]

            # Clean the window
            self._clean_window(requests, current_time)

            # Calculate request distribution
            if requests:
                oldest_request = requests[0]
                newest_request = requests[-1]
                window_span = newest_request - oldest_request

                # Calculate requests per second in current window
                if window_span > 0:
                    current_rate = len(requests) / window_span
                else:
                    current_rate = 0.0
            else:
                oldest_request = None
                newest_request = None
                window_span = 0.0
                current_rate = 0.0

            return {
                "client_id": client_id,
                "current_requests": len(requests),
                "max_requests": self.max_requests,
                "time_window": self.time_window,
                "oldest_request": oldest_request,
                "newest_request": newest_request,
                "window_span": window_span,
                "current_rate_per_second": current_rate,
                "requests_timeline": list(requests)[-10:],  # Last 10 requests
            }

    def cleanup_expired_clients(self, max_age: int = 3600) -> int:
        """
        Clean up expired clients and their sliding windows.

        This override also cleans up empty request deques to save memory.
        """
        cleaned_count = super().cleanup_expired_clients(max_age)

        # Also clean up clients with empty request windows
        current_time = time.time()
        empty_clients = []

        with self._lock:
            for client_id, data in self._client_data.items():
                requests = data["requests"]
                self._clean_window(requests, current_time)

                # If no requests in window and not seen recently, mark for cleanup
                if (
                    not requests and (current_time - data.get("last_seen", 0)) > 300
                ):  # 5 minutes
                    empty_clients.append(client_id)

            for client_id in empty_clients:
                del self._client_data[client_id]

        return cleaned_count + len(empty_clients)
