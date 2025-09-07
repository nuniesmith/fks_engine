"""
Custom exceptions for the rate limiter package.
"""

from typing import Optional


class RateLimitError(Exception):
    """Base exception for all rate limiting errors."""

    pass


class RateLimitExceededError(RateLimitError):
    """
    Raised when a rate limit is exceeded and the policy is STRICT.

    Attributes:
        retry_after: Seconds to wait before retrying
        limit: The rate limit that was exceeded
        window: The time window for the rate limit
    """

    def __init__(
        self,
        message: str,
        retry_after: float = 0,
        limit: Optional[int] = None,
        window: Optional[int] = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit = limit
        self.window = window


class RateLimitConfigError(RateLimitError):
    """Raised when there's an error in rate limiter configuration."""

    pass


class RateLimitRegistryError(RateLimitError):
    """Raised when there's an error with the rate limiter registry."""

    pass


class RateLimitAlgorithmError(RateLimitError):
    """Raised when there's an error with a rate limiting algorithm."""

    pass
