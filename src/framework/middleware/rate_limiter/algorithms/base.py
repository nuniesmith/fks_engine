"""
Abstract base class for all rate limiting algorithms.
"""

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    reset_time: float
    retry_after: float
    total_limit: int
    current_usage: int


class RateLimitAlgorithm(ABC):
    """
    Abstract base class for rate limiting algorithms.

    All rate limiting algorithms must implement this interface to ensure
    consistency across the system.
    """

    def __init__(self, max_requests: int, time_window: int, name: str = "algorithm"):
        """
        Initialize the rate limiting algorithm.

        Args:
            max_requests: Maximum number of requests allowed
            time_window: Time window in seconds
            name: Name identifier for this algorithm instance
        """
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if time_window <= 0:
            raise ValueError("time_window must be positive")

        self.max_requests = max_requests
        self.time_window = time_window
        self.name = name
        self.created_at = time.time()

        # Thread safety
        self._lock = threading.RLock()

        # Per-client storage
        self._client_data: Dict[str, Dict[str, Any]] = {}

        # Statistics
        self.total_requests = 0
        self.allowed_requests = 0
        self.denied_requests = 0

    @abstractmethod
    def _check_limit(self, client_id: str, current_time: float) -> RateLimitResult:
        """
        Check if a request should be allowed for a specific client.

        This is the core algorithm implementation that each subclass must provide.

        Args:
            client_id: Unique identifier for the client
            current_time: Current timestamp

        Returns:
            RateLimitResult with the decision and metadata
        """
        pass

    @abstractmethod
    def _consume_token(self, client_id: str, current_time: float) -> bool:
        """
        Consume a token/request slot for the client.

        Args:
            client_id: Unique identifier for the client
            current_time: Current timestamp

        Returns:
            True if token was consumed, False otherwise
        """
        pass

    @abstractmethod
    def _get_client_data(self, client_id: str) -> Dict[str, Any]:
        """
        Get or initialize data structure for a client.

        Args:
            client_id: Unique identifier for the client

        Returns:
            Client-specific data dictionary
        """
        pass

    def acquire(self, client_id: str) -> RateLimitResult:
        """
        Attempt to acquire a request slot for the client.

        Args:
            client_id: Unique identifier for the client

        Returns:
            RateLimitResult indicating whether the request was allowed
        """
        with self._lock:
            current_time = time.time()
            self.total_requests += 1

            # Check if request is allowed
            result = self._check_limit(client_id, current_time)

            if result.allowed:
                # Consume a token/slot
                success = self._consume_token(client_id, current_time)
                if success:
                    self.allowed_requests += 1
                else:
                    # This shouldn't happen if _check_limit was correct
                    result.allowed = False
                    self.denied_requests += 1
            else:
                self.denied_requests += 1

            return result

    async def acquire_async(self, client_id: str) -> RateLimitResult:
        """
        Asynchronous version of acquire.

        For most algorithms, this is just a wrapper around the sync version.
        Subclasses can override for truly async implementations.

        Args:
            client_id: Unique identifier for the client

        Returns:
            RateLimitResult indicating whether the request was allowed
        """
        return self.acquire(client_id)

    def get_stats(self, client_id: str) -> RateLimitResult:
        """
        Get current rate limit status for a client without consuming a token.

        Args:
            client_id: Unique identifier for the client

        Returns:
            RateLimitResult with current status
        """
        with self._lock:
            current_time = time.time()
            return self._check_limit(client_id, current_time)

    def reset_client(self, client_id: str) -> None:
        """
        Reset rate limit data for a specific client.

        Args:
            client_id: Unique identifier for the client
        """
        with self._lock:
            if client_id in self._client_data:
                del self._client_data[client_id]

    def reset_all(self) -> None:
        """Reset rate limit data for all clients."""
        with self._lock:
            self._client_data.clear()
            self.total_requests = 0
            self.allowed_requests = 0
            self.denied_requests = 0

    def cleanup_expired_clients(self, max_age: int = 3600) -> int:
        """
        Clean up data for clients that haven't been seen recently.

        Args:
            max_age: Maximum age in seconds for client data

        Returns:
            Number of clients cleaned up
        """
        current_time = time.time()
        cutoff_time = current_time - max_age
        expired_clients = []

        with self._lock:
            for client_id, data in self._client_data.items():
                # Each algorithm should store 'last_seen' in client data
                last_seen = data.get("last_seen", 0)
                if last_seen < cutoff_time:
                    expired_clients.append(client_id)

            for client_id in expired_clients:
                del self._client_data[client_id]

        return len(expired_clients)

    def get_algorithm_stats(self) -> Dict[str, Any]:
        """Get statistics about this algorithm instance."""
        with self._lock:
            uptime = time.time() - self.created_at
            success_rate = 0.0
            if self.total_requests > 0:
                success_rate = self.allowed_requests / self.total_requests

            return {
                "name": self.name,
                "algorithm": self.__class__.__name__,
                "max_requests": self.max_requests,
                "time_window": self.time_window,
                "total_requests": self.total_requests,
                "allowed_requests": self.allowed_requests,
                "denied_requests": self.denied_requests,
                "success_rate": f"{success_rate:.2%}",
                "active_clients": len(self._client_data),
                "uptime_seconds": uptime,
            }

    def _update_last_seen(self, client_id: str, current_time: float) -> None:
        """Update the last seen time for a client."""
        client_data = self._get_client_data(client_id)
        client_data["last_seen"] = current_time
