"""
Circuit Breaker Middleware

A comprehensive implementation of the circuit breaker pattern for Python applications.
Provides protection against cascading failures and enables graceful degradation of services.

Example usage:
    ```python
    from framework.middleware.circuit_breaker import with_circuit_breaker, CircuitBreaker

    # Using the decorator
    @with_circuit_breaker("api_service", failure_threshold=3, reset_timeout=60)
    def call_external_api():
        return requests.get("https://api.example.com/data")

    # Using the class directly
    circuit = CircuitBreaker.get_instance("payment_service")
    result = circuit.execute(process_payment, payment_data)
    ```
"""

from .config import CircuitBreakerConfig

# Core components
from .core import CircuitBreaker
from .decorators import with_circuit_breaker
from .enums import CircuitState

# Exceptions
from .exceptions import (
    CircuitBreakerError,
    CircuitExecutionError,
    CircuitOpenError,
    CircuitTimeoutError,
    ConfigurationError,
    StateProviderError,
    StateTransitionError,
)
from .metrics import CircuitMetrics

# State providers (with optional imports)
from .state_providers import MemoryStateProvider, StateProvider

# Utilities
from .utils import (
    CircuitBreakerRegistry,
    calculate_backoff_delay,
    circuit_registry,
    force_state_transition,
    format_duration,
    log_execution,
    safe_execute,
    timeout_handler,
    validate_state_transition,
)

try:
    from .state_providers import RedisStateProvider

    _REDIS_AVAILABLE = True
except ImportError:
    RedisStateProvider = None
    _REDIS_AVAILABLE = False

# Version information
__version__ = "1.0.0"
__author__ = "Your Organization"

# Public API
__all__ = [
    # Core classes
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "CircuitMetrics",
    # Decorators
    "with_circuit_breaker",
    # Exceptions
    "CircuitBreakerError",
    "CircuitOpenError",
    "StateTransitionError",
    "ConfigurationError",
    "StateProviderError",
    "CircuitTimeoutError",
    "CircuitExecutionError",
    # State providers
    "StateProvider",
    "MemoryStateProvider",
    # Utilities
    "log_execution",
    "validate_state_transition",
    "force_state_transition",
    "CircuitBreakerRegistry",
    "timeout_handler",
    "calculate_backoff_delay",
    "format_duration",
    "safe_execute",
    "circuit_registry",
]

# Add Redis provider to exports if available
if _REDIS_AVAILABLE:
    __all__.append("RedisStateProvider")


def create_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    reset_timeout: float = 60.0,
    success_threshold: int = 2,
    timeout: float = 10.0,
    use_persistent_storage: bool = False,
    storage_provider: str = "memory",
    **kwargs,
) -> CircuitBreaker:
    """
    Factory function to create a circuit breaker with common settings.

    This is a convenience function that simplifies circuit breaker creation
    with sensible defaults for most use cases.

    Args:
        name: Unique name for the circuit breaker
        failure_threshold: Number of failures before opening circuit
        reset_timeout: Seconds before trying again (half-open)
        success_threshold: Successes needed to close circuit again
        timeout: Request timeout in seconds
        use_persistent_storage: Whether to use persistent storage
        storage_provider: Storage provider type ("memory", "redis")
        **kwargs: Additional configuration parameters

    Returns:
        Configured CircuitBreaker instance

    Example:
        ```python
        circuit = create_circuit_breaker(
            "database_service",
            failure_threshold=3,
            reset_timeout=30.0,
            timeout=5.0
        )
        ```
    """
    config = CircuitBreakerConfig(
        failure_threshold=failure_threshold,
        reset_timeout=reset_timeout,
        success_threshold=success_threshold,
        timeout=timeout,
        use_persistent_storage=use_persistent_storage,
        storage_provider=storage_provider,
        **kwargs,
    )

    return CircuitBreaker.get_instance(name, config=config)


def get_circuit_status(name: str) -> dict:
    """
    Get the current status of a circuit breaker by name.

    Args:
        name: Name of the circuit breaker

    Returns:
        Dictionary with circuit status information

    Raises:
        KeyError: If circuit breaker with given name doesn't exist
    """
    circuit = CircuitBreaker._instances.get(name)
    if not circuit:
        raise KeyError(f"Circuit breaker '{name}' not found")

    return circuit.get_metrics()


def reset_circuit(name: str) -> bool:
    """
    Reset a circuit breaker to closed state by name.

    Args:
        name: Name of the circuit breaker to reset

    Returns:
        True if circuit was reset, False if circuit not found
    """
    circuit = CircuitBreaker._instances.get(name)
    if circuit:
        circuit.reset()
        return True
    return False


def list_circuits() -> list:
    """
    Get a list of all active circuit breaker names.

    Returns:
        List of circuit breaker names
    """
    return list(CircuitBreaker._instances.keys())


def get_all_circuit_status() -> dict:
    """
    Get status information for all active circuit breakers.

    Returns:
        Dictionary mapping circuit names to their status information
    """
    return {
        name: circuit.get_metrics()
        for name, circuit in CircuitBreaker._instances.items()
    }


# Add convenience functions to __all__
__all__.extend(
    [
        "create_circuit_breaker",
        "get_circuit_status",
        "reset_circuit",
        "list_circuits",
        "get_all_circuit_status",
    ]
)


# Module-level configuration
class CircuitBreakerConfig:
    """Module-level configuration for circuit breaker defaults."""

    # Default values that can be overridden
    default_failure_threshold = 5
    default_reset_timeout = 60.0
    default_success_threshold = 2
    default_timeout = 10.0
    default_use_persistent_storage = False
    default_storage_provider = "memory"

    @classmethod
    def set_defaults(cls, **kwargs):
        """
        Set module-level defaults for circuit breaker configuration.

        Args:
            **kwargs: Configuration parameters to set as defaults
        """
        for key, value in kwargs.items():
            attr_name = f"default_{key}"
            if hasattr(cls, attr_name):
                setattr(cls, attr_name, value)


# Compatibility aliases for common use cases
CircuitOpen = CircuitOpenError
CircuitClosed = CircuitState.CLOSED
CircuitHalfOpen = CircuitState.HALF_OPEN
