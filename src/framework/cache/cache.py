"""
Asynchronous cache implementation.

This module provides a comprehensive asynchronous caching solution
with thread-safety, key generation, and performance monitoring.
"""

import asyncio
import hashlib
import json
import re
import sys
import time
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    TypeVar,
    Union,
    cast,
)

from loguru import logger

# Type variable for better type hinting
T = TypeVar("T")


class CacheEntry(Generic[T]):
    """Represents a cached response with metadata."""

    def __init__(self, data: T, expiry: float):
        self.data = data
        self.expiry = expiry  # Timestamp when this entry expires
        self.created_at = time.time()
        self.hit_count = 0
        self.last_accessed = time.time()

        # Estimate size of cached data
        try:
            if data is not None:
                # Rough size estimation using JSON serialization
                self.size_bytes = len(json.dumps(data, default=str).encode("utf-8"))
            else:
                self.size_bytes = 0
        except (TypeError, OverflowError):
            # For objects that can't be JSON serialized
            self.size_bytes = sys.getsizeof(data) if data is not None else 0

    @property
    def is_expired(self) -> bool:
        """Check if the entry is expired."""
        return time.time() > self.expiry

    @property
    def age(self) -> float:
        """Get the age of this cache entry in seconds."""
        return time.time() - self.created_at

    def record_hit(self) -> None:
        """Record a cache hit."""
        self.hit_count += 1
        self.last_accessed = time.time()


class CacheStats:
    """Statistics for cache performance."""

    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0
        self.total_size_bytes = 0
        self.creation_time = time.time()
        self.response_times: List[float] = []  # List of response times in ms

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0

    @property
    def avg_response_time(self) -> float:
        """Calculate average response time in milliseconds."""
        if not self.response_times:
            return 0
        return sum(self.response_times) / len(self.response_times)

    def record_hit(self) -> None:
        """Record a cache hit."""
        self.hits += 1

    def record_miss(self) -> None:
        """Record a cache miss."""
        self.misses += 1

    def record_eviction(self) -> None:
        """Record a cache eviction."""
        self.evictions += 1

    def record_expiration(self) -> None:
        """Record a cache expiration."""
        self.expirations += 1

    def record_response_time(self, time_ms: float) -> None:
        """Record function execution time."""
        self.response_times.append(time_ms)
        # Keep only the most recent 1000 response times to limit memory usage
        if len(self.response_times) > 1000:
            self.response_times = self.response_times[-1000:]

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "hit_rate": f"{self.hit_rate:.2%}",
            "size_bytes": self.total_size_bytes,
            "uptime_seconds": time.time() - self.creation_time,
            "avg_response_time_ms": (
                f"{self.avg_response_time:.2f}" if self.response_times else "N/A"
            ),
        }


class AsyncCache(Generic[T]):
    """Thread-safe asynchronous cache implementation."""

    def __init__(
        self,
        default_ttl: int = 300,
        max_size: int = 1000,
        max_bytes: Optional[int] = None,
    ):
        """
        Initialize the cache.

        Args:
            default_ttl: Default time-to-live in seconds for cache entries
            max_size: Maximum number of entries to store
            max_bytes: Maximum cache size in bytes (optional)
        """
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.max_bytes = max_bytes
        self.cache: Dict[str, CacheEntry[T]] = {}
        self.stats = CacheStats()
        self._lock = asyncio.Lock()  # Async lock for thread safety

    async def _generate_key(
        self, func_name: str, args: tuple, kwargs: dict, include_args: bool = True
    ) -> str:
        """
        Generate a cache key from the function and its arguments.

        Args:
            func_name: The fully qualified function name
            args: Positional arguments
            kwargs: Keyword arguments
            include_args: Whether to include arguments in key generation

        Returns:
            MD5 hash string to use as cache key
        """
        key_parts = [func_name]

        if not include_args:
            # Skip arguments when generating the key
            return hashlib.md5(func_name.encode()).hexdigest()

        try:
            # Try to serialize all arguments
            if args:
                args_str = json.dumps(args, sort_keys=True, default=str)
                # Hash long argument strings to keep keys manageable
                if len(args_str) > 100:
                    args_str = hashlib.md5(args_str.encode()).hexdigest()
                key_parts.append(args_str)

            if kwargs:
                kwargs_str = json.dumps(
                    sorted(kwargs.items()), sort_keys=True, default=str
                )
                # Hash long kwargs strings
                if len(kwargs_str) > 100:
                    kwargs_str = hashlib.md5(kwargs_str.encode()).hexdigest()
                key_parts.append(kwargs_str)

        except (TypeError, ValueError):
            # Fallback for non-serializable objects
            for arg in args:
                if isinstance(arg, (str, int, float, bool, type(None))):
                    key_parts.append(str(arg))
                else:
                    key_parts.append(f"id:{id(arg)}")

            for k, v in sorted(kwargs.items()):
                if isinstance(v, (str, int, float, bool, type(None))):
                    key_parts.append(f"{k}:{v}")
                else:
                    key_parts.append(f"{k}:id:{id(v)}")

        key_string = ":".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    async def get(self, key: str) -> Optional[T]:
        """
        Get an entry from the cache if it exists and is not expired.

        Args:
            key: Cache key

        Returns:
            Cached data or None if not found or expired
        """
        async with self._lock:
            entry = self.cache.get(key)

            if entry and not entry.is_expired:
                entry.record_hit()
                self.stats.record_hit()
                logger.debug(f"Async cache hit for key: {key}")
                return entry.data

            if entry and entry.is_expired:
                logger.debug(f"Async cache entry expired for key: {key}")
                self.stats.record_expiration()
                self.stats.total_size_bytes -= entry.size_bytes
                del self.cache[key]
            else:
                logger.debug(f"Async cache miss for key: {key}")

            self.stats.record_miss()
            return None

    async def set(self, key: str, data: T, ttl: Optional[int] = None) -> None:
        """
        Store a response in the cache.

        Args:
            key: Cache key
            data: Data to cache
            ttl: Time-to-live in seconds (uses default if not specified)
        """
        async with self._lock:
            # Create the entry first to get its size
            ttl = ttl if ttl is not None else self.default_ttl
            expiry = time.time() + ttl
            entry = CacheEntry(data, expiry)

            # Check size constraints
            if self.max_bytes and entry.size_bytes > self.max_bytes:
                logger.warning(
                    f"Entry too large to cache: {entry.size_bytes} bytes exceeds max {self.max_bytes}"
                )
                return

            # Manage cache size
            if len(self.cache) >= self.max_size or (
                self.max_bytes
                and self.stats.total_size_bytes + entry.size_bytes > self.max_bytes
            ):
                await self._evict_entries(required_bytes=entry.size_bytes)

            # If replacing an existing entry, subtract its size first
            if key in self.cache:
                self.stats.total_size_bytes -= self.cache[key].size_bytes

            self.cache[key] = entry
            self.stats.total_size_bytes += entry.size_bytes
            logger.debug(
                f"Cached async response for key: {key}, expires in {ttl}s, size: {entry.size_bytes} bytes"
            )

    async def _evict_entries(self, required_bytes: int = 0) -> None:
        """
        Evict entries to make space in the cache.

        Args:
            required_bytes: How many bytes are needed for a new entry
        """
        async with self._lock:
            # First remove expired entries
            expired_keys = [k for k, v in self.cache.items() if v.is_expired]
            for key in expired_keys:
                self.stats.total_size_bytes -= self.cache[key].size_bytes
                del self.cache[key]
                self.stats.record_expiration()
                logger.debug(f"Evicted expired async cache entry: {key}")

            # If still need space, remove least recently used entries
            if (
                self.max_bytes
                and self.stats.total_size_bytes + required_bytes > self.max_bytes
            ):
                # Sort by last accessed time (oldest first)
                sorted_entries = sorted(
                    self.cache.items(), key=lambda x: x[1].last_accessed
                )

                bytes_to_free = required_bytes
                for key, entry in sorted_entries:
                    if self.stats.total_size_bytes + bytes_to_free <= self.max_bytes:
                        break

                    self.stats.total_size_bytes -= entry.size_bytes
                    bytes_to_free = max(0, bytes_to_free - entry.size_bytes)
                    del self.cache[key]
                    self.stats.record_eviction()
                    logger.debug(
                        f"Evicted async cache entry due to size constraints: {key}"
                    )

            # If still too many entries, remove by count limit
            if len(self.cache) >= self.max_size:
                sorted_entries = sorted(
                    self.cache.items(), key=lambda x: x[1].last_accessed
                )
                entries_to_remove = (
                    len(self.cache) - self.max_size + 10
                )  # Remove extra to avoid frequent evictions

                for i in range(min(entries_to_remove, len(sorted_entries))):
                    key, entry = sorted_entries[i]
                    self.stats.total_size_bytes -= entry.size_bytes
                    del self.cache[key]
                    self.stats.record_eviction()
                    logger.debug(f"Evicted least used async cache entry: {key}")

    async def invalidate(self, key: str) -> bool:
        """
        Invalidate a specific cache entry.

        Args:
            key: Cache key

        Returns:
            True if an entry was found and removed, False otherwise
        """
        async with self._lock:
            if key in self.cache:
                self.stats.total_size_bytes -= self.cache[key].size_bytes
                del self.cache[key]
                logger.debug(f"Manually invalidated async cache entry: {key}")
                return True
            return False

    async def invalidate_by_pattern(self, pattern: str) -> int:
        """
        Invalidate cache entries matching a pattern.

        Args:
            pattern: Regex pattern to match against keys

        Returns:
            Number of entries invalidated
        """
        try:
            regex = re.compile(pattern)
        except re.error:
            logger.error(f"Invalid regex pattern for cache invalidation: {pattern}")
            return 0

        count = 0

        async with self._lock:
            keys_to_remove = [k for k in self.cache.keys() if regex.search(k)]
            for key in keys_to_remove:
                self.stats.total_size_bytes -= self.cache[key].size_bytes
                del self.cache[key]
                count += 1

        if count > 0:
            logger.debug(f"Invalidated {count} entries matching pattern: {pattern}")
        return count

    async def clear(self) -> None:
        """Clear the entire cache."""
        async with self._lock:
            count = len(self.cache)
            self.cache.clear()
            self.stats.total_size_bytes = 0
            logger.debug(f"Cleared entire async cache ({count} entries)")

    def clear_sync(self) -> None:
        """
        Clear the entire cache synchronously.

        This method is intended for use in synchronous contexts where awaiting
        the async clear() method is not possible. Use with caution.
        """
        count = len(self.cache)
        self.cache.clear()
        self.stats.total_size_bytes = 0
        logger.debug(f"Cleared entire async cache synchronously ({count} entries)")

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the cache performance."""
        return {
            **self.stats.to_dict(),
            "entry_count": len(self.cache),
            "capacity": f"{len(self.cache)}/{self.max_size}",
            "memory_usage": f"{self.stats.total_size_bytes / (1024*1024):.2f} MB",
        }

    async def refresh(
        self, key: str, refresh_func: Callable[[], Awaitable[T]]
    ) -> Optional[T]:
        """
        Refresh a cache entry by calling a function and updating the cache.

        Args:
            key: Cache key to refresh
            refresh_func: Async function to call for refreshing the value

        Returns:
            Updated cache value or None if refresh failed
        """
        try:
            # Call the refresh function
            new_value = await refresh_func()

            # Update the cache with the new value
            if new_value is not None:
                await self.set(key, new_value)

            return new_value
        except Exception as e:
            logger.error(f"Error refreshing cache entry {key}: {e}")
            return None

    async def get_or_set(
        self,
        key: str,
        value_func: Callable[[], Awaitable[T]],
        ttl: Optional[int] = None,
    ) -> T:
        """
        Get a value from cache or compute and store it if not available.

        Args:
            key: Cache key
            value_func: Async function to call if cache miss
            ttl: Time-to-live in seconds (uses default if not specified)

        Returns:
            Cached value (either existing or newly computed)
        """
        # Try to get from cache first
        cached_value = await self.get(key)
        if cached_value is not None:
            return cached_value

        # Cache miss, compute value
        start_time = time.time()
        value = await value_func()
        execution_time = (time.time() - start_time) * 1000  # ms

        # Record execution time for stats
        self.stats.record_response_time(execution_time)

        # Cache the result if not None
        if value is not None:
            await self.set(key, value, ttl=ttl)

        return value


# Registry of named async caches
_cache_registry: Dict[str, AsyncCache] = {}


def get_async_cache(
    name: str = "default", max_size: int = 1000, max_bytes: Optional[int] = None
) -> AsyncCache:
    """
    Get or create a named async cache instance.

    Args:
        name: Unique name for the cache
        max_size: Maximum number of entries to store
        max_bytes: Maximum cache size in bytes (optional)

    Returns:
        An AsyncCache instance
    """
    if name not in _cache_registry:
        _cache_registry[name] = AsyncCache(max_size=max_size, max_bytes=max_bytes)
    return _cache_registry[name]


async def clear_all_async_caches() -> None:
    """Clear all async caches in the registry."""
    for cache_name, cache in _cache_registry.items():
        await cache.clear()
        logger.debug(f"Cleared async cache: {cache_name}")


def get_all_async_cache_stats() -> Dict[str, Dict[str, Any]]:
    """Get statistics for all async caches."""
    return {name: cache.get_stats() for name, cache in _cache_registry.items()}
