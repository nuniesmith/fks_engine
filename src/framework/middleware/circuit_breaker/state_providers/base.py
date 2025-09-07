import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

# Type variable for generic state types
T = TypeVar("T", bound=Dict[str, Any])


class StateProvider(ABC, Generic[T]):
    """
    Abstract base class for state persistence providers.

    This class defines the interface that all state providers must implement
    to provide persistence capabilities for the circuit breaker pattern.

    State providers are responsible for:
    1. Persisting circuit breaker state
    2. Retrieving circuit breaker state
    3. Managing the lifecycle of stored state

    Implementations should handle serialization, error conditions, and
    connection management appropriately.
    """

    @abstractmethod
    def persist_state(self, key: str, state: T) -> bool:
        """
        Persist the circuit breaker state.

        Args:
            key: The key under which to store the state
            state: The state data to store

        Returns:
            True if the state was successfully persisted, False otherwise

        Raises:
            ConnectionError: If unable to connect to the storage backend
            ValueError: If the state is invalid
        """
        pass

    @abstractmethod
    def retrieve_state(self, key: str) -> Optional[T]:
        """
        Retrieve the circuit breaker state.

        Args:
            key: The key to retrieve

        Returns:
            The stored state or None if not found

        Raises:
            ConnectionError: If unable to connect to the storage backend
        """
        pass

    def exists(self, key: str) -> bool:
        """
        Check if a state exists for the given key.

        Args:
            key: The key to check

        Returns:
            True if the state exists, False otherwise

        Raises:
            ConnectionError: If unable to connect to the storage backend
        """
        return self.retrieve_state(key) is not None

    def delete_state(self, key: str) -> bool:
        """
        Delete the state for the given key.

        Args:
            key: The key to delete

        Returns:
            True if the state was successfully deleted, False otherwise

        Raises:
            ConnectionError: If unable to connect to the storage backend
        """
        raise NotImplementedError("Delete not implemented for this provider")

    def update_state(self, key: str, updates: Dict[str, Any]) -> bool:
        """
        Update parts of the state for the given key.

        Default implementation retrieves the state, updates it, and persists it again.
        Subclasses should override this with more efficient implementations if possible.

        Args:
            key: The key to update
            updates: Dictionary of updates to apply to the state

        Returns:
            True if the state was successfully updated, False otherwise

        Raises:
            ConnectionError: If unable to connect to the storage backend
            KeyError: If the key does not exist
        """
        state = self.retrieve_state(key)
        if state is None:
            raise KeyError(f"No state found for key '{key}'")

        state.update(updates)
        return self.persist_state(key, state)

    def list_keys(self, prefix: str = "") -> List[str]:
        """
        List all keys with the given prefix.

        Args:
            prefix: Prefix to filter keys by

        Returns:
            List of keys with the given prefix

        Raises:
            ConnectionError: If unable to connect to the storage backend
        """
        raise NotImplementedError("List keys not implemented for this provider")

    def clear_all(self, prefix: str = "") -> bool:
        """
        Clear all states with the given prefix.

        Args:
            prefix: Prefix to filter keys by

        Returns:
            True if all states were successfully cleared, False otherwise

        Raises:
            ConnectionError: If unable to connect to the storage backend
        """
        raise NotImplementedError("Clear all not implemented for this provider")

    def initialize(self) -> None:
        """
        Initialize the state provider.

        This method should be called before using the provider.
        It can be used to establish connections, create tables/collections, etc.

        Raises:
            ConnectionError: If unable to initialize the provider
        """
        pass

    def shutdown(self) -> None:
        """
        Shutdown the state provider.

        This method should be called when the provider is no longer needed.
        It can be used to close connections, release resources, etc.
        """
        pass

    def health_check(self) -> bool:
        """
        Check if the state provider is healthy.

        Returns:
            True if the provider is healthy, False otherwise
        """
        try:
            # Try a no-op operation to check if the provider is healthy
            test_key = "__health_check__"
            test_state = {"healthy": True}
            # Cast the dictionary to T to satisfy type checking
            self.persist_state(test_key, test_state)  # type: ignore
            self.delete_state(test_key)
            return True
        except Exception:
            return False

    @staticmethod
    def serialize(state: Dict[str, Any]) -> str:
        """
        Serialize the state to a string.

        This is a helper method that can be used by implementations
        that need to convert the state to a string.

        Args:
            state: The state to serialize

        Returns:
            The serialized state
        """
        return json.dumps(state)

    @staticmethod
    def deserialize(data: Union[str, bytes]) -> Dict[str, Any]:
        """
        Deserialize the state from a string or bytes.

        This is a helper method that can be used by implementations
        that need to convert a string or bytes to a state dictionary.

        Args:
            data: The serialized state

        Returns:
            The deserialized state

        Raises:
            ValueError: If the data cannot be deserialized
        """
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return json.loads(data)
