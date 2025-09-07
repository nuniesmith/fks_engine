import json
import time
from typing import Any, Callable, Dict, List, Optional, Union

import backoff
from core import StateProvider
from loguru import logger


class RedisStateProvider(StateProvider):
    """
    Redis-based implementation of state persistence.

    This implementation uses Redis for storing circuit breaker state, supporting
    both standalone Redis and Redis Cluster configurations. It handles serialization,
    connection errors, and provides additional Redis-specific features.

    Attributes:
        ttl_seconds: Time-to-live in seconds for stored state (0 = no expiration)
        namespace: Optional namespace prefix for all keys
        retry_attempts: Number of retry attempts for Redis operations
        logger: Logger instance for error reporting
    """

    def __init__(
        self,
        redis_client,
        ttl_seconds: int = 0,
        namespace: str = "circuit_breaker:",
        retry_attempts: int = 3,
    ):
        """
        Initialize with a Redis client.

        Args:
            redis_client: An initialized Redis client instance
            ttl_seconds: Time-to-live in seconds for stored state (0 = no expiration)
            namespace: Optional namespace prefix for all keys
            retry_attempts: Number of retry attempts for Redis operations
        """
        self.redis_client = redis_client
        self.ttl_seconds = ttl_seconds
        self.namespace = namespace
        self.retry_attempts = retry_attempts
        self.logger = logger

        # Detect Redis client capabilities
        self._detect_client_capabilities()

    def _detect_client_capabilities(self) -> None:
        """Detect which Redis client we're using and its capabilities."""
        client_type = str(type(self.redis_client).__name__)

        # Default methods
        self._set_method = self._set_regular
        self._get_method = self._get_regular
        self._delete_method = self._delete_regular
        self._scan_method = self._scan_regular

        # Check for redis-py's Redis class
        if "Redis" in client_type:
            # Check if client supports JSON operations
            if hasattr(self.redis_client, "json"):
                self._set_method = self._set_json
                self._get_method = self._get_json

        # Check for redis-py-cluster's RedisCluster
        if "RedisCluster" in client_type:
            self._scan_method = self._scan_cluster

    def _make_key(self, key: str) -> str:
        """Create a full key with namespace."""
        return f"{self.namespace}{key}" if self.namespace else key

    def serialize(self, data: Dict[str, Any]) -> str:
        """
        Serialize data to a string for storage in Redis.

        Args:
            data: Dictionary data to serialize

        Returns:
            JSON string representation of the data
        """
        return json.dumps(data)

    def deserialize(self, data: Union[str, bytes]) -> Dict[str, Any]:
        """
        Deserialize data from Redis into a dictionary.

        Args:
            data: String or bytes data from Redis

        Returns:
            Dictionary representation of the data
        """
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return json.loads(data)

    @backoff.on_exception(backoff.expo, (ConnectionError, TimeoutError), max_tries=3)
    def persist_state(self, key: str, state: Dict[str, Any]) -> bool:
        """
        Persist the circuit breaker state to Redis.

        Args:
            key: The key under which to store the state
            state: The state data to store

        Returns:
            True if the state was successfully persisted, False otherwise

        Raises:
            ConnectionError: If unable to connect to Redis after retries
        """
        try:
            full_key = self._make_key(key)
            result = self._set_method(full_key, state)

            # Set TTL if specified
            if self.ttl_seconds > 0:
                self.redis_client.expire(full_key, self.ttl_seconds)

            return result
        except Exception as e:
            self.logger.error(
                f"Error persisting state to Redis for key {key}: {str(e)}"
            )
            # Propagate connection errors after retries, otherwise return False
            if isinstance(e, (ConnectionError, TimeoutError)):
                raise
            return False

    @backoff.on_exception(backoff.expo, (ConnectionError, TimeoutError), max_tries=3)
    def retrieve_state(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve the circuit breaker state from Redis.

        Args:
            key: The key to retrieve

        Returns:
            The stored state or None if not found

        Raises:
            ConnectionError: If unable to connect to Redis after retries
        """
        try:
            full_key = self._make_key(key)
            return self._get_method(full_key)
        except Exception as e:
            self.logger.error(
                f"Error retrieving state from Redis for key {key}: {str(e)}"
            )
            # Propagate connection errors after retries, otherwise return None
            if isinstance(e, (ConnectionError, TimeoutError)):
                raise
            return None

    @backoff.on_exception(backoff.expo, (ConnectionError, TimeoutError), max_tries=3)
    def delete_state(self, key: str) -> bool:
        """
        Delete the state for the given key.

        Args:
            key: The key to delete

        Returns:
            True if the state was successfully deleted, False if key not found

        Raises:
            ConnectionError: If unable to connect to Redis after retries
        """
        try:
            full_key = self._make_key(key)
            result = self._delete_method(full_key)
            return result > 0
        except Exception as e:
            self.logger.error(
                f"Error deleting state from Redis for key {key}: {str(e)}"
            )
            # Propagate connection errors after retries, otherwise return False
            if isinstance(e, (ConnectionError, TimeoutError)):
                raise
            return False

    @backoff.on_exception(backoff.expo, (ConnectionError, TimeoutError), max_tries=3)
    def update_state(self, key: str, updates: Dict[str, Any]) -> bool:
        """
        Update parts of the state for the given key.

        For Redis JSON clients, we use partial updates.
        For regular Redis, we use a transaction to ensure atomicity.

        Args:
            key: The key to update
            updates: Dictionary of updates to apply to the state

        Returns:
            True if the state was successfully updated, False if key not found

        Raises:
            ConnectionError: If unable to connect to Redis after retries
            KeyError: If the key does not exist
        """
        try:
            full_key = self._make_key(key)

            # Check if the key exists
            if not self.redis_client.exists(full_key):
                raise KeyError(f"No state found for key '{key}'")

            # Try to use optimized Redis JSON update if available
            if hasattr(self.redis_client, "json"):
                for field, value in updates.items():
                    self.redis_client.json().set(full_key, f".{field}", value)

                # Reset TTL if specified
                if self.ttl_seconds > 0:
                    self.redis_client.expire(full_key, self.ttl_seconds)

                return True
            else:
                # Use Redis transaction for atomicity
                with self.redis_client.pipeline() as pipe:
                    while True:
                        try:
                            # Watch the key for changes
                            pipe.watch(full_key)

                            # Get current state
                            current_data = self._get_regular(full_key)
                            if current_data is None:
                                raise KeyError(f"No state found for key '{key}'")

                            # Update the state
                            current_data.update(updates)

                            # Execute transaction
                            pipe.multi()
                            pipe.set(full_key, self.serialize(current_data))

                            # Set TTL if specified
                            if self.ttl_seconds > 0:
                                pipe.expire(full_key, self.ttl_seconds)

                            pipe.execute()
                            return True
                        except backoff.redis.WatchError:
                            # Key changed during transaction, retry
                            continue
                        break

        except KeyError:
            # Re-raise KeyError for consistent behavior with base class
            raise
        except Exception as e:
            self.logger.error(f"Error updating state in Redis for key {key}: {str(e)}")
            # Propagate connection errors after retries, otherwise return False
            if isinstance(e, (ConnectionError, TimeoutError)):
                raise
            return False

    @backoff.on_exception(backoff.expo, (ConnectionError, TimeoutError), max_tries=3)
    def exists(self, key: str) -> bool:
        """
        Check if a state exists for the given key.

        Args:
            key: The key to check

        Returns:
            True if the state exists, False otherwise

        Raises:
            ConnectionError: If unable to connect to Redis after retries
        """
        try:
            full_key = self._make_key(key)
            return bool(self.redis_client.exists(full_key))
        except Exception as e:
            self.logger.error(f"Error checking if key exists in Redis: {key}: {str(e)}")
            # Propagate connection errors after retries, otherwise return False
            if isinstance(e, (ConnectionError, TimeoutError)):
                raise
            return False

    @backoff.on_exception(backoff.expo, (ConnectionError, TimeoutError), max_tries=3)
    def list_keys(self, prefix: str = "") -> List[str]:
        """
        List all keys with the given prefix.

        Args:
            prefix: Prefix to filter keys by

        Returns:
            List of keys with the given prefix

        Raises:
            ConnectionError: If unable to connect to Redis after retries
        """
        try:
            full_prefix = self._make_key(prefix)
            pattern = f"{full_prefix}*"

            # Use the appropriate scan method based on client type
            keys = self._scan_method(pattern)

            # Remove namespace prefix from results if necessary
            if self.namespace:
                return [key[len(self.namespace) :] for key in keys]
            return keys
        except Exception as e:
            self.logger.error(f"Error listing keys in Redis: {str(e)}")
            # Propagate connection errors after retries, otherwise return empty list
            if isinstance(e, (ConnectionError, TimeoutError)):
                raise
            return []

    @backoff.on_exception(backoff.expo, (ConnectionError, TimeoutError), max_tries=3)
    def clear_all(self, prefix: str = "") -> bool:
        """
        Clear all states with the given prefix.

        Args:
            prefix: Prefix to filter keys by

        Returns:
            True if all states were successfully cleared, False otherwise

        Raises:
            ConnectionError: If unable to connect to Redis after retries
        """
        try:
            # Get all keys matching the prefix
            keys = self.list_keys(prefix)

            if not keys:
                return True  # Nothing to delete

            # Delete all matching keys
            full_keys = [self._make_key(key) for key in keys]

            # Use pipeline for batch deletion
            pipeline = self.redis_client.pipeline()
            for key in full_keys:
                pipeline.delete(key)

            pipeline.execute()
            return True
        except Exception as e:
            self.logger.error(f"Error clearing keys in Redis: {str(e)}")
            # Propagate connection errors after retries, otherwise return False
            if isinstance(e, (ConnectionError, TimeoutError)):
                raise
            return False

    def initialize(self) -> None:
        """
        Initialize the state provider. Checks Redis connection.

        Raises:
            ConnectionError: If unable to connect to Redis
        """
        try:
            # Check if Redis is available
            self.redis_client.ping()
        except Exception as e:
            raise ConnectionError(f"Unable to connect to Redis: {str(e)}")

    def shutdown(self) -> None:
        """Shutdown the state provider. Close Redis connection pool if possible."""
        try:
            # Some Redis clients have connection pools that can be closed
            if hasattr(self.redis_client, "connection_pool") and hasattr(
                self.redis_client.connection_pool, "disconnect"
            ):
                self.redis_client.connection_pool.disconnect()
        except Exception as e:
            self.logger.warning(f"Error shutting down Redis connection: {str(e)}")

    def health_check(self) -> bool:
        """
        Check if the state provider is healthy.

        Returns:
            True if the provider is healthy, False otherwise
        """
        try:
            # Check if Redis is available
            return bool(self.redis_client.ping())
        except Exception:
            return False

    # Different Redis client implementations

    def _set_json(self, key: str, value: Dict[str, Any]) -> bool:
        """Set method for Redis clients with JSON support."""
        return bool(self.redis_client.json().set(key, "$", value))

    def _get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Get method for Redis clients with JSON support."""
        result = self.redis_client.json().get(key)
        return result

    def _set_regular(self, key: str, value: Dict[str, Any]) -> bool:
        """Set method for regular Redis clients."""
        serialized = self.serialize(value)
        return bool(self.redis_client.set(key, serialized))

    def _get_regular(self, key: str) -> Optional[Dict[str, Any]]:
        """Get method for regular Redis clients."""
        result = self.redis_client.get(key)
        if result is None:
            return None
        return self.deserialize(result)

    def _delete_regular(self, key: str) -> int:
        """Delete method for regular Redis clients."""
        return self.redis_client.delete(key)

    def _scan_regular(self, pattern: str) -> List[str]:
        """Scan method for regular Redis clients."""
        keys = []
        cursor = 0
        while True:
            cursor, results = self.redis_client.scan(cursor, match=pattern, count=100)
            keys.extend(
                [k.decode("utf-8") if isinstance(k, bytes) else k for k in results]
            )
            if cursor == 0:
                break
        return keys

    def _scan_cluster(self, pattern: str) -> List[str]:
        """Scan method for Redis Cluster clients."""
        keys = []
        # For Redis Cluster, we need to scan each master node
        for node_keys in self.redis_client.scan_iter(match=pattern, count=100):
            if isinstance(node_keys, bytes):
                node_keys = node_keys.decode("utf-8")
            keys.append(node_keys)
        return keys
