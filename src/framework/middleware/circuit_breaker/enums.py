from enum import Enum, auto
from typing import Dict, List, Optional, Set


class CircuitState(Enum):
    """
    Enum representing the possible states of a circuit breaker.

    The circuit breaker pattern uses three primary states to control request flow:

    - CLOSED: Normal operation where requests pass through to the service
    - OPEN: Service is considered unavailable and requests fail fast
    - HALF_OPEN: Testing phase to check if service has recovered

    State transitions:
    CLOSED -> OPEN: When failure count exceeds threshold
    OPEN -> HALF_OPEN: After reset timeout period
    HALF_OPEN -> CLOSED: When success count exceeds threshold
    HALF_OPEN -> OPEN: On any failure during testing
    """

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Circuit is open, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service is back online

    @property
    def description(self) -> str:
        """Get a human-readable description of this state."""
        descriptions = {
            CircuitState.CLOSED: (
                "Normal operation - requests are being passed through to the service"
            ),
            CircuitState.OPEN: (
                "Service unavailable - requests are being rejected without attempting to call the service"
            ),
            CircuitState.HALF_OPEN: (
                "Testing recovery - allowing limited requests to test if the service is back online"
            ),
        }
        return descriptions[self]

    @property
    def allows_requests(self) -> bool:
        """Check if this state allows requests to pass through."""
        return self in {CircuitState.CLOSED, CircuitState.HALF_OPEN}

    @property
    def is_testing(self) -> bool:
        """Check if this state is in testing mode."""
        return self == CircuitState.HALF_OPEN

    @property
    def valid_next_states(self) -> Set["CircuitState"]:
        """Get the valid states this state can transition to."""
        transitions = {
            CircuitState.CLOSED: {CircuitState.OPEN},
            CircuitState.OPEN: {CircuitState.HALF_OPEN},
            CircuitState.HALF_OPEN: {CircuitState.CLOSED, CircuitState.OPEN},
        }
        return transitions[self]

    @classmethod
    def from_string(cls, state_str: str) -> "CircuitState":
        """
        Create a CircuitState from a string representation.

        Args:
            state_str: String representation of the state

        Returns:
            Corresponding CircuitState enum value

        Raises:
            ValueError: If state_str doesn't match any known state
        """
        try:
            return cls(state_str.lower())
        except ValueError:
            valid_values = [s.value for s in cls]
            raise ValueError(
                f"Invalid circuit state: '{state_str}'. "
                f"Must be one of: {', '.join(valid_values)}"
            )

    def can_transition_to(self, target_state: "CircuitState") -> bool:
        """
        Check if this state can directly transition to the target state.

        Args:
            target_state: The state to transition to

        Returns:
            True if transition is valid, False otherwise
        """
        return target_state in self.valid_next_states

    def __str__(self) -> str:
        """String representation of the state."""
        return self.value
