"""
Testing utilities for circuit breaker middleware.

This module provides helper classes, mock objects, and testing utilities
to make it easier to test circuit breaker functionality and applications
that use circuit breakers.
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Union
from unittest.mock import MagicMock

from .config import CircuitBreakerConfig
from .core import CircuitBreaker
from .enums import CircuitState
from .exceptions import CircuitExecutionError, CircuitOpenError
from .state_providers.base import StateProvider


class MockStateProvider(StateProvider):
    """
    Mock state provider for testing purposes.

    This provider stores state in memory and allows for easy inspection
    and manipulation during tests. It can also simulate failures for
    testing error handling.
    """

    def __init__(self, fail_operations: bool = False):
        """
        Initialize the mock state provider.

        Args:
            fail_operations: If True, all operations will fail
        """
        self._storage: Dict[str, Dict[str, Any]] = {}
        self._fail_operations = fail_operations
        self._operation_calls = []
        self._lock = threading.RLock()

    def persist_state(self, key: str, state: Dict[str, Any]) -> bool:
        """Mock persist operation."""
        with self._lock:
            self._operation_calls.append(("persist", key, state.copy()))
            if self._fail_operations:
                return False
            self._storage[key] = state.copy()
            return True

    def retrieve_state(self, key: str) -> Optional[Dict[str, Any]]:
        """Mock retrieve operation."""
        with self._lock:
            self._operation_calls.append(("retrieve", key, None))
            if self._fail_operations:
                return None
            return self._storage.get(key, None)

    def delete_state(self, key: str) -> bool:
        """Mock delete operation."""
        with self._lock:
            self._operation_calls.append(("delete", key, None))
            if self._fail_operations:
                return False
            if key in self._storage:
                del self._storage[key]
                return True
            return False

    def exists(self, key: str) -> bool:
        """Mock exists check."""
        with self._lock:
            self._operation_calls.append(("exists", key, None))
            if self._fail_operations:
                return False
            return key in self._storage

    def list_keys(self, prefix: str = "") -> List[str]:
        """Mock key listing."""
        with self._lock:
            self._operation_calls.append(("list_keys", prefix, None))
            if self._fail_operations:
                return []
            return [k for k in self._storage.keys() if k.startswith(prefix)]

    def clear_all(self, prefix: str = "") -> bool:
        """Mock clear operation."""
        with self._lock:
            self._operation_calls.append(("clear_all", prefix, None))
            if self._fail_operations:
                return False
            if not prefix:
                self._storage.clear()
            else:
                keys_to_delete = [
                    k for k in self._storage.keys() if k.startswith(prefix)
                ]
                for key in keys_to_delete:
                    del self._storage[key]
            return True

    def get_operation_calls(self) -> List[tuple]:
        """Get list of all operations called on this provider."""
        with self._lock:
            return self._operation_calls.copy()

    def reset_calls(self) -> None:
        """Reset the operation call history."""
        with self._lock:
            self._operation_calls.clear()

    def set_fail_operations(self, fail: bool) -> None:
        """Set whether operations should fail."""
        with self._lock:
            self._fail_operations = fail

    def get_storage_copy(self) -> Dict[str, Dict[str, Any]]:
        """Get a copy of the internal storage for inspection."""
        with self._lock:
            return {k: v.copy() for k, v in self._storage.items()}


class CircuitBreakerTestHelper:
    """
    Helper class for testing circuit breaker behavior.

    Provides utilities to easily create circuit breakers with specific
    configurations and simulate various failure scenarios.
    """

    def __init__(self, name: str = "test_circuit", **config_kwargs):
        """
        Initialize the test helper.

        Args:
            name: Name for the test circuit breaker
            **config_kwargs: Configuration parameters for the circuit breaker
        """
        self.name = name
        self.state_provider = MockStateProvider()

        # Default test configuration with fast timeouts
        default_config = {
            "failure_threshold": 3,
            "reset_timeout": 1.0,  # Short timeout for faster tests
            "success_threshold": 2,
            "timeout": 1.0,
            "track_metrics": True,
        }
        default_config.update(config_kwargs)

        self.config = CircuitBreakerConfig(**default_config)
        self.circuit = CircuitBreaker(
            name, config=self.config, state_provider=self.state_provider
        )

    def force_state(self, state: CircuitState) -> None:
        """Force the circuit breaker into a specific state."""
        from .utils import force_state_transition

        force_state_transition(self.circuit, state)

    def force_open(self) -> None:
        """Force the circuit breaker to OPEN state."""
        self.force_state(CircuitState.OPEN)

    def force_closed(self) -> None:
        """Force the circuit breaker to CLOSED state."""
        self.force_state(CircuitState.CLOSED)

    def force_half_open(self) -> None:
        """Force the circuit breaker to HALF_OPEN state."""
        self.force_state(CircuitState.HALF_OPEN)

    def simulate_failures(self, count: int) -> None:
        """
        Simulate the specified number of failures.

        Args:
            count: Number of failures to simulate
        """
        for _ in range(count):
            try:
                self.circuit.execute(lambda: self._failing_function())
            except Exception:
                pass  # Expected to fail

    def simulate_successes(self, count: int) -> None:
        """
        Simulate the specified number of successes.

        Args:
            count: Number of successes to simulate
        """
        for _ in range(count):
            self.circuit.execute(lambda: "success")

    def wait_for_reset_timeout(self) -> None:
        """Wait for the circuit breaker's reset timeout to elapse."""
        time.sleep(self.config.reset_timeout + 0.1)

    def get_state(self) -> CircuitState:
        """Get the current state of the circuit breaker."""
        return self.circuit.state

    def get_metrics(self) -> Dict[str, Any]:
        """Get the current metrics of the circuit breaker."""
        return self.circuit.get_metrics()

    def get_failure_count(self) -> int:
        """Get the current failure count."""
        return self.circuit.failure_count

    def get_success_count(self) -> int:
        """Get the current success count."""
        return self.circuit.success_count

    def is_open(self) -> bool:
        """Check if the circuit is open."""
        return self.circuit.state == CircuitState.OPEN

    def is_closed(self) -> bool:
        """Check if the circuit is closed."""
        return self.circuit.state == CircuitState.CLOSED

    def is_half_open(self) -> bool:
        """Check if the circuit is half-open."""
        return self.circuit.state == CircuitState.HALF_OPEN

    @staticmethod
    def _failing_function():
        """A function that always fails."""
        raise Exception("Simulated failure")

    def cleanup(self) -> None:
        """Clean up the test circuit breaker."""
        CircuitBreaker.remove_instance(self.name)


class MockFunction:
    """
    Mock function that can be configured to succeed or fail.

    Useful for testing circuit breaker behavior with controllable
    success/failure patterns.
    """

    def __init__(
        self,
        success_pattern: List[bool] = None,
        default_return_value: Any = "success",
        exception_to_raise: Exception = None,
    ):
        """
        Initialize the mock function.

        Args:
            success_pattern: List of booleans indicating success/failure pattern
            default_return_value: Value to return on success
            exception_to_raise: Exception to raise on failure
        """
        self.success_pattern = success_pattern or []
        self.default_return_value = default_return_value
        self.exception_to_raise = exception_to_raise or Exception("Mock failure")
        self.call_count = 0
        self.call_history = []

    def __call__(self, *args, **kwargs) -> Any:
        """Execute the mock function."""
        self.call_history.append((args, kwargs, time.time()))

        # Determine if this call should succeed or fail
        if self.call_count < len(self.success_pattern):
            should_succeed = self.success_pattern[self.call_count]
        else:
            # Default to success if pattern is exhausted
            should_succeed = True

        self.call_count += 1

        if should_succeed:
            return self.default_return_value
        else:
            raise self.exception_to_raise

    def reset(self) -> None:
        """Reset the call count and history."""
        self.call_count = 0
        self.call_history.clear()

    def set_pattern(self, pattern: List[bool]) -> None:
        """Set a new success/failure pattern."""
        self.success_pattern = pattern
        self.call_count = 0


class CircuitBreakerScenario:
    """
    Predefined scenarios for testing common circuit breaker behaviors.
    """

    @staticmethod
    def create_failing_service_scenario(
        name: str = "failing_service",
    ) -> CircuitBreakerTestHelper:
        """
        Create a scenario where the service is consistently failing.

        Returns:
            Configured test helper with a circuit that will open quickly
        """
        return CircuitBreakerTestHelper(
            name=name, failure_threshold=2, reset_timeout=0.5, timeout=0.1
        )

    @staticmethod
    def create_slow_service_scenario(
        name: str = "slow_service",
    ) -> CircuitBreakerTestHelper:
        """
        Create a scenario for testing timeout behavior.

        Returns:
            Configured test helper with very short timeout
        """
        return CircuitBreakerTestHelper(
            name=name,
            failure_threshold=3,
            timeout=0.1,  # Very short timeout
            reset_timeout=1.0,
        )

    @staticmethod
    def create_recovery_scenario(
        name: str = "recovery_service",
    ) -> CircuitBreakerTestHelper:
        """
        Create a scenario for testing recovery behavior.

        Returns:
            Configured test helper optimized for testing recovery
        """
        return CircuitBreakerTestHelper(
            name=name,
            failure_threshold=2,
            success_threshold=1,  # Quick recovery
            reset_timeout=0.5,
        )


def assert_circuit_state(
    circuit_or_helper: Union[CircuitBreaker, CircuitBreakerTestHelper],
    expected_state: CircuitState,
) -> None:
    """
    Assert that a circuit breaker is in the expected state.

    Args:
        circuit_or_helper: CircuitBreaker instance or test helper
        expected_state: Expected circuit state

    Raises:
        AssertionError: If the circuit is not in the expected state
    """
    if isinstance(circuit_or_helper, CircuitBreakerTestHelper):
        actual_state = circuit_or_helper.get_state()
    else:
        actual_state = circuit_or_helper.state

    assert (
        actual_state == expected_state
    ), f"Expected circuit state {expected_state.value}, got {actual_state.value}"


def assert_circuit_open(
    circuit_or_helper: Union[CircuitBreaker, CircuitBreakerTestHelper],
) -> None:
    """Assert that a circuit breaker is open."""
    assert_circuit_state(circuit_or_helper, CircuitState.OPEN)


def assert_circuit_closed(
    circuit_or_helper: Union[CircuitBreaker, CircuitBreakerTestHelper],
) -> None:
    """Assert that a circuit breaker is closed."""
    assert_circuit_state(circuit_or_helper, CircuitState.CLOSED)


def assert_circuit_half_open(
    circuit_or_helper: Union[CircuitBreaker, CircuitBreakerTestHelper],
) -> None:
    """Assert that a circuit breaker is half-open."""
    assert_circuit_state(circuit_or_helper, CircuitState.HALF_OPEN)


def create_test_circuit(name: str = "test_circuit", **config_kwargs) -> CircuitBreaker:
    """
    Create a circuit breaker configured for testing.

    Args:
        name: Name for the circuit breaker
        **config_kwargs: Additional configuration parameters

    Returns:
        CircuitBreaker instance configured for testing
    """
    helper = CircuitBreakerTestHelper(name, **config_kwargs)
    return helper.circuit


# Example test scenarios
class TestScenarios:
    """Collection of example test scenarios."""

    @staticmethod
    def test_basic_failure_and_recovery():
        """Example test: basic failure and recovery cycle."""
        helper = CircuitBreakerTestHelper("test")

        # Start closed
        assert_circuit_closed(helper)

        # Cause failures to open the circuit
        helper.simulate_failures(3)
        assert_circuit_open(helper)

        # Wait for reset timeout
        helper.wait_for_reset_timeout()

        # Next call should transition to half-open
        try:
            helper.circuit.execute(lambda: "success")
        except:
            pass
        assert_circuit_half_open(helper)

        # Successful calls should close the circuit
        helper.simulate_successes(2)
        assert_circuit_closed(helper)

        helper.cleanup()

    @staticmethod
    def test_timeout_behavior():
        """Example test: timeout behavior."""
        helper = CircuitBreakerTestHelper("timeout_test", timeout=0.1)

        def slow_function():
            time.sleep(0.2)  # Slower than timeout
            return "success"

        # This should timeout and count as a failure
        try:
            helper.circuit.execute(slow_function)
            assert False, "Should have timed out"
        except Exception:
            pass

        # Verify timeout was recorded
        metrics = helper.get_metrics()
        assert metrics["metrics"]["timeout_requests"] > 0

        helper.cleanup()
