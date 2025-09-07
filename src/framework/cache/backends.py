"""
Cache backend implementations for different storage mechanisms.

This module provides various backends for the caching system including
memory, Redis, file-based, and hybrid storage solutions.
"""

import asyncio
import json
import os
import pickle
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import aiofiles
import aiofiles.os
from loguru import logger

try:
    import redis.asyncio as redis  # type: ignore
except Exception:  # ImportError or other issues
    redis = None

from .cache import AsyncCache, CacheEntry, CacheStats, T


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    def __init__(self, default_ttl: int = 300, max_size: int = 1000):
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.stats = CacheStats()

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in the cache."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a value from the cache."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all values from the cache."""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        pass

    @abstractmethod
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get all keys matching a pattern."""
        pass

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return self.stats.to_dict()


class MemoryBackend(CacheBackend):
    """Memory-based cache backend using the AsyncCache implementation."""

    def __init__(
        self,
        default_ttl: int = 300,
        max_size: int = 1000,
        max_bytes: Optional[int] = None,
    ):
        super().__init__(default_ttl, max_size)
        self._cache = AsyncCache[Any](
            default_ttl=default_ttl, max_size=max_size, max_bytes=max_bytes
        )

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from the memory cache."""
        result = await self._cache.get(key)
        if result is not None:
            self.stats.record_hit()
        else:
            self.stats.record_miss()
        return result

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in the memory cache."""
        await self._cache.set(key, value, ttl or self.default_ttl)

    async def delete(self, key: str) -> bool:
        """Delete a value from the memory cache."""
        return await self._cache.invalidate(key)

    async def clear(self) -> None:
        """Clear all values from the memory cache."""
        await self._cache.clear()

    async def exists(self, key: str) -> bool:
        """Check if a key exists in the memory cache."""
        result = await self._cache.get(key)
        return result is not None

    async def keys(self, pattern: str = "*") -> List[str]:
        """Get all keys from the memory cache."""
        import fnmatch

        all_keys = list(self._cache.cache.keys())
        if pattern == "*":
            return all_keys
        return [key for key in all_keys if fnmatch.fnmatch(key, pattern)]

    def get_stats(self) -> Dict[str, Any]:
        """Get combined statistics from both backends."""
        memory_stats = self._cache.get_stats()
        base_stats = super().get_stats()
        return {**memory_stats, **base_stats}


class RedisBackend(CacheBackend):
    """Redis-based cache backend for distributed caching."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        default_ttl: int = 300,
        max_size: int = 1000,
        key_prefix: str = "cache:",
        serializer: str = "json",
    ):
        super().__init__(default_ttl, max_size)
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.serializer = serializer
        self._redis = None

        if redis is None:
            raise ImportError(
                "redis package is required for RedisBackend. Install with: pip install redis"
            )

    async def _get_redis(self):
        """Get or create Redis connection."""
        if self._redis is None:
            if redis is None:
                raise ImportError(
                    "redis package is required for RedisBackend. Install with: pip install redis"
                )
            self._redis = redis.from_url(self.redis_url)
        return self._redis

    def _serialize(self, value: Any) -> bytes:
        """Serialize value for storage."""
        if self.serializer == "json":
            return json.dumps(value, default=str).encode("utf-8")
        elif self.serializer == "pickle":
            return pickle.dumps(value)
        else:
            raise ValueError(f"Unsupported serializer: {self.serializer}")

    def _deserialize(self, data: bytes) -> Any:
        """Deserialize value from storage."""
        if self.serializer == "json":
            return json.loads(data.decode("utf-8"))
        elif self.serializer == "pickle":
            return pickle.loads(data)
        else:
            raise ValueError(f"Unsupported serializer: {self.serializer}")

    def _make_key(self, key: str) -> str:
        """Create prefixed key."""
        return f"{self.key_prefix}{key}"

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from Redis."""
        try:
            redis_client = await self._get_redis()
            data = await redis_client.get(self._make_key(key))

            if data:
                self.stats.record_hit()
                return self._deserialize(data)
            else:
                self.stats.record_miss()
                return None

        except Exception as e:
            logger.error(f"Redis get error for key {key}: {e}")
            self.stats.record_miss()
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in Redis."""
        try:
            redis_client = await self._get_redis()
            data = self._serialize(value)
            ttl = ttl or self.default_ttl

            await redis_client.setex(self._make_key(key), ttl, data)
            logger.debug(f"Set Redis key {key} with TTL {ttl}s")

        except Exception as e:
            logger.error(f"Redis set error for key {key}: {e}")

    async def delete(self, key: str) -> bool:
        """Delete a value from Redis."""
        try:
            redis_client = await self._get_redis()
            result = await redis_client.delete(self._make_key(key))
            return result > 0

        except Exception as e:
            logger.error(f"Redis delete error for key {key}: {e}")
            return False

    async def clear(self) -> None:
        """Clear all cache keys from Redis."""
        try:
            redis_client = await self._get_redis()
            keys = await redis_client.keys(f"{self.key_prefix}*")
            if keys:
                await redis_client.delete(*keys)
                logger.debug(f"Cleared {len(keys)} Redis cache keys")

        except Exception as e:
            logger.error(f"Redis clear error: {e}")

    async def exists(self, key: str) -> bool:
        """Check if a key exists in Redis."""
        try:
            redis_client = await self._get_redis()
            result = await redis_client.exists(self._make_key(key))
            return result > 0

        except Exception as e:
            logger.error(f"Redis exists error for key {key}: {e}")
            return False

    async def keys(self, pattern: str = "*") -> List[str]:
        """Get all keys matching a pattern from Redis."""
        try:
            redis_client = await self._get_redis()
            keys = await redis_client.keys(f"{self.key_prefix}{pattern}")
            # Remove prefix from keys
            return [key.decode("utf-8")[len(self.key_prefix) :] for key in keys]

        except Exception as e:
            logger.error(f"Redis keys error: {e}")
            return []

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()


class FileBackend(CacheBackend):
    """File-based cache backend for persistent caching."""

    def __init__(
        self,
        cache_dir: str = "/tmp/cache",
        default_ttl: int = 300,
        max_size: int = 1000,
        serializer: str = "json",
    ):
        super().__init__(default_ttl, max_size)
        self.cache_dir = Path(cache_dir)
        self.serializer = serializer
        self._lock = asyncio.Lock()

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, key: str) -> Path:
        """Get file path for a cache key."""
        # Use hash to avoid filesystem issues with key names
        import hashlib

        safe_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{safe_key}.cache"

    def _get_meta_path(self, key: str) -> Path:
        """Get metadata file path for a cache key."""
        import hashlib

        safe_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{safe_key}.meta"

    async def _serialize_to_file(self, file_path: Path, value: Any) -> None:
        """Serialize and write value to file."""
        if self.serializer == "json":
            async with aiofiles.open(file_path, "w") as f:
                await f.write(json.dumps(value, default=str))
        elif self.serializer == "pickle":
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(pickle.dumps(value))
        else:
            raise ValueError(f"Unsupported serializer: {self.serializer}")

    async def _deserialize_from_file(self, file_path: Path) -> Any:
        """Read and deserialize value from file."""
        if self.serializer == "json":
            async with aiofiles.open(file_path, "r") as f:
                content = await f.read()
                return json.loads(content)
        elif self.serializer == "pickle":
            async with aiofiles.open(file_path, "rb") as f:
                content = await f.read()
                return pickle.loads(content)
        else:
            raise ValueError(f"Unsupported serializer: {self.serializer}")

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from file cache."""
        file_path = self._get_file_path(key)
        meta_path = self._get_meta_path(key)

        try:
            async with self._lock:
                # Check if files exist
                if not file_path.exists() or not meta_path.exists():
                    self.stats.record_miss()
                    return None

                # Read metadata
                async with aiofiles.open(meta_path, "r") as f:
                    meta_content = await f.read()
                    metadata = json.loads(meta_content)

                # Check if expired
                if time.time() > metadata["expiry"]:
                    # Clean up expired files
                    await aiofiles.os.remove(file_path)
                    await aiofiles.os.remove(meta_path)
                    self.stats.record_miss()
                    return None

                # Read and deserialize value
                value = await self._deserialize_from_file(file_path)
                self.stats.record_hit()
                return value

        except Exception as e:
            logger.error(f"File cache get error for key {key}: {e}")
            self.stats.record_miss()
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in file cache."""
        file_path = self._get_file_path(key)
        meta_path = self._get_meta_path(key)
        ttl = ttl or self.default_ttl

        try:
            async with self._lock:
                # Write value
                await self._serialize_to_file(file_path, value)

                # Write metadata
                metadata = {
                    "key": key,
                    "expiry": time.time() + ttl,
                    "created_at": time.time(),
                }
                async with aiofiles.open(meta_path, "w") as f:
                    await f.write(json.dumps(metadata))

                logger.debug(f"Set file cache key {key} with TTL {ttl}s")

        except Exception as e:
            logger.error(f"File cache set error for key {key}: {e}")

    async def delete(self, key: str) -> bool:
        """Delete a value from file cache."""
        file_path = self._get_file_path(key)
        meta_path = self._get_meta_path(key)

        try:
            async with self._lock:
                deleted = False

                if file_path.exists():
                    await aiofiles.os.remove(file_path)
                    deleted = True

                if meta_path.exists():
                    await aiofiles.os.remove(meta_path)
                    deleted = True

                return deleted

        except Exception as e:
            logger.error(f"File cache delete error for key {key}: {e}")
            return False

    async def clear(self) -> None:
        """Clear all cache files."""
        try:
            async with self._lock:
                count = 0
                for file_path in self.cache_dir.glob("*.cache"):
                    await aiofiles.os.remove(file_path)
                    count += 1

                for meta_path in self.cache_dir.glob("*.meta"):
                    await aiofiles.os.remove(meta_path)

                logger.debug(f"Cleared {count} file cache entries")

        except Exception as e:
            logger.error(f"File cache clear error: {e}")

    async def exists(self, key: str) -> bool:
        """Check if a key exists in file cache."""
        result = await self.get(key)
        return result is not None

    async def keys(self, pattern: str = "*") -> List[str]:
        """Get all keys from file cache."""
        import fnmatch

        keys = []
        try:
            for meta_path in self.cache_dir.glob("*.meta"):
                try:
                    async with aiofiles.open(meta_path, "r") as f:
                        content = await f.read()
                        metadata = json.loads(content)
                        key = metadata["key"]

                        if pattern == "*" or fnmatch.fnmatch(key, pattern):
                            # Check if not expired
                            if time.time() <= metadata["expiry"]:
                                keys.append(key)

                except Exception:
                    continue

        except Exception as e:
            logger.error(f"File cache keys error: {e}")

        return keys


class LayeredBackend(CacheBackend):
    """Layered cache backend with L1 (fast) and L2 (persistent) layers."""

    def __init__(
        self, l1_backend: CacheBackend, l2_backend: CacheBackend, default_ttl: int = 300
    ):
        super().__init__(default_ttl)
        self.l1 = l1_backend  # Fast layer (usually memory)
        self.l2 = l2_backend  # Persistent layer (Redis/File)

    async def get(self, key: str) -> Optional[Any]:
        """Get value from L1 first, then L2."""
        # Try L1 first
        value = await self.l1.get(key)
        if value is not None:
            self.stats.record_hit()
            return value

        # Try L2
        value = await self.l2.get(key)
        if value is not None:
            # Populate L1 cache
            await self.l1.set(key, value)
            self.stats.record_hit()
            return value

        self.stats.record_miss()
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in both layers."""
        ttl = ttl or self.default_ttl

        # Set in both layers
        await asyncio.gather(
            self.l1.set(key, value, ttl),
            self.l2.set(key, value, ttl),
            return_exceptions=True,
        )

    async def delete(self, key: str) -> bool:
        """Delete from both layers."""
        results = await asyncio.gather(
            self.l1.delete(key), self.l2.delete(key), return_exceptions=True
        )
        return any(isinstance(r, bool) and r for r in results)

    async def clear(self) -> None:
        """Clear both layers."""
        await asyncio.gather(self.l1.clear(), self.l2.clear(), return_exceptions=True)

    async def exists(self, key: str) -> bool:
        """Check existence in either layer."""
        l1_exists = await self.l1.exists(key)
        if l1_exists:
            return True

        return await self.l2.exists(key)

    async def keys(self, pattern: str = "*") -> List[str]:
        """Get keys from both layers (deduplicated)."""
        l1_keys, l2_keys = await asyncio.gather(
            self.l1.keys(pattern), self.l2.keys(pattern), return_exceptions=True
        )

        all_keys = set()
        if isinstance(l1_keys, list):
            all_keys.update(l1_keys)
        if isinstance(l2_keys, list):
            all_keys.update(l2_keys)

        return list(all_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get combined statistics from both layers."""
        return {
            "layered": super().get_stats(),
            "l1": self.l1.get_stats(),
            "l2": self.l2.get_stats(),
        }


# Backend factory function
def create_backend(backend_type: str, **kwargs) -> CacheBackend:
    """
    Factory function to create cache backends.

    Args:
        backend_type: Type of backend ('memory', 'redis', 'file', 'layered')
        **kwargs: Backend-specific configuration

    Returns:
        Configured cache backend instance
    """
    if backend_type == "memory":
        return MemoryBackend(**kwargs)
    elif backend_type == "redis":
        return RedisBackend(**kwargs)
    elif backend_type == "file":
        return FileBackend(**kwargs)
    elif backend_type == "layered":
        l1_config = kwargs.get("l1", {"type": "memory"})
        l2_config = kwargs.get("l2", {"type": "file"})

        l1_type = l1_config.pop("type")
        l2_type = l2_config.pop("type")

        l1_backend = create_backend(l1_type, **l1_config)
        l2_backend = create_backend(l2_type, **l2_config)

        return LayeredBackend(l1_backend, l2_backend, **kwargs)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")
