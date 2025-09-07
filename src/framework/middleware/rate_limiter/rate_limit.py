"""
Rate limiting middleware for API request throttling.

This module provides a complete rate limiting implementation with multiple algorithms,
client identification strategies, and comprehensive monitoring capabilities.
"""

import asyncio
import hashlib
import os
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock, RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


# Rate limiting exceptions
class RateLimitError(Exception):
    """Base rate limiting error."""

    pass


class RateLimitExceededError(RateLimitError):
    """Rate limit exceeded error."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimitConfigError(RateLimitError):
    """Rate limit configuration error."""

    pass


# Rate limiting algorithms
class RateLimitAlgorithm(Enum):
    """Available rate limiting algorithms."""

    TOKEN_BUCKET = "token_bucket"
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"
    SLIDING_LOG = "sliding_log"


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    reset_time: float
    retry_after: int
    total_requests: int


class RateLimiter(ABC):
    """Abstract base class for rate limiters."""

    def __init__(self, requests: int, window_seconds: int, identifier: str = "default"):
        self.requests = requests
        self.window_seconds = window_seconds
        self.identifier = identifier
        self.created_at = time.time()
        self._lock = RLock()

        # Statistics
        self.total_requests = 0
        self.allowed_requests = 0
        self.denied_requests = 0

    @abstractmethod
    async def acquire_async(self, client_id: str) -> bool:
        """
        Try to acquire permission for a request asynchronously.

        Args:
            client_id: Client identifier

        Returns:
            bool: True if request is allowed, False if rate limited
        """
        pass

    @abstractmethod
    def acquire(self, client_id: str) -> bool:
        """
        Try to acquire permission for a request synchronously.

        Args:
            client_id: Client identifier

        Returns:
            bool: True if request is allowed, False if rate limited
        """
        pass

    @abstractmethod
    def get_stats(self, client_id: str) -> RateLimitResult:
        """
        Get rate limit statistics for a client.

        Args:
            client_id: Client identifier

        Returns:
            RateLimitResult: Current rate limit status
        """
        pass

    @abstractmethod
    def reset(self, client_id: Optional[str] = None) -> None:
        """
        Reset rate limit data.

        Args:
            client_id: Client to reset, or None for all clients
        """
        pass

    def get_limiter_stats(self) -> Dict[str, Any]:
        """Get overall limiter statistics."""
        return {
            "identifier": self.identifier,
            "requests_per_window": self.requests,
            "window_seconds": self.window_seconds,
            "algorithm": self.__class__.__name__,
            "total_requests": self.total_requests,
            "allowed_requests": self.allowed_requests,
            "denied_requests": self.denied_requests,
            "success_rate": (
                self.allowed_requests / self.total_requests
                if self.total_requests > 0
                else 1.0
            ),
            "uptime_seconds": time.time() - self.created_at,
        }


class TokenBucketRateLimiter(RateLimiter):
    """Token bucket rate limiting algorithm."""

    def __init__(
        self, requests: int, window_seconds: int, identifier: str = "token_bucket"
    ):
        super().__init__(requests, window_seconds, identifier)
        self.buckets: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"tokens": float(requests), "last_refill": time.time()}
        )
        self.refill_rate = requests / window_seconds  # tokens per second

    def _refill_bucket(self, client_id: str) -> None:
        """Refill the token bucket for a client."""
        bucket = self.buckets[client_id]
        now = time.time()
        time_passed = now - bucket["last_refill"]

        # Add tokens based on time passed
        tokens_to_add = time_passed * self.refill_rate
        bucket["tokens"] = min(self.requests, bucket["tokens"] + tokens_to_add)
        bucket["last_refill"] = now

    async def acquire_async(self, client_id: str) -> bool:
        """Acquire a token asynchronously."""
        return self.acquire(client_id)

    def acquire(self, client_id: str) -> bool:
        """Acquire a token synchronously."""
        with self._lock:
            self.total_requests += 1
            self._refill_bucket(client_id)

            bucket = self.buckets[client_id]
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                self.allowed_requests += 1
                return True
            else:
                self.denied_requests += 1
                return False

    def get_stats(self, client_id: str) -> RateLimitResult:
        """Get rate limit statistics."""
        with self._lock:
            self._refill_bucket(client_id)
            bucket = self.buckets[client_id]

            remaining = int(bucket["tokens"])
            time_to_refill = (
                (1 - (bucket["tokens"] % 1)) / self.refill_rate
                if bucket["tokens"] < self.requests
                else 0
            )
            reset_time = time.time() + time_to_refill

            return RateLimitResult(
                allowed=bucket["tokens"] >= 1,
                remaining=remaining,
                reset_time=reset_time,
                retry_after=int(time_to_refill) + 1,
                total_requests=self.requests,
            )

    def reset(self, client_id: Optional[str] = None) -> None:
        """Reset bucket data."""
        with self._lock:
            if client_id:
                if client_id in self.buckets:
                    del self.buckets[client_id]
            else:
                self.buckets.clear()


class SlidingWindowRateLimiter(RateLimiter):
    """Sliding window rate limiting algorithm."""

    def __init__(
        self, requests: int, window_seconds: int, identifier: str = "sliding_window"
    ):
        super().__init__(requests, window_seconds, identifier)
        self.windows: Dict[str, deque] = defaultdict(lambda: deque())

    def _clean_window(self, client_id: str) -> None:
        """Remove old requests from the sliding window."""
        window = self.windows[client_id]
        cutoff_time = time.time() - self.window_seconds

        while window and window[0] < cutoff_time:
            window.popleft()

    async def acquire_async(self, client_id: str) -> bool:
        """Acquire permission asynchronously."""
        return self.acquire(client_id)

    def acquire(self, client_id: str) -> bool:
        """Acquire permission synchronously."""
        with self._lock:
            self.total_requests += 1
            self._clean_window(client_id)

            window = self.windows[client_id]
            if len(window) < self.requests:
                window.append(time.time())
                self.allowed_requests += 1
                return True
            else:
                self.denied_requests += 1
                return False

    def get_stats(self, client_id: str) -> RateLimitResult:
        """Get rate limit statistics."""
        with self._lock:
            self._clean_window(client_id)
            window = self.windows[client_id]

            remaining = self.requests - len(window)
            oldest_request = window[0] if window else time.time()
            reset_time = oldest_request + self.window_seconds
            retry_after = max(0, int(reset_time - time.time()))

            return RateLimitResult(
                allowed=remaining > 0,
                remaining=remaining,
                reset_time=reset_time,
                retry_after=retry_after,
                total_requests=self.requests,
            )

    def reset(self, client_id: Optional[str] = None) -> None:
        """Reset window data."""
        with self._lock:
            if client_id:
                if client_id in self.windows:
                    self.windows[client_id].clear()
            else:
                for window in self.windows.values():
                    window.clear()


class FixedWindowRateLimiter(RateLimiter):
    """Fixed window rate limiting algorithm."""

    def __init__(
        self, requests: int, window_seconds: int, identifier: str = "fixed_window"
    ):
        super().__init__(requests, window_seconds, identifier)
        self.windows: Dict[str, Dict[str, Union[int, float]]] = defaultdict(
            lambda: {"count": 0, "window_start": self._get_current_window()}
        )

    def _get_current_window(self) -> float:
        """Get the current window start time."""
        return int(time.time() // self.window_seconds) * self.window_seconds

    def _reset_window_if_needed(self, client_id: str) -> None:
        """Reset window if we're in a new time window."""
        current_window = self._get_current_window()
        window_data = self.windows[client_id]

        if window_data["window_start"] < current_window:
            window_data["count"] = 0
            window_data["window_start"] = current_window

    async def acquire_async(self, client_id: str) -> bool:
        """Acquire permission asynchronously."""
        return self.acquire(client_id)

    def acquire(self, client_id: str) -> bool:
        """Acquire permission synchronously."""
        with self._lock:
            self.total_requests += 1
            self._reset_window_if_needed(client_id)

            window_data = self.windows[client_id]
            if window_data["count"] < self.requests:
                window_data["count"] += 1
                self.allowed_requests += 1
                return True
            else:
                self.denied_requests += 1
                return False

    def get_stats(self, client_id: str) -> RateLimitResult:
        """Get rate limit statistics."""
        with self._lock:
            self._reset_window_if_needed(client_id)
            window_data = self.windows[client_id]

            remaining = self.requests - window_data["count"]
            reset_time = window_data["window_start"] + self.window_seconds
            retry_after = max(0, int(reset_time - time.time()))

            return RateLimitResult(
                allowed=remaining > 0,
                remaining=remaining,
                reset_time=reset_time,
                retry_after=retry_after,
                total_requests=self.requests,
            )

    def reset(self, client_id: Optional[str] = None) -> None:
        """Reset window data."""
        with self._lock:
            current_window = self._get_current_window()
            if client_id:
                if client_id in self.windows:
                    self.windows[client_id] = {
                        "count": 0,
                        "window_start": current_window,
                    }
            else:
                for client in self.windows:
                    self.windows[client] = {"count": 0, "window_start": current_window}


# Rate limiter registry
class RateLimiterRegistry:
    """Registry for managing multiple rate limiters."""

    def __init__(self):
        self.limiters: Dict[str, RateLimiter] = {}
        self._lock = Lock()

    def register(self, name: str, limiter: RateLimiter) -> None:
        """Register a rate limiter."""
        with self._lock:
            self.limiters[name] = limiter
            logger.debug(f"Registered rate limiter: {name}")

    def get(self, name: str) -> RateLimiter:
        """Get a rate limiter by name."""
        with self._lock:
            if name not in self.limiters:
                raise KeyError(f"Rate limiter not found: {name}")
            return self.limiters[name]

    def exists(self, name: str) -> bool:
        """Check if a rate limiter exists."""
        with self._lock:
            return name in self.limiters

    def remove(self, name: str) -> bool:
        """Remove a rate limiter."""
        with self._lock:
            if name in self.limiters:
                del self.limiters[name]
                logger.debug(f"Removed rate limiter: {name}")
                return True
            return False

    def list_limiters(self) -> List[str]:
        """Get list of registered limiter names."""
        with self._lock:
            return list(self.limiters.keys())

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all limiters."""
        with self._lock:
            return {
                name: limiter.get_limiter_stats()
                for name, limiter in self.limiters.items()
            }

    def clear(self) -> None:
        """Clear all limiters."""
        with self._lock:
            self.limiters.clear()
            logger.debug("Cleared all rate limiters")


# Global registry instance
_rate_limiter_registry = RateLimiterRegistry()


def register_rate_limiter(
    name: str,
    requests: int,
    window_seconds: int,
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET,
) -> RateLimiter:
    """
    Register a new rate limiter.

    Args:
        name: Unique name for the limiter
        requests: Number of requests allowed
        window_seconds: Time window in seconds
        algorithm: Rate limiting algorithm to use

    Returns:
        RateLimiter: The created rate limiter
    """
    if algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
        limiter = TokenBucketRateLimiter(requests, window_seconds, name)
    elif algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
        limiter = SlidingWindowRateLimiter(requests, window_seconds, name)
    elif algorithm == RateLimitAlgorithm.FIXED_WINDOW:
        limiter = FixedWindowRateLimiter(requests, window_seconds, name)
    else:
        raise RateLimitConfigError(f"Unknown algorithm: {algorithm}")

    _rate_limiter_registry.register(name, limiter)
    return limiter


def get_rate_limiter(name: str) -> RateLimiter:
    """Get a rate limiter by name."""
    return _rate_limiter_registry.get(name)


def remove_rate_limiter(name: str) -> bool:
    """Remove a rate limiter."""
    return _rate_limiter_registry.remove(name)


# Client identification strategies
class ClientIdentifier:
    """Utilities for identifying clients for rate limiting."""

    @staticmethod
    def get_client_ip(request: Request) -> str:
        """Get client IP address."""
        # Check for forwarded headers first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        # Fallback to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    @staticmethod
    def get_api_key(request: Request, header_name: str = "X-API-Key") -> Optional[str]:
        """Get API key from request headers."""
        return request.headers.get(header_name)

    @staticmethod
    def get_user_id(request: Request) -> Optional[str]:
        """Get user ID from authenticated request."""
        # Try to get from request state (set by auth middleware)
        user_info = getattr(request.state, "user", None)
        if user_info:
            return getattr(user_info, "user_id", None)

        # Try to get from token payload
        token_payload = getattr(request.state, "token_payload", None)
        if token_payload:
            return token_payload.get("sub")

        return None

    @staticmethod
    def create_composite_id(request: Request, components: List[str]) -> str:
        """Create a composite client ID from multiple components."""
        id_parts = []

        for component in components:
            if component == "ip":
                id_parts.append(ClientIdentifier.get_client_ip(request))
            elif component == "user":
                user_id = ClientIdentifier.get_user_id(request)
                id_parts.append(user_id or "anonymous")
            elif component == "api_key":
                api_key = ClientIdentifier.get_api_key(request)
                id_parts.append(api_key or "no_key")
            elif component == "endpoint":
                id_parts.append(request.url.path)
            else:
                # Custom header or attribute
                value = request.headers.get(component, "unknown")
                id_parts.append(value)

        # Create a hash for consistent length
        composite_id = ":".join(id_parts)
        return hashlib.sha256(composite_id.encode()).hexdigest()[:16]


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    requests: int = 100
    window_seconds: int = 60
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
    client_id_components: List[str] = field(default_factory=lambda: ["ip"])
    exclude_paths: List[str] = field(
        default_factory=lambda: ["/health", "/docs", "/openapi.json"]
    )
    api_key_header: str = "X-API-Key"
    api_key_multiplier: float = 5.0  # API key users get 5x limit
    custom_limits: Dict[str, Tuple[int, int]] = field(
        default_factory=dict
    )  # path -> (requests, window)
    enable_headers: bool = True  # Include rate limit headers in response
    log_violations: bool = True
    fail_open: bool = True  # Allow requests if rate limiter fails


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive rate limiting middleware.

    Features:
    - Multiple rate limiting algorithms
    - Flexible client identification
    - Route-specific limits
    - API key-based limits
    - Comprehensive monitoring
    - Error resilience
    """

    def __init__(self, app: ASGIApp, config: Optional[RateLimitConfig] = None):
        """
        Initialize rate limiting middleware.

        Args:
            app: ASGI application
            config: Rate limiting configuration
        """
        super().__init__(app)
        self.config = config or RateLimitConfig()

        # Initialize rate limiters
        self._setup_limiters()

        # Statistics
        self.stats = {
            "total_requests": 0,
            "allowed_requests": 0,
            "denied_requests": 0,
            "errors": 0,
        }
        self._stats_lock = Lock()

        logger.info(
            f"Rate limiting middleware initialized with {self.config.algorithm.value} algorithm"
        )

    def _setup_limiters(self) -> None:
        """Setup the required rate limiters."""
        # Global rate limiter
        if not _rate_limiter_registry.exists("global"):
            register_rate_limiter(
                "global",
                self.config.requests,
                self.config.window_seconds,
                self.config.algorithm,
            )

        # API key rate limiter (higher limits)
        if not _rate_limiter_registry.exists("api_key"):
            api_key_requests = int(
                self.config.requests * self.config.api_key_multiplier
            )
            register_rate_limiter(
                "api_key",
                api_key_requests,
                self.config.window_seconds,
                self.config.algorithm,
            )

        # Route-specific limiters
        for path, (requests, window) in self.config.custom_limits.items():
            limiter_name = f"route:{path}"
            if not _rate_limiter_registry.exists(limiter_name):
                register_rate_limiter(
                    limiter_name, requests, window, self.config.algorithm
                )

    def _should_exclude(self, path: str) -> bool:
        """Check if path should be excluded from rate limiting."""
        return any(path.startswith(excluded) for excluded in self.config.exclude_paths)

    def _get_client_id(self, request: Request) -> str:
        """Get client identifier for rate limiting."""
        return ClientIdentifier.create_composite_id(
            request, self.config.client_id_components
        )

    def _get_limiter_for_request(self, request: Request) -> Tuple[RateLimiter, str]:
        """Determine which rate limiter to use for the request."""
        path = request.url.path

        # Check for route-specific limiter first
        for custom_path in self.config.custom_limits:
            if path.startswith(custom_path):
                limiter_name = f"route:{custom_path}"
                try:
                    limiter = get_rate_limiter(limiter_name)
                    client_id = f"{self._get_client_id(request)}:{custom_path}"
                    return limiter, client_id
                except KeyError:
                    break

        # Check for API key
        api_key = ClientIdentifier.get_api_key(request, self.config.api_key_header)
        if api_key:
            try:
                limiter = get_rate_limiter("api_key")
                return limiter, api_key
            except KeyError:
                pass

        # Use global limiter
        try:
            limiter = get_rate_limiter("global")
            client_id = self._get_client_id(request)
            return limiter, client_id
        except KeyError:
            # This shouldn't happen, but let's be safe
            limiter = register_rate_limiter(
                "fallback",
                self.config.requests,
                self.config.window_seconds,
                self.config.algorithm,
            )
            return limiter, self._get_client_id(request)

    def _create_rate_limit_response(
        self, stats: RateLimitResult, message: str = None
    ) -> JSONResponse:
        """Create a rate limit exceeded response."""
        content = {
            "error": {
                "code": "rate_limit_exceeded",
                "message": message or "Rate limit exceeded. Please try again later.",
                "retry_after": stats.retry_after,
            }
        }

        headers = {
            "Retry-After": str(stats.retry_after),
            "X-RateLimit-Limit": str(stats.total_requests),
            "X-RateLimit-Remaining": str(stats.remaining),
            "X-RateLimit-Reset": str(int(stats.reset_time)),
        }

        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=content,
            headers=headers,
        )

    def _add_rate_limit_headers(
        self, response: Response, stats: RateLimitResult
    ) -> None:
        """Add rate limit headers to response."""
        if self.config.enable_headers:
            response.headers["X-RateLimit-Limit"] = str(stats.total_requests)
            response.headers["X-RateLimit-Remaining"] = str(stats.remaining)
            response.headers["X-RateLimit-Reset"] = str(int(stats.reset_time))

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with rate limiting."""
        path = request.url.path

        # Skip excluded paths
        if self._should_exclude(path):
            return await call_next(request)

        # Update total requests
        with self._stats_lock:
            self.stats["total_requests"] += 1

        try:
            # Get appropriate rate limiter and client ID
            limiter, client_id = self._get_limiter_for_request(request)

            # Check rate limit
            allowed = await limiter.acquire_async(client_id)
            stats = limiter.get_stats(client_id)

            if not allowed:
                # Rate limit exceeded
                with self._stats_lock:
                    self.stats["denied_requests"] += 1

                if self.config.log_violations:
                    request_id = getattr(request.state, "request_id", "unknown")
                    logger.warning(
                        f"Rate limit exceeded for client {client_id[:8]}...",
                        path=path,
                        client_id=client_id,
                        request_id=request_id,
                        limiter=limiter.identifier,
                    )

                return self._create_rate_limit_response(stats)

            # Request allowed, proceed
            with self._stats_lock:
                self.stats["allowed_requests"] += 1

            response = await call_next(request)

            # Add rate limit headers
            self._add_rate_limit_headers(response, stats)

            return response

        except Exception as e:
            # Handle rate limiter errors
            with self._stats_lock:
                self.stats["errors"] += 1

            logger.error(f"Rate limiting error: {str(e)}", exc_info=True)

            if self.config.fail_open:
                # Allow request to proceed on error
                return await call_next(request)
            else:
                # Return error response
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"error": "Rate limiting service unavailable"},
                )

    def get_stats(self) -> Dict[str, Any]:
        """Get middleware statistics."""
        with self._stats_lock:
            middleware_stats = self.stats.copy()

        limiter_stats = _rate_limiter_registry.get_all_stats()

        return {
            "middleware": middleware_stats,
            "limiters": limiter_stats,
            "config": {
                "algorithm": self.config.algorithm.value,
                "requests": self.config.requests,
                "window_seconds": self.config.window_seconds,
                "exclude_paths": self.config.exclude_paths,
            },
        }


# Convenience functions
def create_rate_limit_middleware(
    app: ASGIApp,
    requests: int = 100,
    window_seconds: int = 60,
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET,
    **kwargs,
) -> RateLimitMiddleware:
    """
    Create a rate limiting middleware with simple configuration.

    Args:
        app: ASGI application
        requests: Number of requests allowed
        window_seconds: Time window in seconds
        algorithm: Rate limiting algorithm
        **kwargs: Additional configuration options

    Returns:
        RateLimitMiddleware: Configured middleware
    """
    config = RateLimitConfig(
        requests=requests, window_seconds=window_seconds, algorithm=algorithm, **kwargs
    )

    return RateLimitMiddleware(app, config)


def setup_rate_limiting(
    app: FastAPI,
    requests: int = 100,
    window_seconds: int = 60,
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET,
    **kwargs,
) -> RateLimitMiddleware:
    """
    Setup rate limiting for a FastAPI application.

    Args:
        app: FastAPI application
        requests: Number of requests allowed
        window_seconds: Time window in seconds
        algorithm: Rate limiting algorithm
        **kwargs: Additional configuration options

    Returns:
        RateLimitMiddleware: Configured middleware
    """
    middleware = create_rate_limit_middleware(
        app, requests, window_seconds, algorithm, **kwargs
    )

    app.add_middleware(lambda app: middleware)

    logger.info(
        f"Rate limiting configured: {requests} requests per {window_seconds}s using {algorithm.value}"
    )

    return middleware


# Legacy function for backward compatibility
async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    """
    Legacy function-based rate limiting middleware.

    This is maintained for backward compatibility.
    """
    # Simple fixed-window rate limiting
    if not hasattr(rate_limit_middleware, "_limiter"):
        rate_limit_middleware._limiter = FixedWindowRateLimiter(100, 60, "legacy")

    path = request.url.path
    if path.startswith(("/docs", "/openapi", "/health")):
        return await call_next(request)

    client_id = ClientIdentifier.get_client_ip(request)

    try:
        if await rate_limit_middleware._limiter.acquire_async(client_id):
            return await call_next(request)
        else:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Please try again later."},
                headers={"Retry-After": "60"},
            )
    except Exception as e:
        logger.error(f"Legacy rate limiting error: {e}")
        return await call_next(request)


# Export all important components
__all__ = [
    "RateLimitMiddleware",
    "RateLimitConfig",
    "RateLimitAlgorithm",
    "RateLimiter",
    "TokenBucketRateLimiter",
    "SlidingWindowRateLimiter",
    "FixedWindowRateLimiter",
    "ClientIdentifier",
    "register_rate_limiter",
    "get_rate_limiter",
    "setup_rate_limiting",
    "create_rate_limit_middleware",
    "rate_limit_middleware",
    "RateLimitExceededError",
    "RateLimitResult",
]
