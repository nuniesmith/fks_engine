import copy
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import StateProvider  # Fixed import


class MemoryStateProvider(StateProvider):
    """
    In-memory implementation of state persistence.

    This implementation stores all state in memory using a dictionary.
    It provides thread-safe operations and optional TTL-based expiration.

    Attributes:
        ttl_seconds: Time-to-live in seconds for stored state (0 = no expiration)
        deep_copy: Whether to make deep copies of state when storing/retrieving
    """

    def __init__(self, ttl_seconds: int = 0, deep_copy: bool = True):
        """
        Initialize the memory state provider.

        Args:
            ttl_seconds: Time-to-live in seconds for stored state (0 = no expiration)
            deep_copy: Whether to make deep copies of state when storing/retrieving
        """
        # Storage structure: {key: (state_dict, expiration_timestamp)}
        self._storage: Dict[str, Tuple[Dict[str, Any], float]] = {}
        self._lock = threading.RLock()
        self.ttl_seconds = ttl_seconds
        self.deep_copy = deep_copy

        # Statistics
        self._stats = {
            "total_reads": 0,
            "total_writes": 0,
            "total_deletes": 0,
            "total_updates": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "expired_entries_removed": 0,
        }

    def persist_state(self, key: str, state: Dict[str, Any]) -> bool:
        """
        Persist the circuit breaker state in memory.

        Args:
            key: The key under which to store the state
            state: The state data to store

        Returns:
            True if the state was successfully persisted
        """
        with self._lock:
            try:
                # Calculate expiration time if TTL is set
                expiration = 0
                if self.ttl_seconds > 0:
                    expiration = time.time() + self.ttl_seconds

                # Store state with optional deep copy
                if self.deep_copy:
                    self._storage[key] = (copy.deepcopy(state), expiration)
                else:
                    self._storage[key] = (state, expiration)

                self._stats["total_writes"] += 1
                return True
            except Exception as e:
                # This should rarely happen with in-memory storage
                # but we catch exceptions for consistency with the interface
                print(f"Error persisting state for key {key}: {str(e)}")
                return False

    def retrieve_state(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve the circuit breaker state from memory.

        Args:
            key: The key to retrieve

        Returns:
            The stored state or None if not found or expired
        """
        with self._lock:
            self._stats["total_reads"] += 1
            self._remove_expired_entries()

            if key not in self._storage:
                self._stats["cache_misses"] += 1
                return None

            state, expiration = self._storage[key]

            # Check if entry has expired
            if expiration > 0 and time.time() > expiration:
                del self._storage[key]
                self._stats["cache_misses"] += 1
                self._stats["expired_entries_removed"] += 1
                return None

            self._stats["cache_hits"] += 1

            # Return state with optional deep copy
            if self.deep_copy:
                return copy.deepcopy(state)
            else:
                return state

    def delete_state(self, key: str) -> bool:
        """
        Delete the state for the given key.

        Args:
            key: The key to delete

        Returns:
            True if the state was successfully deleted, False if key not found
        """
        with self._lock:
            if key in self._storage:
                del self._storage[key]
                self._stats["total_deletes"] += 1
                return True
            return False

    def update_state(self, key: str, updates: Dict[str, Any]) -> bool:
        """
        Update parts of the state for the given key.

        Args:
            key: The key to update
            updates: Dictionary of updates to apply to the state

        Returns:
            True if the state was successfully updated, False if key not found

        Raises:
            KeyError: If the key does not exist
        """
        with self._lock:
            if key not in self._storage:
                raise KeyError(f"No state found for key '{key}'")

            state, expiration = self._storage[key]

            # Check if entry has expired
            if expiration > 0 and time.time() > expiration:
                del self._storage[key]
                self._stats["expired_entries_removed"] += 1
                raise KeyError(f"State for key '{key}' has expired")

            # Update the state
            state.update(updates)

            # Reset expiration if TTL is enabled
            if self.ttl_seconds > 0:
                expiration = time.time() + self.ttl_seconds

            self._storage[key] = (state, expiration)
            self._stats["total_updates"] += 1
            return True

    def exists(self, key: str) -> bool:
        """
        Check if a state exists for the given key.

        Args:
            key: The key to check

        Returns:
            True if the state exists and is not expired, False otherwise
        """
        with self._lock:
            self._remove_expired_entries()

            if key not in self._storage:
                return False

            _, expiration = self._storage[key]

            # Check if entry has expired
            if expiration > 0 and time.time() > expiration:
                del self._storage[key]
                self._stats["expired_entries_removed"] += 1
                return False

            return True

    def list_keys(self, prefix: str = "") -> List[str]:
        """
        List all keys with the given prefix.

        Args:
            prefix: Prefix to filter keys by

        Returns:
            List of keys with the given prefix
        """
        with self._lock:
            self._remove_expired_entries()

            keys = []
            for key in self._storage.keys():
                if key.startswith(prefix):
                    # Check if entry has expired
                    _, expiration = self._storage[key]
                    if expiration == 0 or time.time() <= expiration:
                        keys.append(key)

            return keys

    def clear_all(self, prefix: str = "") -> bool:
        """
        Clear all states with the given prefix.

        Args:
            prefix: Prefix to filter keys by

        Returns:
            True if all states were successfully cleared
        """
        with self._lock:
            if not prefix:
                # Clear everything
                self._storage.clear()
                return True

            # Clear matching keys
            keys_to_delete = [k for k in self._storage.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                del self._storage[key]
                self._stats["total_deletes"] += 1

            return True

    def initialize(self) -> None:
        """
        Initialize the state provider. No-op for memory provider.
        """
        # No specific initialization needed for in-memory provider
        pass

    def shutdown(self) -> None:
        """
        Shutdown the state provider. Clears all state.
        """
        with self._lock:
            self._storage.clear()

    def health_check(self) -> bool:
        """
        Check if the state provider is healthy.

        Returns:
            True if the provider is healthy (always true for in-memory)
        """
        return True

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the state provider.

        Returns:
            Dictionary of statistics
        """
        with self._lock:
            stats = dict(self._stats)
            stats["current_entries"] = len(self._storage)
            stats["memory_usage_estimate"] = self._estimate_memory_usage()
            return stats

    def reset_stats(self) -> None:
        """
        Reset all statistics counters.
        """
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0

    def _remove_expired_entries(self) -> None:
        """Remove all expired entries from storage."""
        if self.ttl_seconds <= 0:
            return  # No expiration

        now = time.time()
        expired_keys = []

        # Find expired keys
        for key, (_, expiration) in self._storage.items():
            if expiration > 0 and now > expiration:
                expired_keys.append(key)

        # Remove expired keys
        for key in expired_keys:
            del self._storage[key]
            self._stats["expired_entries_removed"] += 1

    def _estimate_memory_usage(self) -> int:
        """
        Estimate memory usage in bytes.

        This is a rough estimate and may not be completely accurate.

        Returns:
            Estimated memory usage in bytes
        """
        import sys

        total_size = 0
        try:
            # Estimate size of the storage dictionary
            total_size += sys.getsizeof(self._storage)

            # Estimate size of stored data
            for key, (state, expiration) in self._storage.items():
                total_size += sys.getsizeof(key)
                total_size += sys.getsizeof(state)
                total_size += sys.getsizeof(expiration)

                # Rough estimate of dictionary contents
                for k, v in state.items():
                    total_size += sys.getsizeof(k) + sys.getsizeof(v)

        except Exception:
            # If size estimation fails, return 0
            total_size = 0

        return total_size

    def compact(self) -> int:
        """
        Remove expired entries and return the number of entries removed.

        This can be called periodically to clean up expired entries
        and free memory.

        Returns:
            Number of expired entries removed
        """
        with self._lock:
            initial_count = len(self._storage)
            self._remove_expired_entries()
            final_count = len(self._storage)
            return initial_count - final_count

    def get_entry_info(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific entry.

        Args:
            key: The key to get information for

        Returns:
            Dictionary with entry information or None if not found
        """
        with self._lock:
            if key not in self._storage:
                return None

            state, expiration = self._storage[key]

            now = time.time()
            is_expired = expiration > 0 and now > expiration
            time_to_expiry = max(0, expiration - now) if expiration > 0 else None

            return {
                "key": key,
                "exists": not is_expired,
                "expired": is_expired,
                "expiration_time": expiration if expiration > 0 else None,
                "time_to_expiry": time_to_expiry,
                "state_keys": list(state.keys()) if not is_expired else None,
                "state_size": len(str(state)) if not is_expired else 0,
            }
