"""
HTTP middleware for rate limiting FastAPI and Starlette applications.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .core import RateLimiter
from .exceptions import RateLimitExceededError
from .policies import RateLimitPolicy
from .registry import get_or_create_rate_limiter
from .utils import ClientIdentifier, format_rate_limit_message, get_retry_after_header


@dataclass
class RateLimitConfig:
    """Configuration for HTTP rate limiting middleware."""

    # Basic rate limiting
    requests: int = 100
    window_seconds: int = 60
    algorithm: str = "token_bucket"
    policy: str = "wait"

    # Client identification
    client_id_strategy: str = "ip"  # 'ip', 'user_id', 'api_key', 'composite'
    client_id_components: List[str] = field(default_factory=lambda: ["ip"])

    # Path configuration
    exclude_paths: Set[str] = field(
        default_factory=lambda: {"/health", "/docs", "/openapi.json"}
    )
    include_paths: Optional[Set[str]] = (
        None  # If set, only these paths are rate limited
    )

    # Advanced features
    api_key_multiplier: float = 5.0  # API key users get higher limits
    api_key_header: str = "X-API-Key"
    custom_limits: Dict[str, Tuple[int, int]] = field(
        default_factory=dict
    )  # path -> (requests, window)

    # Response configuration
    enable_headers: bool = True  # Add rate limit headers to responses
    custom_error_message: Optional[str] = None
    error_response_format: str = "json"  # 'json' or 'plain'

    # Behavior
    fail_open: bool = True  # Allow requests if rate limiter fails
    log_violations: bool = True
    log_allowed_requests: bool = False
    cleanup_interval: int = 3600  # Clean up old client data every hour


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive rate limiting middleware for FastAPI/Starlette applications.

    Features:
    - Multiple rate limiting algorithms
    - Flexible client identification strategies
    - Path-based rate limiting rules
    - API key based rate limiting
    - Comprehensive monitoring and logging
    - Graceful error handling
    """

    def __init__(self, app: ASGIApp, config: Optional[RateLimitConfig] = None):
        """
        Initialize the rate limiting middleware.

        Args:
            app: ASGI application
            config: Rate limiting configuration
        """
        super().__init__(app)
        self.config = config or RateLimitConfig()

        # Create rate limiters
        self._setup_limiters()

        # Statistics tracking
        self.stats = {
            "total_requests": 0,
            "rate_limited_requests": 0,
            "allowed_requests": 0,
            "errors": 0,
            "excluded_requests": 0,
        }

        # Cleanup tracking
        self.last_cleanup = time.time()

        logger.info(
            f"Rate limiting middleware initialized: {self.config.requests} req/{self.config.window_seconds}s "
            f"using {self.config.algorithm} algorithm"
        )

    def _setup_limiters(self) -> None:
        """Setup the required rate limiters based on configuration."""
        # Global rate limiter
        self.global_limiter = get_or_create_rate_limiter(
            name="middleware_global",
            max_requests=self.config.requests,
            time_window=self.config.window_seconds,
            algorithm=self.config.algorithm,
            policy=self.config.policy,
        )

        # API key rate limiter (higher limits)
        if self.config.api_key_multiplier > 1.0:
            api_key_requests = int(
                self.config.requests * self.config.api_key_multiplier
            )
            self.api_key_limiter = get_or_create_rate_limiter(
                name="middleware_api_key",
                max_requests=api_key_requests,
                time_window=self.config.window_seconds,
                algorithm=self.config.algorithm,
                policy=self.config.policy,
            )
        else:
            self.api_key_limiter = None

        # Path-specific limiters
        self.path_limiters: Dict[str, RateLimiter] = {}
        for path, (requests, window) in self.config.custom_limits.items():
            limiter_name = f"middleware_path_{path.replace('/', '_')}"
            self.path_limiters[path] = get_or_create_rate_limiter(
                name=limiter_name,
                max_requests=requests,
                time_window=window,
                algorithm=self.config.algorithm,
                policy=self.config.policy,
            )

    def _should_exclude_path(self, path: str) -> bool:
        """Check if a path should be excluded from rate limiting."""
        # Check inclusion list first (if specified)
        if self.config.include_paths is not None:
            return path not in self.config.include_paths

        # Check exclusion list
        return any(path.startswith(excluded) for excluded in self.config.exclude_paths)

    def _get_client_id(self, request: Request) -> str:
        """Extract client ID based on configured strategy."""
        if self.config.client_id_strategy == "ip":
            return ClientIdentifier.get_client_ip(request)
        elif self.config.client_id_strategy == "user_id":
            user_id = ClientIdentifier.get_user_id(request)
            return user_id or ClientIdentifier.get_client_ip(request)  # Fallback to IP
        elif self.config.client_id_strategy == "api_key":
            api_key = ClientIdentifier.get_api_key(request, self.config.api_key_header)
            return api_key or ClientIdentifier.get_client_ip(request)  # Fallback to IP
        elif self.config.client_id_strategy == "composite":
            return ClientIdentifier.create_composite_id(
                request, self.config.client_id_components
            )
        else:
            # Default to IP
            return ClientIdentifier.get_client_ip(request)

    def _select_limiter_and_client_id(
        self, request: Request
    ) -> Tuple[RateLimiter, str]:
        """Select the appropriate rate limiter and client ID for the request."""
        path = request.url.path

        # Check for path-specific limiter first
        for custom_path, limiter in self.path_limiters.items():
            if path.startswith(custom_path):
                client_id = f"{self._get_client_id(request)}:{custom_path}"
                return limiter, client_id

        # Check for API key limiter
        if self.api_key_limiter:
            api_key = ClientIdentifier.get_api_key(request, self.config.api_key_header)
            if api_key:
                return self.api_key_limiter, api_key

        # Use global limiter
        return self.global_limiter, self._get_client_id(request)

    def _create_error_response(
        self, request: Request, limiter: RateLimiter, client_id: str
    ) -> Response:
        """Create an error response for rate limit exceeded."""
        # Get current stats for headers
        try:
            stats = limiter.get_stats(client_id)
            client_stats = stats.get("client_stats", {})
            retry_after = client_stats.get("retry_after", 60)
            remaining = client_stats.get("remaining", 0)
            reset_time = client_stats.get("reset_time", time.time() + 60)
        except Exception:
            # Fallback values if stats retrieval fails
            retry_after = 60
            remaining = 0
            reset_time = time.time() + 60

        # Create error message
        if self.config.custom_error_message:
            message = self.config.custom_error_message
        else:
            message = format_rate_limit_message(
                self.config.requests,
                self.config.window_seconds,
                retry_after,
                self.config.algorithm,
            )

        # Prepare headers
        headers = {}
        if self.config.enable_headers:
            headers.update(
                {
                    "Retry-After": get_retry_after_header(reset_time),
                    "X-RateLimit-Limit": str(self.config.requests),
                    "X-RateLimit-Remaining": str(remaining),
                    "X-RateLimit-Reset": str(int(reset_time)),
                }
            )

        # Create response based on format preference
        if self.config.error_response_format == "plain":
            return Response(
                content=message,
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers=headers,
                media_type="text/plain",
            )
        else:
            # JSON format (default)
            content = {
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": message,
                    "retry_after": retry_after,
                }
            }

            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=content,
                headers=headers,
            )

    def _add_rate_limit_headers(
        self, response: Response, limiter: RateLimiter, client_id: str
    ) -> None:
        """Add rate limit headers to a successful response."""
        if not self.config.enable_headers:
            return

        try:
            stats = limiter.get_stats(client_id)
            client_stats = stats.get("client_stats", {})

            if client_stats:
                response.headers["X-RateLimit-Limit"] = str(
                    stats.get("limit", self.config.requests)
                )
                response.headers["X-RateLimit-Remaining"] = str(
                    client_stats.get("remaining", 0)
                )
                response.headers["X-RateLimit-Reset"] = str(
                    int(client_stats.get("reset_time", time.time() + 60))
                )
        except Exception as e:
            logger.debug(f"Failed to add rate limit headers: {e}")

    def _cleanup_if_needed(self) -> None:
        """Perform periodic cleanup of old client data."""
        current_time = time.time()
        if current_time - self.last_cleanup > self.config.cleanup_interval:
            try:
                # Cleanup all limiters
                cleaned = 0
                cleaned += self.global_limiter.cleanup_expired_clients()

                if self.api_key_limiter:
                    cleaned += self.api_key_limiter.cleanup_expired_clients()

                for limiter in self.path_limiters.values():
                    cleaned += limiter.cleanup_expired_clients()

                if cleaned > 0:
                    logger.debug(
                        f"Rate limiter cleanup removed {cleaned} expired client entries"
                    )

                self.last_cleanup = current_time
            except Exception as e:
                logger.warning(f"Rate limiter cleanup failed: {e}")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with rate limiting."""
        path = request.url.path

        # Update total request count
        self.stats["total_requests"] += 1

        # Check if path should be excluded
        if self._should_exclude_path(path):
            self.stats["excluded_requests"] += 1
            return await call_next(request)

        # Periodic cleanup
        self._cleanup_if_needed()

        try:
            # Select appropriate limiter and get client ID
            limiter, client_id = self._select_limiter_and_client_id(request)

            # Attempt to acquire rate limit permission
            allowed = await limiter.acquire_async(client_id)

            if not allowed:
                # Rate limit exceeded
                self.stats["rate_limited_requests"] += 1

                if self.config.log_violations:
                    logger.warning(
                        f"Rate limit exceeded",
                        client_id=(
                            client_id[:8] + "..." if len(client_id) > 8 else client_id
                        ),
                        path=path,
                        limiter=limiter.name,
                        method=request.method,
                    )

                return self._create_error_response(request, limiter, client_id)

            # Request allowed
            self.stats["allowed_requests"] += 1

            if self.config.log_allowed_requests:
                logger.debug(
                    f"Request allowed",
                    client_id=(
                        client_id[:8] + "..." if len(client_id) > 8 else client_id
                    ),
                    path=path,
                    limiter=limiter.name,
                )

            # Process the request
            response = await call_next(request)

            # Add rate limit headers to successful response
            self._add_rate_limit_headers(response, limiter, client_id)

            return response

        except RateLimitExceededError as e:
            # Handle strict policy rate limit errors
            self.stats["rate_limited_requests"] += 1

            if self.config.log_violations:
                logger.warning(f"Rate limit exceeded with strict policy: {e}")

            # Create error response using the exception details
            headers = {}
            if self.config.enable_headers:
                headers["Retry-After"] = str(int(e.retry_after))
                if e.limit:
                    headers["X-RateLimit-Limit"] = str(e.limit)
                    headers["X-RateLimit-Remaining"] = "0"

            if self.config.error_response_format == "plain":
                return Response(
                    content=str(e),
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers=headers,
                    media_type="text/plain",
                )
            else:
                content = {
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": str(e),
                        "retry_after": e.retry_after,
                    }
                }

                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content=content,
                    headers=headers,
                )

        except Exception as e:
            # Handle unexpected errors
            self.stats["errors"] += 1
            logger.error(f"Rate limiting middleware error: {e}", exc_info=True)

            if self.config.fail_open:
                # Allow request to proceed on error
                logger.warning("Rate limiter failed, allowing request (fail_open=True)")
                return await call_next(request)
            else:
                # Return service unavailable
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "error": {
                            "code": "rate_limiter_error",
                            "message": "Rate limiting service unavailable",
                        }
                    },
                )

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive middleware statistics."""
        # Get middleware stats
        middleware_stats = self.stats.copy()

        # Calculate derived metrics
        if self.stats["total_requests"] > 0:
            middleware_stats["success_rate"] = (
                f"{(self.stats['allowed_requests'] / self.stats['total_requests']) * 100:.2f}%"
            )
            middleware_stats["rate_limited_percentage"] = (
                f"{(self.stats['rate_limited_requests'] / self.stats['total_requests']) * 100:.2f}%"
            )
        else:
            middleware_stats["success_rate"] = "100.00%"
            middleware_stats["rate_limited_percentage"] = "0.00%"

        # Get limiter stats
        limiter_stats = {}
        try:
            limiter_stats["global"] = self.global_limiter.get_stats()
            if self.api_key_limiter:
                limiter_stats["api_key"] = self.api_key_limiter.get_stats()
            for path, limiter in self.path_limiters.items():
                limiter_stats[f"path_{path}"] = limiter.get_stats()
        except Exception as e:
            logger.warning(f"Failed to get limiter stats: {e}")

        return {
            "middleware": middleware_stats,
            "limiters": limiter_stats,
            "config": {
                "algorithm": self.config.algorithm,
                "requests_per_window": self.config.requests,
                "window_seconds": self.config.window_seconds,
                "policy": self.config.policy,
                "client_id_strategy": self.config.client_id_strategy,
                "fail_open": self.config.fail_open,
                "excluded_paths": list(self.config.exclude_paths),
                "custom_limits": dict(self.config.custom_limits),
            },
        }


def create_rate_limit_middleware(
    requests: int = 100,
    window_seconds: int = 60,
    algorithm: str = "token_bucket",
    **kwargs,
) -> Callable[[ASGIApp], RateLimitMiddleware]:
    """
    Factory function to create rate limiting middleware with simple configuration.

    Args:
        requests: Number of requests allowed per window
        window_seconds: Time window in seconds
        algorithm: Rate limiting algorithm to use
        **kwargs: Additional configuration options

    Returns:
        Middleware factory function
    """
    config = RateLimitConfig(
        requests=requests, window_seconds=window_seconds, algorithm=algorithm, **kwargs
    )

    def middleware_factory(app: ASGIApp) -> RateLimitMiddleware:
        return RateLimitMiddleware(app, config)

    return middleware_factory
