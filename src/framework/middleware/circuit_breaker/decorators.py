import asyncio
import functools
import inspect
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union, cast

from framework.exceptions.api import SourceUnavailableError

from .config import CircuitBreakerConfig
from .core import CircuitBreaker

# Type variables for better type hinting
T = TypeVar("T", bound=Callable)
R = TypeVar("R")


def with_circuit_breaker(
    circuit_name: str,
    failure_threshold: int = 5,
    reset_timeout: float = 60.0,
    success_threshold: int = 2,
    timeout: float = 10.0,
    excluded_exceptions: Optional[List[Type[Exception]]] = None,
    use_persistent_storage: bool = False,
    track_metrics: bool = True,
    max_state_history: int = 100,
    log_level_state_change: str = "INFO",
    log_level_failure: str = "ERROR",
    storage_provider: Optional[str] = None,
):
    """
    Decorator to apply circuit breaker pattern to a function.

    Args:
        circuit_name: Unique name for this circuit
        failure_threshold: Number of failures before opening circuit
        reset_timeout: Seconds before trying again (half-open)
        success_threshold: Successes needed to close circuit again
        timeout: Request timeout in seconds (0 for no timeout)
        excluded_exceptions: Exceptions that don't count as failures
        use_persistent_storage: Whether to use persistent storage
        track_metrics: Whether to track performance metrics
        max_state_history: Maximum number of state changes to track
        log_level_state_change: Log level for state changes
        log_level_failure: Log level for failures
        storage_provider: Storage provider type ("memory", "redis", etc.)

    Returns:
        Decorated function with circuit breaker protection

    Examples:
        ```python
        # Basic usage
        @with_circuit_breaker("api_service")
        def call_api_service(data):
            return requests.post("https://api.example.com", json=data)

        # With custom configuration
        @with_circuit_breaker(
            circuit_name="payment_gateway",
            failure_threshold=3,
            reset_timeout=120.0,
            timeout=5.0,
            excluded_exceptions=[ValueError, KeyError]
        )
        async def process_payment(payment_data):
            return await payment_service.process(payment_data)
        ```
    """
    excluded = excluded_exceptions or []

    def decorator(func: T) -> T:
        # Create a config object with the decorator parameters
        config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
            success_threshold=success_threshold,
            timeout=timeout,
            excluded_exceptions=excluded,
            use_persistent_storage=use_persistent_storage,
            track_metrics=track_metrics,
            max_state_history=max_state_history,
            log_level_state_change=log_level_state_change,
            log_level_failure=log_level_failure,
            storage_provider=storage_provider,
        )

        # Check if the function is a coroutine function (async)
        is_async = inspect.iscoroutinefunction(func)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            """Synchronous wrapper for the decorated function."""
            circuit = CircuitBreaker.get_instance(circuit_name, config=config)
            return circuit.execute(func, *args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            """Asynchronous wrapper for the decorated function."""
            # Get or create the circuit breaker
            circuit = CircuitBreaker.get_instance(circuit_name, config=config)

            # Check if request is allowed (this may raise exceptions)
            circuit.allow_request()

            # Extract timeout from kwargs or use default
            req_timeout = kwargs.pop("_timeout", None) or config.timeout

            try:
                # Execute with timeout if needed
                if req_timeout and req_timeout > 0:
                    try:
                        result = await asyncio.wait_for(
                            func(*args, **kwargs), timeout=req_timeout
                        )
                    except asyncio.TimeoutError:
                        if config.track_metrics:
                            circuit.metrics.timeout_requests += 1
                        circuit._on_failure("persistent")
                        raise TimeoutError(
                            f"Request to '{circuit_name}' timed out after {req_timeout}s"
                        )
                else:
                    result = await func(*args, **kwargs)

                # Record success
                circuit._on_success()
                return result

            except Exception as e:
                # Skip failure handling for excluded exceptions
                if type(e) not in config.excluded_exceptions:
                    failure_type = (
                        "persistent"
                        if isinstance(
                            e,
                            (
                                SourceUnavailableError,
                                TimeoutError,
                                asyncio.TimeoutError,
                            ),
                        )
                        else "transient"
                    )
                    circuit._on_failure(failure_type)
                # Re-raise the original exception
                raise

        # Create a callable class that can hold attributes
        class CircuitBreakerWrapper:
            def __init__(self, wrapped_func):
                self.wrapped_func = wrapped_func
                functools.update_wrapper(self, func)

            def __call__(self, *args, **kwargs):
                return self.wrapped_func(*args, **kwargs)

            def get_circuit(self):
                return CircuitBreaker.get_instance(circuit_name)

            def reset_circuit(self):
                return CircuitBreaker.get_instance(circuit_name).reset()

            def get_metrics(self):
                return CircuitBreaker.get_instance(circuit_name).get_metrics()

            def get_state(self):
                return CircuitBreaker.get_instance(circuit_name).state.value

            def is_open(self):
                return CircuitBreaker.get_instance(circuit_name).state.name == "OPEN"

            def is_closed(self):
                return CircuitBreaker.get_instance(circuit_name).state.name == "CLOSED"

            def is_half_open(self):
                return (
                    CircuitBreaker.get_instance(circuit_name).state.name == "HALF_OPEN"
                )

            def force_open(self):
                return _force_circuit_state(circuit_name, "OPEN")

            def force_closed(self):
                return _force_circuit_state(circuit_name, "CLOSED")

        # Choose the appropriate wrapper based on whether the function is async
        wrapper_func = async_wrapper if is_async else sync_wrapper

        # Create the wrapper instance and return with proper typing
        return cast(T, CircuitBreakerWrapper(wrapper_func))

    return decorator


def _force_circuit_state(circuit_name: str, state_name: str) -> None:
    """
    Force a circuit breaker into a specific state.
    Internal helper function for the decorator.

    Args:
        circuit_name: Name of the circuit breaker
        state_name: Desired state ("OPEN", "CLOSED", "HALF_OPEN")
    """
    from .enums import CircuitState

    # Get the circuit instance
    circuit = CircuitBreaker.get_instance(circuit_name)

    # Get the target state
    try:
        target_state = getattr(CircuitState, state_name)
    except AttributeError:
        raise ValueError(f"Invalid circuit state: {state_name}")

    # Record the old state for state change notification
    old_state = circuit.state

    # Update the state
    with circuit._lock:
        circuit.state = target_state

        # Reset counters as needed
        if target_state == CircuitState.CLOSED:
            circuit.failure_count = 0

        # Record state change
        if old_state != target_state:
            circuit._record_state_change(old_state, target_state)
            circuit._persist_state()
