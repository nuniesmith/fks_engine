"""
Enhanced rate limiter registry for global management of rate limiters.
"""

import threading
import time
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from .core import RateLimiter
from .exceptions import RateLimitConfigError, RateLimitRegistryError
from .policies import RateLimitPolicy

# Global registry of rate limiters
_RATE_LIMITERS: Dict[str, RateLimiter] = {}
_REGISTRY_LOCK = threading.RLock()
_REGISTRY_STATS = {
    "created_at": time.time(),
    "total_limiters_created": 0,
    "total_limiters_removed": 0,
    "last_cleanup": 0,
}


def get_rate_limiter(name: str) -> RateLimiter:
    """
    Get a registered rate limiter by name.

    Args:
        name: Name of the rate limiter

    Returns:
        The rate limiter instance

    Raises:
        RateLimitRegistryError: If no rate limiter with the given name exists
    """
    with _REGISTRY_LOCK:
        if name not in _RATE_LIMITERS:
            available = list(_RATE_LIMITERS.keys())
            raise RateLimitRegistryError(
                f"No rate limiter registered with name '{name}'. "
                f"Available limiters: {available}"
            )
        return _RATE_LIMITERS[name]


def get_or_create_rate_limiter(
    name: str,
    max_requests: int = 100,
    time_window: int = 60,
    algorithm: str = "token_bucket",
    policy: Union[str, RateLimitPolicy] = RateLimitPolicy.WAIT,
    **kwargs,
) -> RateLimiter:
    """
    Get a registered rate limiter by name, or create one if it doesn't exist.

    Args:
        name: Name of the rate limiter
        max_requests: Maximum requests allowed in time window (used only if creating)
        time_window: Time window in seconds (used only if creating)
        algorithm: Rate limiting algorithm to use (used only if creating)
        policy: Rate limiting policy (used only if creating)
        **kwargs: Additional arguments for RateLimiter constructor

    Returns:
        The rate limiter instance (either existing or newly created)
    """
    with _REGISTRY_LOCK:
        if name in _RATE_LIMITERS:
            return _RATE_LIMITERS[name]

        return register_rate_limiter(
            name, max_requests, time_window, algorithm, policy, **kwargs
        )


def register_rate_limiter(
    name: str,
    max_requests: int,
    time_window: int = 60,
    algorithm: str = "token_bucket",
    policy: Union[str, RateLimitPolicy] = RateLimitPolicy.WAIT,
    force_replace: bool = False,
    **kwargs,
) -> RateLimiter:
    """
    Register a new rate limiter.

    Args:
        name: Name for this rate limiter
        max_requests: Maximum requests allowed in time window
        time_window: Time window in seconds
        algorithm: Rate limiting algorithm to use
        policy: Rate limiting policy
        force_replace: Whether to replace an existing limiter with the same name
        **kwargs: Additional arguments for RateLimiter constructor

    Returns:
        The newly created rate limiter

    Raises:
        RateLimitRegistryError: If the name is already in use and force_replace is False
        RateLimitConfigError: If the configuration is invalid
    """
    # Input validation
    if not name or not isinstance(name, str):
        raise RateLimitConfigError("Rate limiter name must be a non-empty string")

    if max_requests <= 0:
        raise RateLimitConfigError(f"max_requests must be positive, got {max_requests}")

    if time_window <= 0:
        raise RateLimitConfigError(f"time_window must be positive, got {time_window}")

    with _REGISTRY_LOCK:
        # Check if name already exists
        if name in _RATE_LIMITERS and not force_replace:
            raise RateLimitRegistryError(
                f"Rate limiter '{name}' already exists. Use force_replace=True to override"
            )

        try:
            # Create the rate limiter
            limiter = RateLimiter(
                max_requests=max_requests,
                time_window=time_window,
                algorithm=algorithm,
                policy=policy,
                name=name,
                **kwargs,
            )

            # Register it
            if name in _RATE_LIMITERS:
                logger.warning(f"Replacing existing rate limiter '{name}'")
                _REGISTRY_STATS["total_limiters_removed"] += 1

            _RATE_LIMITERS[name] = limiter
            _REGISTRY_STATS["total_limiters_created"] += 1

            logger.info(
                f"Registered rate limiter '{name}': {max_requests} req/{time_window}s "
                f"using {algorithm} algorithm with {policy} policy"
            )

            return limiter

        except Exception as e:
            raise RateLimitConfigError(f"Failed to create rate limiter '{name}': {e}")


def unregister_rate_limiter(name: str, force: bool = False) -> None:
    """
    Remove a rate limiter from the registry.

    Args:
        name: Name of the rate limiter to remove
        force: If True, won't raise error if limiter doesn't exist

    Raises:
        RateLimitRegistryError: If no rate limiter with the given name exists and force=False
    """
    with _REGISTRY_LOCK:
        if name not in _RATE_LIMITERS:
            if not force:
                available = list(_RATE_LIMITERS.keys())
                raise RateLimitRegistryError(
                    f"No rate limiter registered with name '{name}'. "
                    f"Available limiters: {available}"
                )
            else:
                logger.debug(f"Rate limiter '{name}' not found (force=True, ignoring)")
                return

        del _RATE_LIMITERS[name]
        _REGISTRY_STATS["total_limiters_removed"] += 1
        logger.info(f"Unregistered rate limiter '{name}'")


def list_rate_limiters() -> List[str]:
    """
    Get a list of all registered rate limiter names.

    Returns:
        List of rate limiter names sorted alphabetically
    """
    with _REGISTRY_LOCK:
        return sorted(_RATE_LIMITERS.keys())


def get_all_stats() -> Dict[str, Dict[str, Any]]:
    """
    Get statistics for all registered rate limiters.

    Returns:
        Dictionary mapping rate limiter names to their statistics
    """
    stats = {}
    with _REGISTRY_LOCK:
        for name, limiter in _RATE_LIMITERS.items():
            try:
                stats[name] = limiter.get_stats()
            except Exception as e:
                logger.warning(f"Failed to get stats for rate limiter '{name}': {e}")
                stats[name] = {"error": str(e)}

    return stats


def reset_all_limiters() -> int:
    """
    Reset all registered rate limiters to their initial state.

    Returns:
        Number of limiters that were reset
    """
    reset_count = 0
    with _REGISTRY_LOCK:
        for name, limiter in _RATE_LIMITERS.items():
            try:
                limiter.reset()
                reset_count += 1
                logger.debug(f"Reset rate limiter '{name}'")
            except Exception as e:
                logger.warning(f"Failed to reset rate limiter '{name}': {e}")

    if reset_count > 0:
        logger.info(f"Reset {reset_count} rate limiters")

    return reset_count


def cleanup_all_limiters(max_age: int = 3600) -> int:
    """
    Clean up expired client data from all registered rate limiters.

    Args:
        max_age: Maximum age in seconds for client data

    Returns:
        Total number of clients cleaned up across all limiters
    """
    total_cleaned = 0
    with _REGISTRY_LOCK:
        for name, limiter in _RATE_LIMITERS.items():
            try:
                cleaned = limiter.cleanup_expired_clients(max_age)
                total_cleaned += cleaned
                if cleaned > 0:
                    logger.debug(f"Cleaned {cleaned} expired clients from '{name}'")
            except Exception as e:
                logger.warning(f"Failed to cleanup rate limiter '{name}': {e}")

        _REGISTRY_STATS["last_cleanup"] = time.time()

    if total_cleaned > 0:
        logger.info(f"Registry cleanup removed {total_cleaned} expired client entries")

    return total_cleaned


def clear_registry(confirm: bool = False) -> None:
    """
    Clear the entire rate limiter registry.

    This removes all registered rate limiters. Use with extreme caution.

    Args:
        confirm: Must be True to actually clear the registry (safety measure)

    Raises:
        RateLimitRegistryError: If confirm is not True
    """
    if not confirm:
        raise RateLimitRegistryError(
            "Registry clear requires explicit confirmation. Set confirm=True"
        )

    with _REGISTRY_LOCK:
        limiter_count = len(_RATE_LIMITERS)
        _RATE_LIMITERS.clear()
        _REGISTRY_STATS["total_limiters_removed"] += limiter_count

        logger.warning(
            f"Rate limiter registry cleared - removed {limiter_count} limiters"
        )


def get_registry_stats() -> Dict[str, Any]:
    """
    Get statistics about the registry itself.

    Returns:
        Dictionary with registry statistics
    """
    with _REGISTRY_LOCK:
        current_time = time.time()
        uptime = current_time - _REGISTRY_STATS["created_at"]

        return {
            "limiter_count": len(_RATE_LIMITERS),
            "limiter_names": list(_RATE_LIMITERS.keys()),
            "total_created": _REGISTRY_STATS["total_limiters_created"],
            "total_removed": _REGISTRY_STATS["total_limiters_removed"],
            "uptime_seconds": uptime,
            "last_cleanup": _REGISTRY_STATS["last_cleanup"],
            "time_since_cleanup": current_time - _REGISTRY_STATS["last_cleanup"],
        }


def exists(name: str) -> bool:
    """
    Check if a rate limiter with the given name exists.

    Args:
        name: Name to check

    Returns:
        True if a rate limiter with that name exists
    """
    with _REGISTRY_LOCK:
        return name in _RATE_LIMITERS


def find_limiters_by_algorithm(algorithm: str) -> List[str]:
    """
    Find all rate limiters using a specific algorithm.

    Args:
        algorithm: Algorithm name to search for

    Returns:
        List of rate limiter names using the specified algorithm
    """
    matching_limiters = []
    with _REGISTRY_LOCK:
        for name, limiter in _RATE_LIMITERS.items():
            try:
                if limiter.algorithm.__class__.__name__.lower().startswith(
                    algorithm.lower()
                ):
                    matching_limiters.append(name)
            except Exception:
                continue  # Skip limiters we can't inspect

    return matching_limiters


def find_limiters_by_policy(policy: Union[str, RateLimitPolicy]) -> List[str]:
    """
    Find all rate limiters using a specific policy.

    Args:
        policy: Policy to search for

    Returns:
        List of rate limiter names using the specified policy
    """
    if isinstance(policy, str):
        try:
            policy = RateLimitPolicy(policy.lower())
        except ValueError:
            return []

    matching_limiters = []
    with _REGISTRY_LOCK:
        for name, limiter in _RATE_LIMITERS.items():
            try:
                if limiter.policy == policy:
                    matching_limiters.append(name)
            except Exception:
                continue  # Skip limiters we can't inspect

    return matching_limiters
