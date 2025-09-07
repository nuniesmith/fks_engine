"""
Utility functions and decorators for the circuit breaker middleware.

This module contains helper functions, decorators, and utilities that are
used throughout the circuit breaker implementation.
"""

import asyncio
import functools
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, TypeVar, Union

from loguru import logger

if TYPE_CHECKING:
    from .enums import CircuitState
    from .exceptions import StateTransitionError

# Type variables for better type hinting
F = TypeVar("F", bound=Callable[..., Any])


def log_execution(func: F) -> F:
    """
    Decorator to log function execution time and result.

    This decorator wraps functions to provide detailed logging about
    execution time, success/failure status, and any exceptions that occur.

    Args:
        func: The function to wrap with logging

    Returns:
        The wrapped function with logging capabilities
    """

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs) -> Any:
        start_time = time.time()
        func_name = getattr(func, "__qualname__", func.__name__)

        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.debug(f"{func_name} executed successfully in {execution_time:.3f}s")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"{func_name} failed after {execution_time:.3f}s: {str(e)}")
            raise

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs) -> Any:
        start_time = time.time()
        func_name = getattr(func, "__qualname__", func.__name__)

        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.debug(f"{func_name} executed successfully in {execution_time:.3f}s")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"{func_name} failed after {execution_time:.3f}s: {str(e)}")
            raise

    # Return the appropriate wrapper based on whether the function is async
    if asyncio.iscoroutinefunction(func):
        return async_wrapper  # type: ignore
    else:
        return sync_wrapper  # type: ignore


def validate_state_transition(
    from_state: "CircuitState", to_state: "CircuitState"
) -> bool:
    """
    Validate if a state transition is allowed.

    This function checks whether a circuit breaker can transition from
    one state to another based on the defined state machine rules.

    Args:
        from_state: Current state of the circuit
        to_state: Desired target state

    Returns:
        True if the transition is valid, False otherwise
    """
    return to_state in from_state.valid_next_states


def force_state_transition(circuit_breaker, target_state: "CircuitState") -> None:
    """
    Force a circuit breaker into a specific state.

    This utility function forces a circuit breaker to transition to a
    specific state, bypassing normal transition rules. Should be used
    carefully, primarily for testing or administrative purposes.

    Args:
        circuit_breaker: The CircuitBreaker instance to modify
        target_state: The state to transition to

    Raises:
        StateTransitionError: If the state transition fails
    """
    from .exceptions import StateTransitionError

    try:
        with circuit_breaker._lock:
            old_state = circuit_breaker.state
            circuit_breaker.state = target_state

            # Reset counters as needed
            if target_state.value == "closed":
                circuit_breaker.failure_count = 0
                circuit_breaker.success_count = 0
            elif target_state.value == "half_open":
                circuit_breaker.success_count = 0

            # Record state change
            if old_state != target_state:
                circuit_breaker._record_state_change(old_state, target_state)
                circuit_breaker._persist_state()

    except Exception as e:
        raise StateTransitionError(
            f"Failed to force state transition to {target_state.value}",
            circuit_breaker.state.value,
            target_state.value,
            circuit_breaker.name,
        ) from e


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breaker instances.

    This utility class provides a centralized way to manage multiple
    circuit breakers, including bulk operations and monitoring.
    """

    def __init__(self):
        self._circuits = {}
        self._lock = threading.RLock()

    def register(self, circuit_breaker) -> None:
        """Register a circuit breaker instance."""
        with self._lock:
            self._circuits[circuit_breaker.name] = circuit_breaker

    def unregister(self, name: str) -> bool:
        """Unregister a circuit breaker by name."""
        with self._lock:
            if name in self._circuits:
                del self._circuits[name]
                return True
            return False

    def get(self, name: str):
        """Get a circuit breaker by name."""
        with self._lock:
            return self._circuits.get(name)

    def list_circuits(self) -> list:
        """Get a list of all registered circuit names."""
        with self._lock:
            return list(self._circuits.keys())

    def reset_all(self) -> None:
        """Reset all registered circuit breakers."""
        with self._lock:
            for circuit in self._circuits.values():
                circuit.reset()

    def get_all_metrics(self) -> dict:
        """Get metrics for all registered circuits."""
        with self._lock:
            return {
                name: circuit.get_metrics() for name, circuit in self._circuits.items()
            }

    def health_check_all(self) -> dict:
        """Perform health check on all circuits."""
        with self._lock:
            results = {}
            for name, circuit in self._circuits.items():
                try:
                    metrics = circuit.get_metrics()
                    results[name] = {
                        "healthy": circuit.state.value != "open",
                        "state": circuit.state.value,
                        "success_rate": metrics.get("success_rate", "0%"),
                    }
                except Exception as e:
                    results[name] = {"healthy": False, "error": str(e)}
            return results


def timeout_handler(timeout_seconds: float):
    """
    Decorator to add timeout handling to functions.

    This decorator can be used independently of the circuit breaker
    to add timeout functionality to any function.

    Args:
        timeout_seconds: Maximum execution time in seconds

    Returns:
        Decorator function
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            import signal

            def timeout_error_handler(signum, frame):
                raise TimeoutError(
                    f"Function {func.__name__} timed out after {timeout_seconds}s"
                )

            # Set up timeout
            old_handler = signal.signal(signal.SIGALRM, timeout_error_handler)
            signal.alarm(int(timeout_seconds))

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                signal.alarm(0)  # Cancel the alarm
                signal.signal(signal.SIGALRM, old_handler)  # Restore old handler

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                result = await asyncio.wait_for(
                    func(*args, **kwargs), timeout=timeout_seconds
                )
                return result
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Function {func.__name__} timed out after {timeout_seconds}s"
                )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore

    return decorator


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
) -> float:
    """
    Calculate exponential backoff delay.

    This utility function calculates the delay for retry attempts using
    exponential backoff with jitter to avoid thundering herd problems.

    Args:
        attempt: Current attempt number (starting from 0)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        backoff_factor: Multiplier for exponential backoff

    Returns:
        Delay in seconds for this attempt
    """
    import random

    delay = min(base_delay * (backoff_factor**attempt), max_delay)
    # Add jitter (±25% of the calculated delay)
    jitter = delay * 0.25 * (2 * random.random() - 1)
    return max(0.1, delay + jitter)


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to a human-readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "2m 30s", "1h 5m", "3d 2h")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"

    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    components = []
    if days > 0:
        components.append(f"{days}d")
    if hours > 0:
        components.append(f"{hours}h")
    if minutes > 0:
        components.append(f"{minutes}m")
    if seconds > 0 or not components:
        components.append(f"{seconds}s")

    return " ".join(components)


def safe_execute(func: Callable, *args, default=None, **kwargs) -> Any:
    """
    Safely execute a function, returning a default value on failure.

    This utility function wraps function execution with exception handling,
    useful for non-critical operations that shouldn't break the main flow.

    Args:
        func: Function to execute
        *args: Positional arguments for the function
        default: Value to return if execution fails
        **kwargs: Keyword arguments for the function

    Returns:
        Function result or default value on failure
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.debug(f"Safe execution failed for {func.__name__}: {str(e)}")
        return default


# Global registry instance
circuit_registry = CircuitBreakerRegistry()
