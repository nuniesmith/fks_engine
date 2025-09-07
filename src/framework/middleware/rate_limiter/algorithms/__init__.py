"""
Rate limiting algorithms package.

This package provides various rate limiting algorithms that can be used
with the core RateLimiter class or independently.

Available algorithms:
- TokenBucketAlgorithm: Allows bursts while maintaining average rate
- SlidingWindowAlgorithm: Precise rate limiting with smooth distribution
- FixedWindowAlgorithm: Memory efficient with fixed time windows

Example usage:
    from framework.middleware.rate_limiter.algorithms import TokenBucketAlgorithm

    algorithm = TokenBucketAlgorithm(max_requests=100, time_window=60)
    result = algorithm.acquire("client_123")
    if result.allowed:
        # Process request
        pass
"""

from .base import RateLimitAlgorithm, RateLimitResult
from .fixed_window import FixedWindowAlgorithm
from .sliding_window import SlidingWindowAlgorithm
from .token_bucket import TokenBucketAlgorithm

# Define what algorithms are available
AVAILABLE_ALGORITHMS = {
    "token_bucket": TokenBucketAlgorithm,
    "sliding_window": SlidingWindowAlgorithm,
    "fixed_window": FixedWindowAlgorithm,
}


def create_algorithm(
    algorithm_type: str, max_requests: int, time_window: int, **kwargs
) -> RateLimitAlgorithm:
    """
    Factory function to create rate limiting algorithms.

    Args:
        algorithm_type: Type of algorithm ('token_bucket', 'sliding_window', 'fixed_window')
        max_requests: Maximum number of requests allowed
        time_window: Time window in seconds
        **kwargs: Additional algorithm-specific parameters

    Returns:
        Configured rate limiting algorithm

    Raises:
        ValueError: If algorithm_type is not recognized
    """
    if algorithm_type not in AVAILABLE_ALGORITHMS:
        available = ", ".join(AVAILABLE_ALGORITHMS.keys())
        raise ValueError(
            f"Unknown algorithm type '{algorithm_type}'. Available: {available}"
        )

    algorithm_class = AVAILABLE_ALGORITHMS[algorithm_type]
    return algorithm_class(max_requests, time_window, **kwargs)


# Export all public components
__all__ = [
    # Base classes
    "RateLimitAlgorithm",
    "RateLimitResult",
    # Algorithm implementations
    "TokenBucketAlgorithm",
    "SlidingWindowAlgorithm",
    "FixedWindowAlgorithm",
    # Utilities
    "AVAILABLE_ALGORITHMS",
    "create_algorithm",
]
