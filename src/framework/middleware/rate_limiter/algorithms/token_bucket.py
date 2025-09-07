"""
Token bucket rate limiting algorithm implementation.
"""

import time
from typing import Any, Dict

from .base import RateLimitAlgorithm, RateLimitResult


class TokenBucketAlgorithm(RateLimitAlgorithm):
    """
    Token bucket rate limiting algorithm.

    This algorithm maintains a bucket of tokens for each client. Tokens are added
    at a constant rate up to the bucket capacity. Each request consumes one token.
    When the bucket is empty, requests are denied.

    This algorithm allows for bursty traffic while maintaining an average rate limit.
    """

    def __init__(
        self,
        max_requests: int,
        time_window: int,
        burst_capacity: int = 0,
        name: str = "token_bucket",
    ):
        """
        Initialize token bucket algorithm.

        Args:
            max_requests: Maximum number of requests allowed per time window
            time_window: Time window in seconds
            burst_capacity: Additional burst capacity beyond the rate limit
            name: Name identifier for this algorithm instance
        """
        super().__init__(max_requests, time_window, name)
        self.burst_capacity = max(0, burst_capacity)
        self.bucket_capacity = max_requests + self.burst_capacity
        self.refill_rate = max_requests / time_window  # tokens per second

    def _get_client_data(self, client_id: str) -> Dict[str, Any]:
        """Get or initialize token bucket data for a client."""
        if client_id not in self._client_data:
            current_time = time.time()
            self._client_data[client_id] = {
                "tokens": float(self.bucket_capacity),  # Start with full bucket
                "last_refill": current_time,
                "last_seen": current_time,
            }
        return self._client_data[client_id]

    def _refill_bucket(self, client_data: Dict[str, Any], current_time: float) -> None:
        """Refill the token bucket based on elapsed time."""
        time_passed = current_time - client_data["last_refill"]
        if time_passed > 0:
            # Calculate tokens to add
            tokens_to_add = time_passed * self.refill_rate

            # Add tokens, but don't exceed capacity
            client_data["tokens"] = min(
                self.bucket_capacity, client_data["tokens"] + tokens_to_add
            )

            client_data["last_refill"] = current_time

    def _check_limit(self, client_id: str, current_time: float) -> RateLimitResult:
        """Check if a request should be allowed for a client."""
        client_data = self._get_client_data(client_id)
        self._refill_bucket(client_data, current_time)
        self._update_last_seen(client_id, current_time)

        # Check if we have at least one token
        allowed = client_data["tokens"] >= 1.0
        remaining = int(client_data["tokens"])
        current_usage = self.bucket_capacity - int(client_data["tokens"])

        # Calculate when the next token will be available
        if client_data["tokens"] < 1.0:
            # Need to wait for a token
            tokens_needed = 1.0 - client_data["tokens"]
            time_to_next_token = tokens_needed / self.refill_rate
            retry_after = time_to_next_token
            reset_time = current_time + time_to_next_token
        else:
            # Tokens available
            retry_after = 0.0
            # Calculate when bucket will be empty at current rate
            time_to_empty = client_data["tokens"] / self.refill_rate
            reset_time = current_time + time_to_empty

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            reset_time=reset_time,
            retry_after=retry_after,
            total_limit=self.bucket_capacity,
            current_usage=current_usage,
        )

    def _consume_token(self, client_id: str, current_time: float) -> bool:
        """Consume a token from the client's bucket."""
        client_data = self._get_client_data(client_id)

        if client_data["tokens"] >= 1.0:
            client_data["tokens"] -= 1.0
            return True

        return False

    def get_bucket_info(self, client_id: str) -> Dict[str, Any]:
        """
        Get detailed bucket information for a client.

        Args:
            client_id: Unique identifier for the client

        Returns:
            Dictionary with bucket details
        """
        with self._lock:
            current_time = time.time()
            client_data = self._get_client_data(client_id)
            self._refill_bucket(client_data, current_time)

            return {
                "client_id": client_id,
                "current_tokens": client_data["tokens"],
                "bucket_capacity": self.bucket_capacity,
                "refill_rate_per_second": self.refill_rate,
                "last_refill": client_data["last_refill"],
                "time_since_refill": current_time - client_data["last_refill"],
            }
