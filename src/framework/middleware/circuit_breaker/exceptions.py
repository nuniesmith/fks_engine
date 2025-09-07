"""
Custom exceptions for the circuit breaker middleware.

This module defines all the specific exceptions that can be raised
by the circuit breaker implementation, providing clear error types
for different failure scenarios.
"""

from typing import Optional


class CircuitBreakerError(Exception):
    """
    Base exception for all circuit breaker-related errors.

    This serves as the parent class for all circuit breaker exceptions,
    allowing consumers to catch all circuit breaker errors with a single
    exception type if needed.
    """

    def __init__(self, message: str, circuit_name: Optional[str] = None):
        """
        Initialize the circuit breaker error.

        Args:
            message: Error message describing what went wrong
            circuit_name: Name of the circuit breaker that caused the error
        """
        super().__init__(message)
        self.circuit_name = circuit_name
        self.message = message

    def __str__(self) -> str:
        """Return a string representation of the error."""
        if self.circuit_name:
            return f"Circuit '{self.circuit_name}': {self.message}"
        return self.message


class CircuitOpenError(CircuitBreakerError):
    """
    Raised when a circuit is open and requests are being rejected.

    This exception is thrown when the circuit breaker is in the OPEN state
    and a request is attempted. It includes information about when the
    circuit might be available again.
    """

    def __init__(
        self,
        message: str,
        circuit_name: Optional[str] = None,
        retry_after_seconds: Optional[float] = None,
    ):
        """
        Initialize the circuit open error.

        Args:
            message: Error message
            circuit_name: Name of the circuit that's open
            retry_after_seconds: How long until the circuit might be available
        """
        super().__init__(message, circuit_name)
        self.retry_after_seconds = retry_after_seconds


class StateTransitionError(CircuitBreakerError):
    """
    Raised when an invalid state transition is attempted.

    This exception occurs when trying to force a circuit breaker into
    a state that's not a valid transition from its current state.
    """

    def __init__(
        self,
        message: str,
        current_state: str,
        attempted_state: str,
        circuit_name: Optional[str] = None,
    ):
        """
        Initialize the state transition error.

        Args:
            message: Error message
            current_state: Current state of the circuit
            attempted_state: State that was attempted to transition to
            circuit_name: Name of the circuit
        """
        super().__init__(message, circuit_name)
        self.current_state = current_state
        self.attempted_state = attempted_state


class ConfigurationError(CircuitBreakerError):
    """
    Raised when circuit breaker configuration is invalid.

    This exception is thrown during configuration validation when
    invalid parameters are provided.
    """

    def __init__(self, message: str, parameter_name: Optional[str] = None):
        """
        Initialize the configuration error.

        Args:
            message: Error message describing the configuration issue
            parameter_name: Name of the invalid parameter
        """
        super().__init__(message)
        self.parameter_name = parameter_name


class StateProviderError(CircuitBreakerError):
    """
    Raised when state provider operations fail.

    This exception wraps errors that occur during state persistence
    or retrieval operations.
    """

    def __init__(
        self,
        message: str,
        operation: str,
        circuit_name: Optional[str] = None,
        underlying_error: Optional[Exception] = None,
    ):
        """
        Initialize the state provider error.

        Args:
            message: Error message
            operation: Operation that failed (e.g., 'persist', 'retrieve')
            circuit_name: Name of the circuit
            underlying_error: The original exception that caused this error
        """
        super().__init__(message, circuit_name)
        self.operation = operation
        self.underlying_error = underlying_error


class CircuitTimeoutError(CircuitBreakerError):
    """
    Raised when a circuit breaker operation times out.

    This exception is used when the circuit breaker's timeout
    mechanism triggers during function execution.
    """

    def __init__(
        self, message: str, timeout_seconds: float, circuit_name: Optional[str] = None
    ):
        """
        Initialize the circuit timeout error.

        Args:
            message: Error message
            timeout_seconds: The timeout value that was exceeded
            circuit_name: Name of the circuit
        """
        super().__init__(message, circuit_name)
        self.timeout_seconds = timeout_seconds


class CircuitExecutionError(CircuitBreakerError):
    """
    Raised when function execution fails within a circuit breaker.

    This exception wraps the original exception that occurred during
    function execution, providing additional circuit breaker context.
    """

    def __init__(
        self,
        message: str,
        circuit_name: Optional[str] = None,
        underlying_error: Optional[Exception] = None,
        failure_type: str = "unknown",
    ):
        """
        Initialize the circuit execution error.

        Args:
            message: Error message
            circuit_name: Name of the circuit
            underlying_error: The original exception that was raised
            failure_type: Type of failure (e.g., 'transient', 'persistent')
        """
        super().__init__(message, circuit_name)
        self.underlying_error = underlying_error
        self.failure_type = failure_type
