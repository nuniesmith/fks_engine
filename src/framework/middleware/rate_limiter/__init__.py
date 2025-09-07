"""
Rate Limiter Package

A comprehensive, production-ready rate limiting solution with multiple algorithms,
flexible policies, and extensive monitoring capabilities.

Features:
- Multiple rate limiting algorithms (token bucket, sliding window, fixed window)
- Flexible policies (strict, wait, throttle)
- Synchronous and asynchronous support
- Per-client rate limiting with automatic cleanup
- Comprehensive statistics and monitoring
- HTTP middleware for FastAPI/Starlette
- Function-level decorators
- Global registry for limiter management

Quick Start:
-----------

Basic function decoration:
    from framework.middleware.rate_limiter import rate_limited

    @rate_limited(limit=100, window=60)
    def my_function():
        # Limited to 100 calls per minute
        pass

Explicit rate limiter creation:
    from framework.middleware.rate_limiter import RateLimiter

    limiter = RateLimiter(max_requests=100, time_window=60)
    if limiter.acquire():
        # Process request
        pass

HTTP middleware:
    from fastapi import FastAPI
    from framework.middleware.rate_limiter.middleware import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

Advanced usage with custom algorithms:
    from framework.middleware.rate_limiter.algorithms import TokenBucketAlgorithm

    algorithm = TokenBucketAlgorithm(max_requests=100, time_window=60, burst_capacity=20)
    result = algorithm.acquire("client_123")
"""

# Algorithms
from .algorithms import (
    AVAILABLE_ALGORITHMS,
    FixedWindowAlgorithm,
    RateLimitAlgorithm,
    RateLimitResult,
    SlidingWindowAlgorithm,
    TokenBucketAlgorithm,
    create_algorithm,
)

# Core components
from .core import RateLimiter

# Decorators
from .decorators import (
    api_rate_limit,
    conditional_rate_limit,
    method_rate_limit,
    per_ip_rate_limit,
    per_user_rate_limit,
    rate_limited,
    shared_rate_limit,
    strict_rate_limit,
    throttle_rate_limit,
    wait_rate_limit,
)
from .exceptions import (
    RateLimitAlgorithmError,
    RateLimitConfigError,
    RateLimitError,
    RateLimitExceededError,
    RateLimitRegistryError,
)
from .policies import RateLimitPolicy

# Registry functions
from .registry import (
    cleanup_all_limiters,
    clear_registry,
    exists,
    find_limiters_by_algorithm,
    find_limiters_by_policy,
    get_all_stats,
    get_or_create_rate_limiter,
    get_rate_limiter,
    get_registry_stats,
    list_rate_limiters,
    register_rate_limiter,
    reset_all_limiters,
    unregister_rate_limiter,
)
from .stats import RateLimitStats

# Utilities
from .utils import (
    ClientIdentifier,
    calculate_reset_time,
    create_client_key_func,
    format_rate_limit_message,
    get_retry_after_header,
)

# Middleware (imported separately to avoid FastAPI dependency for non-web usage)
try:
    from .middleware import (
        RateLimitConfig,
        RateLimitMiddleware,
        create_rate_limit_middleware,
    )

    _MIDDLEWARE_AVAILABLE = True
except ImportError:
    _MIDDLEWARE_AVAILABLE = False
    RateLimitMiddleware = None
    RateLimitConfig = None
    create_rate_limit_middleware = None


# Public API - carefully curated for stability
__all__ = [
    # Core classes
    "RateLimiter",
    "RateLimitPolicy",
    "RateLimitStats",
    # Exceptions
    "RateLimitError",
    "RateLimitExceededError",
    "RateLimitConfigError",
    "RateLimitRegistryError",
    "RateLimitAlgorithmError",
    # Algorithms
    "RateLimitAlgorithm",
    "RateLimitResult",
    "TokenBucketAlgorithm",
    "SlidingWindowAlgorithm",
    "FixedWindowAlgorithm",
    "create_algorithm",
    "AVAILABLE_ALGORITHMS",
    # Registry functions
    "get_rate_limiter",
    "get_or_create_rate_limiter",
    "register_rate_limiter",
    "unregister_rate_limiter",
    "list_rate_limiters",
    "get_all_stats",
    "reset_all_limiters",
    "cleanup_all_limiters",
    "clear_registry",
    "get_registry_stats",
    "exists",
    "find_limiters_by_algorithm",
    "find_limiters_by_policy",
    # Decorators
    "rate_limited",
    "conditional_rate_limit",
    "method_rate_limit",
    "shared_rate_limit",
    "strict_rate_limit",
    "wait_rate_limit",
    "throttle_rate_limit",
    "per_user_rate_limit",
    "per_ip_rate_limit",
    "api_rate_limit",
    # Utilities
    "ClientIdentifier",
    "create_client_key_func",
    "format_rate_limit_message",
    "calculate_reset_time",
    "get_retry_after_header",
    # Middleware (conditional)
    "RateLimitMiddleware",
    "RateLimitConfig",
    "create_rate_limit_middleware",
]

# Version information
__version__ = "1.0.0"
__author__ = "Your Organization"
__description__ = "Advanced rate limiting package with multiple algorithms and policies"

# Configuration and feature flags
FEATURES = {
    "algorithms": ["token_bucket", "sliding_window", "fixed_window"],
    "policies": ["strict", "wait", "throttle"],
    "middleware_available": _MIDDLEWARE_AVAILABLE,
    "async_support": True,
    "per_client_limiting": True,
    "statistics": True,
    "cleanup": True,
}


def get_version() -> str:
    """Get the package version."""
    return __version__


def get_features() -> dict:
    """Get available features in this installation."""
    return FEATURES.copy()


def create_simple_limiter(requests: int, window: int = 60, **kwargs) -> RateLimiter:
    """
    Create a simple rate limiter with sensible defaults.

    Args:
        requests: Maximum requests per window
        window: Time window in seconds
        **kwargs: Additional configuration options

    Returns:
        Configured RateLimiter instance
    """
    return RateLimiter(
        max_requests=requests,
        time_window=window,
        algorithm=kwargs.get("algorithm", "token_bucket"),
        policy=kwargs.get("policy", RateLimitPolicy.WAIT),
        **{k: v for k, v in kwargs.items() if k not in ["algorithm", "policy"]},
    )


def setup_global_rate_limiting(
    requests: int = 1000,
    window: int = 60,
    algorithm: str = "token_bucket",
    policy: str = "wait",
) -> RateLimiter:
    """
    Set up a global rate limiter for application-wide use.

    Args:
        requests: Maximum requests per window
        window: Time window in seconds
        algorithm: Algorithm to use
        policy: Policy for handling exceeded limits

    Returns:
        The global rate limiter instance
    """
    return register_rate_limiter(
        name="global_application_limiter",
        max_requests=requests,
        time_window=window,
        algorithm=algorithm,
        policy=policy,
    )


# Compatibility aliases for migration from old structure
# These maintain backward compatibility while encouraging migration to new APIs


def create_rate_limiter(*args, **kwargs):
    """
    Legacy function for backward compatibility.
    Use RateLimiter() or create_simple_limiter() instead.
    """
    import warnings

    warnings.warn(
        "create_rate_limiter is deprecated, use RateLimiter() or create_simple_limiter() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return RateLimiter(*args, **kwargs)


# Auto-cleanup setup - register a cleanup function that runs periodically
import atexit
import threading

_cleanup_thread = None
_cleanup_stop_event = threading.Event()


def _periodic_cleanup():
    """Periodic cleanup function that runs in background."""
    while not _cleanup_stop_event.wait(3600):  # Every hour
        try:
            cleaned = cleanup_all_limiters()
            if cleaned > 0:
                from loguru import logger

                logger.debug(f"Background cleanup removed {cleaned} expired entries")
        except Exception as e:
            from loguru import logger

            logger.warning(f"Background cleanup failed: {e}")


def start_background_cleanup():
    """Start background cleanup thread."""
    global _cleanup_thread
    if _cleanup_thread is None or not _cleanup_thread.is_alive():
        _cleanup_stop_event.clear()
        _cleanup_thread = threading.Thread(target=_periodic_cleanup, daemon=True)
        _cleanup_thread.start()


def stop_background_cleanup():
    """Stop background cleanup thread."""
    _cleanup_stop_event.set()
    if _cleanup_thread and _cleanup_thread.is_alive():
        _cleanup_thread.join(timeout=1.0)


# Register cleanup on exit
atexit.register(stop_background_cleanup)

# Start background cleanup by default (can be disabled if needed)
try:
    start_background_cleanup()
except Exception:
    pass  # Silently fail if we can't start background cleanup
