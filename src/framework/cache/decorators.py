"""
Cache decorators for easy function and method caching.

This module provides decorators that make it simple to add caching
to functions and methods with various configuration options.
"""

import asyncio
import functools
import hashlib
import inspect
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar, Union

from loguru import logger

from .backends import CacheBackend, MemoryBackend, create_backend

# Type variables for generic functions
F = TypeVar("F", bound=Callable[..., Any])
AF = TypeVar("AF", bound=Callable[..., Awaitable[Any]])

# Global thread pool for sync operations
_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cache_")


class CacheConfig:
    """Configuration for cache decorators."""

    def __init__(
        self,
        backend: Optional[CacheBackend] = None,
        ttl: int = 300,
        key_prefix: str = "",
        include_args: bool = True,
        include_kwargs: bool = True,
        exclude_args: Optional[list] = None,
        exclude_kwargs: Optional[list] = None,
        key_generator: Optional[Callable] = None,
        condition: Optional[Callable] = None,
        on_cache_hit: Optional[Callable] = None,
        on_cache_miss: Optional[Callable] = None,
    ):
        """
        Initialize cache configuration.

        Args:
            backend: Cache backend to use (defaults to memory)
            ttl: Time-to-live in seconds
            key_prefix: Prefix for cache keys
            include_args: Whether to include positional args in key
            include_kwargs: Whether to include keyword args in key
            exclude_args: List of arg indices to exclude from key
            exclude_kwargs: List of kwarg names to exclude from key
            key_generator: Custom key generation function
            condition: Function to determine if result should be cached
            on_cache_hit: Callback for cache hits
            on_cache_miss: Callback for cache misses
        """
        self.backend = backend or MemoryBackend()
        self.ttl = ttl
        self.key_prefix = key_prefix
        self.include_args = include_args
        self.include_kwargs = include_kwargs
        self.exclude_args = exclude_args or []
        self.exclude_kwargs = exclude_kwargs or []
        self.key_generator = key_generator
        self.condition = condition
        self.on_cache_hit = on_cache_hit
        self.on_cache_miss = on_cache_miss


def _generate_cache_key(
    func: Callable, args: tuple, kwargs: dict, config: CacheConfig
) -> str:
    """Generate a cache key for the function call."""

    # Use custom key generator if provided
    if config.key_generator:
        try:
            custom_key = config.key_generator(func, args, kwargs)
            return f"{config.key_prefix}{custom_key}"
        except Exception as e:
            logger.warning(f"Custom key generator failed: {e}, falling back to default")

    # Build key components
    key_parts = [func.__module__, func.__qualname__]

    # Add arguments if enabled
    if config.include_args and args:
        filtered_args = []
        for i, arg in enumerate(args):
            if i not in config.exclude_args:
                filtered_args.append(arg)

        if filtered_args:
            try:
                args_str = json.dumps(filtered_args, sort_keys=True, default=str)
                if len(args_str) > 100:
                    args_str = hashlib.md5(args_str.encode()).hexdigest()
                key_parts.append(f"args:{args_str}")
            except (TypeError, ValueError):
                # Fallback for non-serializable objects
                args_hash = hashlib.md5(str(filtered_args).encode()).hexdigest()
                key_parts.append(f"args:{args_hash}")

    # Add keyword arguments if enabled
    if config.include_kwargs and kwargs:
        filtered_kwargs = {
            k: v for k, v in kwargs.items() if k not in config.exclude_kwargs
        }

        if filtered_kwargs:
            try:
                kwargs_str = json.dumps(
                    sorted(filtered_kwargs.items()), sort_keys=True, default=str
                )
                if len(kwargs_str) > 100:
                    kwargs_str = hashlib.md5(kwargs_str.encode()).hexdigest()
                key_parts.append(f"kwargs:{kwargs_str}")
            except (TypeError, ValueError):
                # Fallback for non-serializable objects
                kwargs_hash = hashlib.md5(
                    str(sorted(filtered_kwargs.items())).encode()
                ).hexdigest()
                key_parts.append(f"kwargs:{kwargs_hash}")

    # Create final key
    key_string = ":".join(key_parts)
    cache_key = hashlib.md5(key_string.encode()).hexdigest()

    return f"{config.key_prefix}{cache_key}"


def _should_cache_result(result: Any, config: CacheConfig) -> bool:
    """Determine if the result should be cached."""
    if config.condition:
        try:
            return config.condition(result)
        except Exception as e:
            logger.warning(f"Cache condition function failed: {e}, caching by default")
            return True

    # Default: cache everything except None
    return result is not None


async def _async_cache_wrapper(
    func: Callable, config: CacheConfig, *args, **kwargs
) -> Any:
    """Async wrapper for cached functions."""
    cache_key = _generate_cache_key(func, args, kwargs, config)

    # Try to get from cache first
    try:
        cached_result = await config.backend.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Cache hit for {func.__name__}: {cache_key}")
            if config.on_cache_hit:
                try:
                    config.on_cache_hit(func, args, kwargs, cached_result)
                except Exception as e:
                    logger.warning(f"Cache hit callback failed: {e}")
            return cached_result
    except Exception as e:
        logger.warning(f"Cache get failed for {func.__name__}: {e}")

    # Cache miss - execute function
    logger.debug(f"Cache miss for {func.__name__}: {cache_key}")
    start_time = time.time()

    try:
        if asyncio.iscoroutinefunction(func):
            result = await func(*args, **kwargs)
        else:
            # Run sync function in thread pool
            result = await asyncio.get_event_loop().run_in_executor(
                _thread_pool, functools.partial(func, *args, **kwargs)
            )

        execution_time = (time.time() - start_time) * 1000  # ms

        # Cache the result if it meets the condition
        if _should_cache_result(result, config):
            try:
                await config.backend.set(cache_key, result, config.ttl)
            except Exception as e:
                logger.warning(f"Cache set failed for {func.__name__}: {e}")

        if config.on_cache_miss:
            try:
                config.on_cache_miss(func, args, kwargs, result, execution_time)
            except Exception as e:
                logger.warning(f"Cache miss callback failed: {e}")

        return result

    except Exception as e:
        logger.error(f"Function execution failed for {func.__name__}: {e}")
        raise


def async_cached(
    ttl: int = 300,
    backend: Optional[CacheBackend] = None,
    key_prefix: str = "",
    include_args: bool = True,
    include_kwargs: bool = True,
    exclude_args: Optional[list] = None,
    exclude_kwargs: Optional[list] = None,
    key_generator: Optional[Callable] = None,
    condition: Optional[Callable] = None,
    on_cache_hit: Optional[Callable] = None,
    on_cache_miss: Optional[Callable] = None,
) -> Callable[[AF], AF]:
    """
    Decorator for caching async functions.

    Args:
        ttl: Time-to-live in seconds
        backend: Cache backend to use
        key_prefix: Prefix for cache keys
        include_args: Whether to include positional args in key
        include_kwargs: Whether to include keyword args in key
        exclude_args: List of arg indices to exclude from key
        exclude_kwargs: List of kwarg names to exclude from key
        key_generator: Custom key generation function
        condition: Function to determine if result should be cached
        on_cache_hit: Callback for cache hits
        on_cache_miss: Callback for cache misses

    Returns:
        Decorated async function
    """

    def decorator(func: AF) -> AF:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("async_cached can only be used with async functions")

        config = CacheConfig(
            backend=backend,
            ttl=ttl,
            key_prefix=key_prefix,
            include_args=include_args,
            include_kwargs=include_kwargs,
            exclude_args=exclude_args,
            exclude_kwargs=exclude_kwargs,
            key_generator=key_generator,
            condition=condition,
            on_cache_hit=on_cache_hit,
            on_cache_miss=on_cache_miss,
        )

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await _async_cache_wrapper(func, config, *args, **kwargs)

        # Add cache control methods
        wrapper._cache_config = config
        wrapper._original_func = func

        async def invalidate(*args, **kwargs):
            """Invalidate cache for specific arguments."""
            cache_key = _generate_cache_key(func, args, kwargs, config)
            return await config.backend.delete(cache_key)

        async def clear_cache():
            """Clear all cache entries for this function."""
            pattern = f"{config.key_prefix}{func.__module__}:{func.__qualname__}:*"
            keys = await config.backend.keys(pattern)
            for key in keys:
                await config.backend.delete(key)
            return len(keys)

        wrapper.invalidate = invalidate
        wrapper.clear_cache = clear_cache

        return wrapper

    return decorator


def cached(
    ttl: int = 300,
    backend: Optional[CacheBackend] = None,
    key_prefix: str = "",
    include_args: bool = True,
    include_kwargs: bool = True,
    exclude_args: Optional[list] = None,
    exclude_kwargs: Optional[list] = None,
    key_generator: Optional[Callable] = None,
    condition: Optional[Callable] = None,
    on_cache_hit: Optional[Callable] = None,
    on_cache_miss: Optional[Callable] = None,
) -> Callable[[F], F]:
    """
    Decorator for caching sync functions (executed in async context).

    Args:
        ttl: Time-to-live in seconds
        backend: Cache backend to use
        key_prefix: Prefix for cache keys
        include_args: Whether to include positional args in key
        include_kwargs: Whether to include keyword args in key
        exclude_args: List of arg indices to exclude from key
        exclude_kwargs: List of kwarg names to exclude from key
        key_generator: Custom key generation function
        condition: Function to determine if result should be cached
        on_cache_hit: Callback for cache hits
        on_cache_miss: Callback for cache misses

    Returns:
        Decorated async function that caches the sync function
    """

    def decorator(func: F) -> F:
        if asyncio.iscoroutinefunction(func):
            raise ValueError("Use async_cached for async functions")

        config = CacheConfig(
            backend=backend,
            ttl=ttl,
            key_prefix=key_prefix,
            include_args=include_args,
            include_kwargs=include_kwargs,
            exclude_args=exclude_args,
            exclude_kwargs=exclude_kwargs,
            key_generator=key_generator,
            condition=condition,
            on_cache_hit=on_cache_hit,
            on_cache_miss=on_cache_miss,
        )

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await _async_cache_wrapper(func, config, *args, **kwargs)

        # Add cache control methods
        async_wrapper._cache_config = config
        async_wrapper._original_func = func

        async def invalidate(*args, **kwargs):
            """Invalidate cache for specific arguments."""
            cache_key = _generate_cache_key(func, args, kwargs, config)
            return await config.backend.delete(cache_key)

        async def clear_cache():
            """Clear all cache entries for this function."""
            pattern = f"{config.key_prefix}{func.__module__}:{func.__qualname__}:*"
            keys = await config.backend.keys(pattern)
            for key in keys:
                await config.backend.delete(key)
            return len(keys)

        async_wrapper.invalidate = invalidate
        async_wrapper.clear_cache = clear_cache

        return async_wrapper

    return decorator


def method_cached(
    ttl: int = 300,
    backend: Optional[CacheBackend] = None,
    key_prefix: str = "",
    include_self: bool = False,
    include_args: bool = True,
    include_kwargs: bool = True,
    exclude_args: Optional[list] = None,
    exclude_kwargs: Optional[list] = None,
    key_generator: Optional[Callable] = None,
    condition: Optional[Callable] = None,
) -> Callable:
    """
    Decorator for caching class methods.

    Args:
        ttl: Time-to-live in seconds
        backend: Cache backend to use
        key_prefix: Prefix for cache keys
        include_self: Whether to include self object in key generation
        include_args: Whether to include positional args in key
        include_kwargs: Whether to include keyword args in key
        exclude_args: List of arg indices to exclude from key
        exclude_kwargs: List of kwarg names to exclude from key
        key_generator: Custom key generation function
        condition: Function to determine if result should be cached

    Returns:
        Decorated method
    """

    def decorator(method):
        is_async = asyncio.iscoroutinefunction(method)

        # Adjust exclude_args to account for self parameter
        adjusted_exclude_args = (exclude_args or []).copy()
        if not include_self:
            adjusted_exclude_args.append(0)  # Exclude self (first argument)

        if is_async:
            cache_decorator = async_cached(
                ttl=ttl,
                backend=backend,
                key_prefix=key_prefix,
                include_args=include_args,
                include_kwargs=include_kwargs,
                exclude_args=adjusted_exclude_args,
                exclude_kwargs=exclude_kwargs,
                key_generator=key_generator,
                condition=condition,
            )
        else:
            cache_decorator = cached(
                ttl=ttl,
                backend=backend,
                key_prefix=key_prefix,
                include_args=include_args,
                include_kwargs=include_kwargs,
                exclude_args=adjusted_exclude_args,
                exclude_kwargs=exclude_kwargs,
                key_generator=key_generator,
                condition=condition,
            )

        return cache_decorator(method)

    return decorator


class CacheManager:
    """Manager for multiple cache instances and global operations."""

    def __init__(self):
        self.backends: Dict[str, CacheBackend] = {}
        self.cached_functions: list = []

    def register_backend(self, name: str, backend: CacheBackend) -> None:
        """Register a named cache backend."""
        self.backends[name] = backend

    def get_backend(self, name: str) -> Optional[CacheBackend]:
        """Get a registered cache backend."""
        return self.backends.get(name)

    def register_function(self, func: Callable) -> None:
        """Register a cached function for management."""
        if hasattr(func, "_cache_config"):
            self.cached_functions.append(func)

    async def clear_all_caches(self) -> Dict[str, int]:
        """Clear all registered cache backends."""
        results = {}
        for name, backend in self.backends.items():
            try:
                await backend.clear()
                results[name] = 0  # Success
            except Exception as e:
                logger.error(f"Failed to clear cache {name}: {e}")
                results[name] = -1  # Error
        return results

    async def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics from all registered cache backends."""
        return {name: backend.get_stats() for name, backend in self.backends.items()}

    async def invalidate_pattern(self, pattern: str) -> Dict[str, int]:
        """Invalidate keys matching pattern across all backends."""
        results = {}
        for name, backend in self.backends.items():
            try:
                keys = await backend.keys(pattern)
                count = 0
                for key in keys:
                    if await backend.delete(key):
                        count += 1
                results[name] = count
            except Exception as e:
                logger.error(f"Failed to invalidate pattern in cache {name}: {e}")
                results[name] = -1
        return results


# Global cache manager instance
cache_manager = CacheManager()


def configure_cache(backend_type: str = "memory", **kwargs) -> CacheBackend:
    """
    Configure and return a cache backend.

    Args:
        backend_type: Type of backend ('memory', 'redis', 'file', 'layered')
        **kwargs: Backend-specific configuration

    Returns:
        Configured cache backend
    """
    backend = create_backend(backend_type, **kwargs)
    cache_manager.register_backend(backend_type, backend)
    return backend


# Convenience decorators with pre-configured backends
def memory_cached(ttl: int = 300, **kwargs):
    """Convenience decorator for memory caching."""
    backend = MemoryBackend(default_ttl=ttl)
    return async_cached(ttl=ttl, backend=backend, **kwargs)


def redis_cached(ttl: int = 300, redis_url: str = "redis://localhost:6379", **kwargs):
    """Convenience decorator for Redis caching."""
    try:
        from .backends import RedisBackend

        backend = RedisBackend(redis_url=redis_url, default_ttl=ttl)
        return async_cached(ttl=ttl, backend=backend, **kwargs)
    except ImportError:
        logger.warning("Redis not available, falling back to memory cache")
        return memory_cached(ttl=ttl, **kwargs)


def file_cached(ttl: int = 300, cache_dir: str = "/tmp/cache", **kwargs):
    """Convenience decorator for file-based caching."""
    from .backends import FileBackend

    backend = FileBackend(cache_dir=cache_dir, default_ttl=ttl)
    return async_cached(ttl=ttl, backend=backend, **kwargs)


# Context manager for temporary cache configuration
class temporary_cache:
    """Context manager for temporary cache configuration."""

    def __init__(self, backend: CacheBackend):
        self.backend = backend
        self.original_backends = {}

    async def __aenter__(self):
        # Store original default backends
        self.original_backends = cache_manager.backends.copy()
        cache_manager.register_backend("temp", self.backend)
        return self.backend

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Restore original backends
        cache_manager.backends = self.original_backends


# Performance monitoring decorator
def monitor_cache_performance(func: Callable) -> Callable:
    """Decorator to add performance monitoring to cached functions."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        execution_time = (time.time() - start_time) * 1000

        # Log performance metrics
        logger.info(f"Function {func.__name__} executed in {execution_time:.2f}ms")

        # Record in cache stats if available
        if hasattr(func, "_cache_config"):
            config = func._cache_config
            if hasattr(config.backend, "stats"):
                config.backend.stats.record_response_time(execution_time)

        return result

    return wrapper
