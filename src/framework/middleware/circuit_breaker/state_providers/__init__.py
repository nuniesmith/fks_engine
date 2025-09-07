"""
State Providers for Circuit Breaker Middleware

This module provides different implementations for persisting circuit breaker state.
State providers allow circuit breakers to maintain their state across application
restarts and share state between multiple application instances.

Available providers:
- MemoryStateProvider: In-memory storage (default, no persistence)
- RedisStateProvider: Redis-based storage (requires redis package)

Example usage:
    ```python
    from framework.middleware.circuit_breaker.state_providers import (
        MemoryStateProvider,
        RedisStateProvider
    )

    # Memory provider (default)
    memory_provider = MemoryStateProvider()

    # Redis provider (if redis is available)
    import redis
    redis_client = redis.Redis(host='localhost', port=6379, db=0)
    redis_provider = RedisStateProvider(redis_client)
    ```
"""

from typing import TYPE_CHECKING, Any

# Always available providers
from .base import StateProvider
from .memory import MemoryStateProvider

# Track what's available for exports
__all__ = ["StateProvider", "MemoryStateProvider"]

# Try to import Redis provider
_REDIS_AVAILABLE = False
_import_error = ""

if TYPE_CHECKING:
    # For type checking, always import RedisStateProvider
    try:
        from .redis import RedisStateProvider
    except ImportError:
        RedisStateProvider = Any  # Fallback for type checking

try:
    from .redis import RedisStateProvider

    __all__.append("RedisStateProvider")
    _REDIS_AVAILABLE = True
except ImportError as e:
    # Redis provider not available
    RedisStateProvider = None  # type: ignore
    _import_error = str(e)


def create_memory_provider(
    ttl_seconds: int = 0, deep_copy: bool = True
) -> MemoryStateProvider:
    """
    Factory function to create a memory state provider.

    Args:
        ttl_seconds: Time-to-live in seconds for stored state (0 = no expiration)
        deep_copy: Whether to make deep copies of state when storing/retrieving

    Returns:
        Configured MemoryStateProvider instance
    """
    return MemoryStateProvider(ttl_seconds=ttl_seconds, deep_copy=deep_copy)


def create_redis_provider(
    redis_client,
    ttl_seconds: int = 0,
    namespace: str = "circuit_breaker:",
    retry_attempts: int = 3,
) -> StateProvider:
    """
    Factory function to create a Redis state provider.

    Args:
        redis_client: An initialized Redis client instance
        ttl_seconds: Time-to-live in seconds for stored state (0 = no expiration)
        namespace: Optional namespace prefix for all keys
        retry_attempts: Number of retry attempts for Redis operations

    Returns:
        Configured RedisStateProvider instance

    Raises:
        ImportError: If Redis dependencies are not available
    """
    if not _REDIS_AVAILABLE:
        raise ImportError(
            f"Redis provider not available. Install redis package to use RedisStateProvider. "
            f"Original error: {_import_error}"
        )

    # At this point we know RedisStateProvider is available
    assert RedisStateProvider is not None
    return RedisStateProvider(
        redis_client=redis_client,
        ttl_seconds=ttl_seconds,
        namespace=namespace,
        retry_attempts=retry_attempts,
    )


def get_available_providers() -> list:
    """
    Get a list of available state provider names.

    Returns:
        List of available provider names
    """
    providers = ["memory"]
    if _REDIS_AVAILABLE:
        providers.append("redis")
    return providers


def is_redis_available() -> bool:
    """
    Check if Redis state provider is available.

    Returns:
        True if Redis provider can be imported, False otherwise
    """
    return _REDIS_AVAILABLE


def create_provider(provider_type: str, **kwargs) -> StateProvider:
    """
    Factory function to create a state provider by type.

    Args:
        provider_type: Type of provider ("memory" or "redis")
        **kwargs: Provider-specific configuration parameters

    Returns:
        Configured state provider instance

    Raises:
        ValueError: If provider_type is not supported
        ImportError: If required dependencies are not available

    Example:
        ```python
        # Create memory provider
        provider = create_provider("memory", ttl_seconds=300)

        # Create Redis provider
        import redis
        redis_client = redis.Redis()
        provider = create_provider("redis", redis_client=redis_client)
        ```
    """
    if provider_type == "memory":
        return create_memory_provider(**kwargs)
    elif provider_type == "redis":
        if not _REDIS_AVAILABLE:
            raise ImportError(
                f"Redis provider not available. Install redis package to use RedisStateProvider."
            )
        return create_redis_provider(**kwargs)
    else:
        available = get_available_providers()
        raise ValueError(
            f"Unknown provider type: '{provider_type}'. "
            f"Available providers: {', '.join(available)}"
        )


# Add factory functions to exports
__all__.extend(
    [
        "create_memory_provider",
        "create_redis_provider",
        "create_provider",
        "get_available_providers",
        "is_redis_available",
    ]
)


# Provider information
PROVIDER_INFO = {
    "memory": {
        "name": "Memory State Provider",
        "description": "In-memory storage with optional TTL and thread safety",
        "persistent": False,
        "shared": False,
        "requirements": None,
        "available": True,
    },
    "redis": {
        "name": "Redis State Provider",
        "description": "Redis-based storage with persistence and clustering support",
        "persistent": True,
        "shared": True,
        "requirements": ["redis", "backoff"],
        "available": _REDIS_AVAILABLE,
    },
}


def get_provider_info(provider_type: str = None) -> dict:
    """
    Get information about available state providers.

    Args:
        provider_type: Specific provider to get info for (optional)

    Returns:
        Provider information dictionary
    """
    if provider_type:
        if provider_type not in PROVIDER_INFO:
            raise ValueError(f"Unknown provider type: '{provider_type}'")
        return PROVIDER_INFO[provider_type].copy()

    return {k: v.copy() for k, v in PROVIDER_INFO.items()}


# Add info function to exports
__all__.append("get_provider_info")


# Compatibility imports for common patterns
try:
    # Try to provide a simple Redis client factory for convenience
    import redis

    def create_redis_client(
        host: str = "localhost", port: int = 6379, db: int = 0, **kwargs
    ):
        """
        Convenience function to create a Redis client.

        Args:
            host: Redis server hostname
            port: Redis server port
            db: Redis database number
            **kwargs: Additional Redis client parameters

        Returns:
            Configured Redis client instance
        """
        return redis.Redis(host=host, port=port, db=db, **kwargs)

    __all__.append("create_redis_client")

except ImportError:
    # Redis not available, skip convenience function
    pass
