from enum import Enum, auto
from typing import Optional


class RateLimitPolicy(Enum):
    """
    Policies for handling rate limit exceeded situations.

    These policies determine the behavior when a rate limit is reached:
    - STRICT: Immediately reject the request with an exception
    - WAIT: Wait for a token to become available (blocking)
    - THROTTLE: Introduce a delay proportional to congestion (partial blocking)
    """

    STRICT = "strict"
    WAIT = "wait"
    THROTTLE = "throttle"

    @classmethod
    def from_string(cls, policy_name: str) -> Optional["RateLimitPolicy"]:
        """
        Convert a string to a RateLimitPolicy enum value.

        Args:
            policy_name: String representation of the policy

        Returns:
            The matching RateLimitPolicy or None if not found
        """
        try:
            return cls(policy_name.lower())
        except ValueError:
            return None

    @property
    def description(self) -> str:
        """Get a human-readable description of the policy."""
        if self == RateLimitPolicy.STRICT:
            return "Immediately reject requests when rate limit is exceeded"
        elif self == RateLimitPolicy.WAIT:
            return (
                "Wait for token availability, blocking until a token becomes available"
            )
        elif self == RateLimitPolicy.THROTTLE:
            return (
                "Slow down processing by introducing delays proportional to congestion"
            )
        else:
            return "Unknown policy"

    def should_wait(self) -> bool:
        """Determine if this policy involves waiting."""
        return self in (RateLimitPolicy.WAIT, RateLimitPolicy.THROTTLE)

    def should_reject(self) -> bool:
        """Determine if this policy involves rejecting requests."""
        return self == RateLimitPolicy.STRICT
