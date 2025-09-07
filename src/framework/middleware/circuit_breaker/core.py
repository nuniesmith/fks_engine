import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Dict, List, Optional, Type, Union

from loguru import logger

from .config import CircuitBreakerConfig

# Internal imports - updated to use new structure
from .enums import CircuitState
from .exceptions import (
    CircuitExecutionError,
    CircuitOpenError,
    CircuitTimeoutError,
    StateProviderError,
)
from .metrics import CircuitMetrics
from .state_providers import MemoryStateProvider, StateProvider
from .utils import log_execution, safe_execute

# External framework imports (fallback to generic exceptions if not available)
try:
    from framework.exceptions.api import ApiConnectionError, SourceUnavailableError
except ImportError:
    # Fallback exceptions if framework exceptions are not available
    class ApiConnectionError(Exception):
        """Transient API connection error."""

        pass

    class SourceUnavailableError(Exception):
        """Source unavailable error."""

        pass


class CircuitBreaker:
    """
    Implements the circuit breaker pattern to prevent repeated calls to failing services.
    Allows for both in-memory state tracking and external persistence.
    """

    _instances: Dict[str, "CircuitBreaker"] = {}
    _lock = threading.RLock()  # Class-level lock for thread safety

    @classmethod
    def get_instance(cls, name: str, **kwargs) -> "CircuitBreaker":
        """
        Get or create a circuit breaker instance by name.
        Thread-safe singleton implementation.

        Args:
            name: Unique identifier for this circuit breaker
            **kwargs: Configuration parameters to pass to the constructor

        Returns:
            A CircuitBreaker instance
        """
        with cls._lock:
            if name not in cls._instances:
                cls._instances[name] = CircuitBreaker(name, **kwargs)
            return cls._instances[name]

    @classmethod
    def reset_all_instances(cls) -> None:
        """
        Reset all circuit breaker instances to their initial state.
        Primarily useful for testing purposes.
        """
        with cls._lock:
            for circuit in cls._instances.values():
                circuit.reset()

    @classmethod
    def remove_instance(cls, name: str) -> None:
        """
        Remove a circuit breaker instance from the registry.
        Useful for testing or for dynamic configuration changes.

        Args:
            name: Name of the circuit breaker to remove
        """
        with cls._lock:
            if name in cls._instances:
                del cls._instances[name]

    @classmethod
    def list_instances(cls) -> List[str]:
        """
        Get a list of all circuit breaker instance names.

        Returns:
            List of circuit breaker names
        """
        with cls._lock:
            return list(cls._instances.keys())

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        state_provider: Optional[StateProvider] = None,
    ):
        """
        Initialize a new CircuitBreaker.

        Args:
            name: Unique identifier for this circuit breaker
            config: Configuration parameters
            state_provider: Provider for state persistence (optional)
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()

        # Set up state provider based on config
        self.state_provider = self._setup_state_provider(state_provider)

        # Set up logger
        self.logger = logger.bind(circuit=name)

        # Thread safety
        self._lock = threading.RLock()

        # State machine transitions
        self._state_handlers = {
            CircuitState.CLOSED: self._handle_closed_state,
            CircuitState.OPEN: self._handle_open_state,
            CircuitState.HALF_OPEN: self._handle_half_open_state,
        }

        # Initialize state
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        self.last_success_time = 0

        # Metrics
        self.metrics = CircuitMetrics()

        # State change notification hooks
        self.state_change_hooks: List[
            Callable[[str, CircuitState, CircuitState], None]
        ] = []

        # Try to restore state if available
        self._restore_state()

        self._log(
            "info",
            f"CircuitBreaker '{name}' initialized with threshold={self.config.failure_threshold} "
            f"and reset_timeout={self.config.reset_timeout}s",
        )

    def _setup_state_provider(
        self, state_provider: Optional[StateProvider]
    ) -> StateProvider:
        """
        Set up the appropriate state provider based on configuration.

        Args:
            state_provider: Explicit state provider or None

        Returns:
            Configured state provider
        """
        if state_provider:
            return state_provider

        if (
            self.config.use_persistent_storage
            and self.config.storage_provider == "redis"
        ):
            try:
                from .state_providers import RedisStateProvider

                redis_client = self._get_redis_client()
                return RedisStateProvider(redis_client)
            except ImportError:
                self._log(
                    "warning", "Redis not available, falling back to memory storage"
                )
            except Exception as e:
                self._log("error", f"Failed to setup Redis provider: {e}")

        return MemoryStateProvider()

    def _log(self, level: str, message: str) -> None:
        """
        Log a message at the specified level.

        Args:
            level: Log level (debug, info, warning, error, critical)
            message: Message to log
        """
        log_method = getattr(self.logger, level, self.logger.info)
        log_method(message)

    def _get_redis_client(self):
        """
        Get the Redis client for state persistence.

        This method should be implemented based on your Redis setup.
        For now, it raises NotImplementedError to indicate it needs implementation.
        """
        raise NotImplementedError(
            "Redis client retrieval not implemented. "
            "Please implement _get_redis_client() method or provide a state_provider."
        )

    def _restore_state(self) -> None:
        """Attempt to restore state from the persistence provider."""
        try:
            stored_state = self.state_provider.retrieve_state(
                f"circuit_breaker:{self.name}"
            )
            if stored_state:
                with self._lock:
                    old_state = self.state
                    self.state = CircuitState.from_string(
                        stored_state.get("state", "closed")
                    )
                    self.failure_count = stored_state.get("failures", 0)
                    self.success_count = stored_state.get("success_count", 0)
                    self.last_failure_time = stored_state.get("last_failure_time", 0)
                    self.last_success_time = stored_state.get("last_success_time", 0)

                    # Import metrics if available
                    if "metrics" in stored_state and self.config.track_metrics:
                        self._restore_metrics(stored_state["metrics"])

                    # Record state change in metrics
                    if old_state != self.state:
                        self._record_state_change(old_state, self.state)

                    self._log(
                        "info",
                        f"Restored circuit breaker state for '{self.name}': {self.state.value}",
                    )
        except Exception as e:
            self._log("error", f"Error restoring circuit breaker state: {e}")

    def _restore_metrics(self, metrics_data: Dict[str, Any]) -> None:
        """
        Restore metrics from stored state.

        Args:
            metrics_data: Dictionary containing metrics data
        """
        try:
            self.metrics.total_requests = metrics_data.get("total_requests", 0)
            self.metrics.successful_requests = metrics_data.get(
                "successful_requests", 0
            )
            self.metrics.failed_requests = metrics_data.get("failed_requests", 0)
            self.metrics.rejected_requests = metrics_data.get("rejected_requests", 0)
            self.metrics.timeout_requests = metrics_data.get("timeout_requests", 0)
        except Exception as e:
            self._log("warning", f"Error restoring metrics: {e}")

    def _persist_state(self) -> None:
        """Persist the current state using the state provider."""
        try:
            with self._lock:
                state = {
                    "state": self.state.value,
                    "failures": self.failure_count,
                    "success_count": self.success_count,
                    "last_failure_time": self.last_failure_time,
                    "last_success_time": self.last_success_time,
                }

                # Include metrics in persisted state if enabled
                if self.config.track_metrics:
                    state["metrics"] = {
                        "total_requests": self.metrics.total_requests,
                        "successful_requests": self.metrics.successful_requests,
                        "failed_requests": self.metrics.failed_requests,
                        "rejected_requests": self.metrics.rejected_requests,
                        "timeout_requests": self.metrics.timeout_requests,
                    }

                success = self.state_provider.persist_state(
                    f"circuit_breaker:{self.name}", state
                )
                if not success:
                    self._log(
                        "warning", f"Failed to persist state for circuit '{self.name}'"
                    )

        except Exception as e:
            self._log("error", f"Error persisting circuit breaker state: {e}")

    def _record_state_change(
        self, old_state: CircuitState, new_state: CircuitState
    ) -> None:
        """
        Record a state change in metrics and notify hooks.

        Args:
            old_state: Previous circuit state
            new_state: New circuit state
        """
        if self.config.track_metrics:
            self.metrics.record_state_change(old_state.value, new_state.value)

        # Use appropriate log level based on config
        self._log(
            self.config.log_level_state_change.lower(),
            f"Circuit '{self.name}' state change: {old_state.value} -> {new_state.value}",
        )

        # Notify hooks safely
        for hook in self.state_change_hooks:
            safe_execute(hook, self.name, old_state, new_state)

    def register_state_change_hook(
        self, hook: Callable[[str, CircuitState, CircuitState], None]
    ) -> None:
        """
        Register a function to be called when the circuit state changes.

        Args:
            hook: Function taking (circuit_name, old_state, new_state) as arguments
        """
        self.state_change_hooks.append(hook)

    def allow_request(self) -> bool:
        """
        Check if a request is allowed based on the current circuit state.

        Returns:
            True if the request is allowed, False otherwise

        Raises:
            CircuitOpenError: If the circuit is open
        """
        with self._lock:
            self._check_state_transition()

            if self.config.track_metrics:
                self.metrics.total_requests += 1

            # Use state pattern to handle request based on current state
            return self._state_handlers[self.state]()

    def _handle_closed_state(self) -> bool:
        """Handle request when circuit is in CLOSED state."""
        self._log("debug", f"Request allowed for '{self.name}' (circuit CLOSED).")
        return True

    def _handle_open_state(self) -> bool:
        """Handle request when circuit is in OPEN state."""
        elapsed_time = time.time() - self.last_failure_time
        remaining = self.config.reset_timeout - elapsed_time

        if elapsed_time < self.config.reset_timeout:
            if self.config.track_metrics:
                self.metrics.rejected_requests += 1

            self._log(
                "warning",
                f"Circuit breaker open for '{self.name}'. Request blocked. "
                f"Retry in {remaining:.2f}s.",
            )
            raise CircuitOpenError(
                f"Circuit '{self.name}' is open. Retry after {remaining:.2f}s.",
                circuit_name=self.name,
                retry_after_seconds=remaining,
            )

        # If we've exceeded the timeout, transition will happen in _check_state_transition
        return True

    def _handle_half_open_state(self) -> bool:
        """Handle request when circuit is in HALF_OPEN state."""
        self._log(
            "debug", f"Test request allowed for '{self.name}' (circuit HALF_OPEN)."
        )
        return True

    @log_execution
    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute the provided function with circuit breaker protection.

        Args:
            func: The function to execute
            *args: Positional arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function

        Returns:
            The result of the function call

        Raises:
            CircuitOpenError: If the circuit is open
            CircuitTimeoutError: If the function execution times out
            CircuitExecutionError: If the function execution fails
            Any exceptions raised by the function
        """
        # Check if we can make the request
        self.allow_request()

        # Extract timeout from kwargs or use the default
        timeout = kwargs.pop("_timeout", None) or self.config.timeout

        start_time = time.time()

        try:
            # Use a separate thread with timeout if needed
            if timeout and timeout > 0:
                result = self._execute_with_timeout(func, timeout, *args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Record successful execution time if tracking metrics
            if self.config.track_metrics:
                execution_time_ms = (time.time() - start_time) * 1000
                self.metrics.record_request(
                    success=True, response_time_ms=execution_time_ms
                )

            self._on_success()
            return result

        except Exception as e:
            # Record execution time for failed requests too
            if self.config.track_metrics:
                execution_time_ms = (time.time() - start_time) * 1000
                is_timeout = isinstance(e, (TimeoutError, CircuitTimeoutError))
                self.metrics.record_request(
                    success=False,
                    response_time_ms=execution_time_ms,
                    timeout=is_timeout,
                )

            # Skip failure handling for excluded exceptions
            if type(e) not in self.config.excluded_exceptions:
                failure_type = self._classify_failure(e)
                self._on_failure(failure_type, e)

            # Re-raise the original exception
            raise

    def _execute_with_timeout(
        self, func: Callable, timeout: float, *args, **kwargs
    ) -> Any:
        """
        Execute function with timeout using ThreadPoolExecutor.

        Args:
            func: Function to execute
            timeout: Timeout in seconds
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitTimeoutError: If execution times out
        """
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except FuturesTimeoutError as timeout_error:
                self._log(
                    "error", f"Request to '{self.name}' timed out after {timeout}s"
                )
                raise CircuitTimeoutError(
                    f"Request to '{self.name}' timed out after {timeout}s",
                    timeout_seconds=timeout,
                    circuit_name=self.name,
                ) from timeout_error

    def _classify_failure(self, exception: Exception) -> str:
        """
        Classify the type of failure based on the exception.

        Args:
            exception: The exception that occurred

        Returns:
            "persistent" or "transient"
        """
        persistent_exceptions = (
            SourceUnavailableError,
            TimeoutError,
            CircuitTimeoutError,
            ConnectionError,
            OSError,
        )

        if isinstance(exception, persistent_exceptions):
            return "persistent"
        return "transient"

    def _check_state_transition(self) -> None:
        """Check and potentially change the circuit state based on timeouts."""
        with self._lock:
            old_state = self.state

            # Only check for timeout transition if we're in OPEN state
            if (
                self.state == CircuitState.OPEN
                and time.time() - self.last_failure_time >= self.config.reset_timeout
            ):
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                self._log(
                    "info",
                    f"Circuit breaker for '{self.name}' transitioning to HALF_OPEN state",
                )

                if old_state != self.state:
                    self._record_state_change(old_state, self.state)
                    self._persist_state()

    def _on_success(self) -> None:
        """
        Handle successful execution.
        Updates state and persistence as needed.
        """
        with self._lock:
            self.last_success_time = time.time()
            old_state = self.state

            if self.config.track_metrics:
                self.metrics.successful_requests += 1

            # In HALF_OPEN state, count successes to determine if we should close the circuit
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self._log(
                        "info",
                        f"Circuit breaker for '{self.name}' closed after successful tests",
                    )

                    if old_state != self.state:
                        self._record_state_change(old_state, self.state)

            self._persist_state()

    def _on_failure(
        self,
        failure_type: str = "transient",
        original_exception: Optional[Exception] = None,
    ) -> None:
        """
        Handle failed execution.

        Args:
            failure_type: Type of failure - "transient" or "persistent"
            original_exception: The original exception that caused the failure
        """
        with self._lock:
            self.last_failure_time = time.time()
            old_state = self.state

            if self.config.track_metrics:
                self.metrics.failed_requests += 1

            state_changed = False

            # Update state based on current state
            if self.state == CircuitState.CLOSED:
                self.failure_count += 1
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN
                    self._log(
                        self.config.log_level_failure.lower(),
                        f"Circuit breaker for '{self.name}' opened after {self.failure_count} failures",
                    )
                    state_changed = old_state != self.state

            # In HALF_OPEN state, any failure reopens the circuit
            elif self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self._log(
                    "warning",
                    f"Circuit breaker for '{self.name}' reopened after test failure",
                )
                state_changed = old_state != self.state

            # Update metrics and persist state
            if state_changed:
                self._record_state_change(old_state, self.state)

            self._persist_state()

    def record_failure(self, failure_type: str = "transient") -> None:
        """
        Explicitly record a failure without executing a function.

        Args:
            failure_type: Type of failure - "transient" or "persistent"

        Raises:
            ValueError: If failure_type is invalid
        """
        if failure_type not in {"transient", "persistent"}:
            raise ValueError("Failure type must be either 'transient' or 'persistent'.")

        self._on_failure(failure_type)

    def record_success(self) -> None:
        """
        Explicitly record a success without executing a function.

        This can be useful for external monitoring or when success/failure
        is determined by external factors.
        """
        self._on_success()

    def reset(self) -> None:
        """
        Manually reset the circuit breaker to closed state.
        Useful for testing or administrative interventions.
        """
        with self._lock:
            old_state = self.state
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0

            if old_state != self.state:
                self._record_state_change(old_state, self.state)

            self._log(
                "info", f"Circuit breaker '{self.name}' manually reset to CLOSED state"
            )
            self._persist_state()

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get circuit breaker metrics and status information.

        Returns:
            Dictionary with state and metrics information
        """
        with self._lock:
            result = {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "last_failure": self.last_failure_time,
                "last_success": self.last_success_time,
                "config": {
                    "failure_threshold": self.config.failure_threshold,
                    "reset_timeout": self.config.reset_timeout,
                    "success_threshold": self.config.success_threshold,
                    "timeout": self.config.timeout,
                },
            }

            if self.config.track_metrics:
                result["metrics"] = self.metrics.to_dict()

            return result

    def get_state(self) -> CircuitState:
        """
        Get the current state of the circuit breaker.

        Returns:
            Current circuit state
        """
        return self.state

    def is_open(self) -> bool:
        """Check if the circuit is open."""
        return self.state == CircuitState.OPEN

    def is_closed(self) -> bool:
        """Check if the circuit is closed."""
        return self.state == CircuitState.CLOSED

    def is_half_open(self) -> bool:
        """Check if the circuit is half-open."""
        return self.state == CircuitState.HALF_OPEN

    def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the circuit breaker.

        Returns:
            Dictionary with health information
        """
        with self._lock:
            is_healthy = self.state != CircuitState.OPEN

            # Check state provider health
            provider_healthy = safe_execute(
                self.state_provider.health_check, default=False
            )

            return {
                "name": self.name,
                "healthy": is_healthy and provider_healthy,
                "state": self.state.value,
                "state_provider_healthy": provider_healthy,
                "failure_count": self.failure_count,
                "success_rate": (
                    self.metrics.get_success_rate()
                    if self.config.track_metrics
                    else None
                ),
                "last_check": time.time(),
            }
