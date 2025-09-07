"""
Cache framework package.

This package provides comprehensive caching functionality including:
- Multiple backend implementations (memory, Redis, file-based, layered)
- Async and sync function caching decorators
- Performance monitoring and statistics
- Cache invalidation and management utilities
"""

# Import backend implementations
from .backends import (
    CacheBackend,
    FileBackend,
    LayeredBackend,
    MemoryBackend,
    RedisBackend,
    create_backend,
)

# Import core cache functionality
from .cache import (
    AsyncCache,
    CacheEntry,
    CacheStats,
    clear_all_async_caches,
    get_all_async_cache_stats,
    get_async_cache,
)

# Import decorators and utilities
from .decorators import (
    CacheConfig,
    CacheManager,
    async_cached,
    cache_manager,
    cached,
    configure_cache,
    file_cached,
    memory_cached,
    method_cached,
    monitor_cache_performance,
    redis_cached,
    temporary_cache,
)

# Version information
__version__ = "1.0.0"
__author__ = "Framework Cache Team"

# Default cache instances for convenience
default_memory_cache = MemoryBackend()
default_cache_manager = cache_manager

# Register default backends
cache_manager.register_backend("default", default_memory_cache)
cache_manager.register_backend("memory", default_memory_cache)

# Convenience aliases
Cache = AsyncCache
cache = async_cached
memory_cache = memory_cached

# Export all public symbols
__all__ = [
    # Core cache classes
    "AsyncCache",
    "CacheEntry",
    "CacheStats",
    # Backend classes
    "CacheBackend",
    "MemoryBackend",
    "RedisBackend",
    "FileBackend",
    "LayeredBackend",
    # Factory functions
    "create_backend",
    "get_async_cache",
    "configure_cache",
    # Decorators
    "async_cached",
    "cached",
    "method_cached",
    "memory_cached",
    "redis_cached",
    "file_cached",
    # Management classes
    "CacheConfig",
    "CacheManager",
    "cache_manager",
    # Utilities
    "temporary_cache",
    "monitor_cache_performance",
    "clear_all_async_caches",
    "get_all_async_cache_stats",
    # Convenience aliases
    "Cache",
    "cache",
    "memory_cache",
    "default_memory_cache",
    "default_cache_manager",
]

# Package metadata
__package_info__ = {
    "name": "framework.cache",
    "version": __version__,
    "description": "Comprehensive async caching framework with multiple backends",
    "features": [
        "Thread-safe async cache implementation",
        "Multiple backend support (memory, Redis, file, layered)",
        "Easy-to-use decorators for function caching",
        "Performance monitoring and statistics",
        "Cache invalidation and pattern matching",
        "TTL (time-to-live) support",
        "Size-based eviction policies",
        "Custom key generation",
        "Conditional caching",
    ],
    "dependencies": [
        "loguru",  # Required
        "aiofiles",  # Required for file backend
        "redis",  # Optional, for Redis backend
    ],
}


def get_package_info():
    """Get package information and features."""
    return __package_info__.copy()


def create_cache_from_config(config_dict: dict) -> CacheBackend:
    """
    Create a cache backend from configuration dictionary.

    Args:
        config_dict: Configuration dictionary with 'type' and backend-specific options

    Returns:
        Configured cache backend

    Example:
        config = {
            "type": "layered",
            "l1": {"type": "memory", "max_size": 1000},
            "l2": {"type": "redis", "redis_url": "redis://localhost:6379"}
        }
        cache_backend = create_cache_from_config(config)
    """
    backend_type = config_dict.pop("type", "memory")
    return create_backend(backend_type, **config_dict)


# Auto-configure based on environment
def auto_configure_cache():
    """
    Auto-configure cache based on available dependencies and environment.

    Returns:
        Tuple of (backend_type, backend_instance)
    """
    import os

    # Check for Redis availability
    try:
        import redis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        backend = RedisBackend(redis_url=redis_url)
        cache_manager.register_backend("auto", backend)
        return "redis", backend
    except ImportError:
        pass

    # Fallback to file cache for persistence
    cache_dir = os.getenv("CACHE_DIR", "/tmp/framework_cache")
    try:
        backend = FileBackend(cache_dir=cache_dir)
        cache_manager.register_backend("auto", backend)
        return "file", backend
    except Exception:
        pass

    # Final fallback to memory cache
    backend = MemoryBackend()
    cache_manager.register_backend("auto", backend)
    return "memory", backend


# Initialize auto-configured cache
auto_backend_type, auto_backend = auto_configure_cache()
cache_manager.register_backend("auto", auto_backend)

# Logging configuration check
try:
    from loguru import logger

    logger.debug(f"Framework cache package loaded with {auto_backend_type} backend")
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logging.getLogger(__name__).info(
        f"Framework cache package loaded with {auto_backend_type} backend"
    )
