"""
Main RateLimiter class that orchestrates different algorithms and provides
a unified interface for rate limiting functionality.
"""

import asyncio
import threading
import time
from typing import Any, Dict, Optional, Union

from loguru import logger

from .algorithms import RateLimitAlgorithm, RateLimitResult, create_algorithm
from .exceptions import RateLimitConfigError, RateLimitExceededError
from .policies import RateLimitPolicy
from .stats import RateLimitStats


class RateLimiter:
    """
    Advanced rate limiter with multiple algorithm support and flexible policies.

    This is the main interface for rate limiting in the application. It provides
    a unified API that can use different algorithms and policies underneath.
    """

    def __init__(
        self,
        max_requests: int,
        time_window: int = 60,
        algorithm: str = "token_bucket",
        policy: Union[RateLimitPolicy, str] = RateLimitPolicy.WAIT,
        max_wait_time: float = 5.0,
        name: str = "default",
        burst_capacity: int = 0,
        **algorithm_kwargs,
    ):
        """
        Initialize the rate limiter.

        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds
            algorithm: Algorithm to use ('token_bucket', 'sliding_window', 'fixed_window')
            policy: How to handle rate limit exceeded
            max_wait_time: Maximum time to wait for a token (for WAIT policy)
            name: Name identifier for this rate limiter
            burst_capacity: Additional burst capacity (for token_bucket algorithm)
            **algorithm_kwargs: Additional algorithm-specific parameters
        """
        # Validate inputs
        if max_requests <= 0:
            raise RateLimitConfigError("max_requests must be positive")
        if time_window <= 0:
            raise RateLimitConfigError("time_window must be positive")
        if max_wait_time < 0:
            raise RateLimitConfigError("max_wait_time cannot be negative")

        self.max_requests = max_requests
        self.time_window = time_window
        self.max_wait_time = max_wait_time
        self.name = name

        # Convert string policy to enum if needed
        if isinstance(policy, str):
            try:
                self.policy = RateLimitPolicy(policy.lower())
            except ValueError:
                logger.warning(f"Invalid policy '{policy}', using WAIT")
                self.policy = RateLimitPolicy.WAIT
        else:
            self.policy = policy

        # Create the underlying algorithm
        try:
            # Add burst_capacity for token_bucket algorithm
            if algorithm == "token_bucket" and burst_capacity > 0:
                algorithm_kwargs["burst_capacity"] = burst_capacity

            self.algorithm = create_algorithm(
                algorithm,
                max_requests,
                time_window,
                name=f"{name}_{algorithm}",
                **algorithm_kwargs,
            )
        except ValueError as e:
            raise RateLimitConfigError(f"Failed to create algorithm: {e}")

        # Thread safety
        self.async_lock = asyncio.Lock()
        self.thread_lock = threading.RLock()

        # Statistics
        self.stats = RateLimitStats()

        # Per-client rate limiting
        self.enable_per_client = False
        self.per_client_max_requests = max_requests

        logger.info(
            f"RateLimiter '{name}' initialized: {max_requests} req/{time_window}s "
            f"using {algorithm} algorithm with {self.policy.value} policy"
        )

    def enable_client_tracking(
        self, per_client_max_requests: Optional[int] = None
    ) -> None:
        """
        Enable per-client rate limiting.

        Args:
            per_client_max_requests: Max requests per client (defaults to global limit)
        """
        self.enable_per_client = True
        self.per_client_max_requests = per_client_max_requests or self.max_requests
        logger.info(
            f"RateLimiter '{self.name}' enabled per-client tracking: "
            f"{self.per_client_max_requests} req/{self.time_window}s per client"
        )

    async def acquire_async(self, client_id: Optional[str] = None) -> bool:
        """
        Asynchronously acquire a token/request slot.

        Args:
            client_id: Optional client identifier for per-client rate limiting

        Returns:
            True if request is allowed, False if rejected

        Raises:
            RateLimitExceededError: If policy is STRICT and rate limit is exceeded
        """
        async with self.async_lock:
            return await self._acquire_internal(client_id, is_async=True)

    def acquire(
        self, client_id: Optional[str] = None, wait: Optional[bool] = None
    ) -> bool:
        """
        Synchronously acquire a token/request slot.

        Args:
            client_id: Optional client identifier for per-client rate limiting
            wait: Override policy to force waiting or not waiting

        Returns:
            True if request is allowed, False if rejected

        Raises:
            RateLimitExceededError: If policy is STRICT and rate limit is exceeded
        """
        with self.thread_lock:
            return self._acquire_sync(client_id, wait)

    async def _acquire_internal(
        self, client_id: Optional[str], is_async: bool = False
    ) -> bool:
        """Internal acquire logic that handles both sync and async cases."""
        start_time = time.time()

        # Use global algorithm or per-client logic
        effective_client_id = client_id or "global"

        # Try to acquire from algorithm
        result = (
            await self.algorithm.acquire_async(effective_client_id)
            if is_async
            else self.algorithm.acquire(effective_client_id)
        )

        if result.allowed:
            # Request allowed
            wait_time_ms = (time.time() - start_time) * 1000
            self.stats.record_request(allowed=True, wait_time_ms=wait_time_ms)
            return True

        # Request not allowed, handle according to policy
        if self.policy == RateLimitPolicy.STRICT:
            # Strict policy: reject immediately
            self.stats.record_request(allowed=False)
            raise RateLimitExceededError(
                f"Rate limit exceeded: {self.max_requests} requests per {self.time_window} seconds",
                retry_after=result.retry_after,
                limit=self.max_requests,
                window=self.time_window,
            )

        elif self.policy == RateLimitPolicy.WAIT:
            # Wait policy: wait for token to become available
            wait_time = min(result.retry_after, self.max_wait_time)

            if wait_time > self.max_wait_time:
                logger.warning(
                    f"Wait time {wait_time:.2f}s exceeds maximum {self.max_wait_time:.2f}s"
                )
                self.stats.record_request(allowed=False)
                return False

            if wait_time > 0:
                logger.debug(f"Waiting {wait_time:.2f}s for token availability")
                if is_async:
                    await asyncio.sleep(wait_time)
                else:
                    time.sleep(wait_time)

            # Try again after waiting
            result = (
                await self.algorithm.acquire_async(effective_client_id)
                if is_async
                else self.algorithm.acquire(effective_client_id)
            )

            total_wait_time_ms = (time.time() - start_time) * 1000
            self.stats.record_request(
                allowed=result.allowed, throttled=True, wait_time_ms=total_wait_time_ms
            )

            return result.allowed

        elif self.policy == RateLimitPolicy.THROTTLE:
            # Throttle policy: introduce partial delay
            wait_time = min(result.retry_after / 2, self.max_wait_time)

            if wait_time > 0:
                logger.debug(f"Throttling request with {wait_time:.2f}s delay")
                if is_async:
                    await asyncio.sleep(wait_time)
                else:
                    time.sleep(wait_time)

            total_wait_time_ms = (time.time() - start_time) * 1000
            self.stats.record_request(
                allowed=True, throttled=True, wait_time_ms=total_wait_time_ms
            )
            return True

        # Unknown policy
        logger.error(f"Unknown rate limit policy: {self.policy}")
        self.stats.record_request(allowed=False)
        return False

    def _acquire_sync(self, client_id: Optional[str], wait: Optional[bool]) -> bool:
        """Synchronous acquire implementation."""
        # Temporarily override policy if wait parameter is provided
        original_policy = self.policy
        if wait is not None:
            self.policy = RateLimitPolicy.WAIT if wait else RateLimitPolicy.STRICT

        try:
            # Use the async implementation but run it synchronously
            loop = None
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're in an async context, create a new thread
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(self._acquire_sync_internal, client_id)
                        return future.result()
                else:
                    return loop.run_until_complete(
                        self._acquire_internal(client_id, is_async=False)
                    )
            except RuntimeError:
                # No event loop, run directly
                return self._acquire_sync_internal(client_id)
        finally:
            # Restore original policy
            self.policy = original_policy

    def _acquire_sync_internal(self, client_id: Optional[str]) -> bool:
        """Pure synchronous implementation without asyncio."""
        start_time = time.time()
        effective_client_id = client_id or "global"

        # Try to acquire from algorithm
        result = self.algorithm.acquire(effective_client_id)

        if result.allowed:
            wait_time_ms = (time.time() - start_time) * 1000
            self.stats.record_request(allowed=True, wait_time_ms=wait_time_ms)
            return True

        # Handle based on policy
        if self.policy == RateLimitPolicy.STRICT:
            self.stats.record_request(allowed=False)
            raise RateLimitExceededError(
                f"Rate limit exceeded: {self.max_requests} requests per {self.time_window} seconds",
                retry_after=result.retry_after,
                limit=self.max_requests,
                window=self.time_window,
            )

        elif self.policy == RateLimitPolicy.WAIT:
            wait_time = min(result.retry_after, self.max_wait_time)

            if wait_time > self.max_wait_time:
                self.stats.record_request(allowed=False)
                return False

            if wait_time > 0:
                time.sleep(wait_time)

            # Try again
            result = self.algorithm.acquire(effective_client_id)
            total_wait_time_ms = (time.time() - start_time) * 1000
            self.stats.record_request(
                allowed=result.allowed, throttled=True, wait_time_ms=total_wait_time_ms
            )
            return result.allowed

        elif self.policy == RateLimitPolicy.THROTTLE:
            wait_time = min(result.retry_after / 2, self.max_wait_time)

            if wait_time > 0:
                time.sleep(wait_time)

            total_wait_time_ms = (time.time() - start_time) * 1000
            self.stats.record_request(
                allowed=True, throttled=True, wait_time_ms=total_wait_time_ms
            )
            return True

        self.stats.record_request(allowed=False)
        return False

    def get_stats(self, client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get rate limiter statistics.

        Args:
            client_id: Optional client ID to get client-specific stats

        Returns:
            Dictionary with statistics
        """
        with self.thread_lock:
            # Get base statistics
            stats = self.stats.to_dict()

            # Add limiter information
            stats.update(
                {
                    "name": self.name,
                    "algorithm": self.algorithm.__class__.__name__,
                    "limit": self.max_requests,
                    "time_window": self.time_window,
                    "policy": self.policy.value,
                    "max_wait_time": self.max_wait_time,
                    "per_client_enabled": self.enable_per_client,
                }
            )

            # Add algorithm-specific stats
            algo_stats = self.algorithm.get_algorithm_stats()
            stats["algorithm_stats"] = algo_stats

            # Add client-specific stats if requested
            if client_id:
                effective_client_id = client_id if self.enable_per_client else "global"
                client_result = self.algorithm.get_stats(effective_client_id)
                stats["client_stats"] = {
                    "client_id": client_id,
                    "allowed": client_result.allowed,
                    "remaining": client_result.remaining,
                    "reset_time": client_result.reset_time,
                    "retry_after": client_result.retry_after,
                    "current_usage": client_result.current_usage,
                }

            return stats

    def reset(self, client_id: Optional[str] = None) -> None:
        """
        Reset rate limiter state.

        Args:
            client_id: Optional client ID to reset specific client, or None for all
        """
        with self.thread_lock:
            if client_id:
                effective_client_id = client_id if self.enable_per_client else "global"
                self.algorithm.reset_client(effective_client_id)
                logger.info(
                    f"Reset rate limiter '{self.name}' for client '{client_id}'"
                )
            else:
                self.algorithm.reset_all()
                self.stats.reset()
                logger.info(f"Reset rate limiter '{self.name}' completely")

    def cleanup_expired_clients(self, max_age: int = 3600) -> int:
        """
        Clean up data for clients that haven't been seen recently.

        Args:
            max_age: Maximum age in seconds for client data

        Returns:
            Number of clients cleaned up
        """
        with self.thread_lock:
            cleaned = self.algorithm.cleanup_expired_clients(max_age)
            if cleaned > 0:
                logger.debug(f"Cleaned up {cleaned} expired clients from '{self.name}'")
            return cleaned
