"""
Enhanced decorators for function-level rate limiting.
"""

import asyncio
import inspect
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, Union

from loguru import logger

from .core import RateLimiter
from .exceptions import RateLimitExceededError
from .policies import RateLimitPolicy
from .registry import get_or_create_rate_limiter
from .utils import create_client_key_func


def rate_limited(
    limit: int,
    window: int = 60,
    algorithm: str = "token_bucket",
    policy: Union[str, RateLimitPolicy] = RateLimitPolicy.WAIT,
    limiter_name: Optional[str] = None,
    client_key: Optional[Union[str, Callable]] = None,
    max_wait_time: float = 5.0,
    burst_capacity: int = 0,
    per_client: bool = False,
    error_handler: Optional[Callable] = None,
    fallback_value: Any = None,
    **limiter_kwargs,
):
    """
    Advanced decorator for rate limiting function calls.

    Args:
        limit: Maximum number of calls per window
        window: Time window in seconds
        algorithm: Rate limiting algorithm ('token_bucket', 'sliding_window', 'fixed_window')
        policy: How to handle exceeded limits ('strict', 'wait', 'throttle')
        limiter_name: Name for this rate limiter (defaults to function name)
        client_key: Client identification strategy or custom function
        max_wait_time: Maximum time to wait for tokens (for WAIT policy)
        burst_capacity: Additional burst capacity (for token_bucket algorithm)
        per_client: Enable per-client rate limiting
        error_handler: Custom function to handle rate limit errors
        fallback_value: Value to return when rate limited (instead of None)
        **limiter_kwargs: Additional arguments for the rate limiter

    Returns:
        Decorated function with rate limiting
    """

    def decorator(func):
        # Determine limiter name
        nonlocal limiter_name
        if limiter_name is None:
            limiter_name = f"{func.__module__}.{func.__qualname__}"

        # Create or get the rate limiter
        limiter = get_or_create_rate_limiter(
            name=limiter_name,
            max_requests=limit,
            time_window=window,
            algorithm=algorithm,
            policy=policy,
            max_wait_time=max_wait_time,
            burst_capacity=burst_capacity,
            **limiter_kwargs,
        )

        # Enable per-client tracking if requested
        if per_client:
            limiter.enable_client_tracking()

        # Set up client key extraction
        client_key_func = None
        if client_key is not None:
            if callable(client_key):
                client_key_func = client_key
            elif isinstance(client_key, str):
                client_key_func = create_client_key_func(client_key)
            else:
                logger.warning(f"Invalid client_key type for {func.__name__}, ignoring")

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            """Synchronous wrapper with rate limiting."""
            return _execute_with_rate_limit(
                func,
                limiter,
                client_key_func,
                error_handler,
                fallback_value,
                is_async=False,
                args=args,
                kwargs=kwargs,
            )

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            """Asynchronous wrapper with rate limiting."""
            return await _execute_with_rate_limit(
                func,
                limiter,
                client_key_func,
                error_handler,
                fallback_value,
                is_async=True,
                args=args,
                kwargs=kwargs,
            )

        # Choose the appropriate wrapper
        if inspect.iscoroutinefunction(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper

        # Add utility methods to the wrapper
        _add_wrapper_methods(wrapper, limiter, func)

        return wrapper

    return decorator


def _execute_with_rate_limit(
    func,
    limiter,
    client_key_func,
    error_handler,
    fallback_value,
    is_async,
    args,
    kwargs,
):
    """Execute function with rate limiting logic."""
    # Extract client ID if needed
    client_id = None
    if client_key_func:
        try:
            if is_async and inspect.iscoroutinefunction(client_key_func):
                # We can't await here in sync context, so we'll handle this differently
                if is_async:
                    client_id = asyncio.create_task(client_key_func(*args, **kwargs))
                else:
                    logger.warning(
                        "Async client_key_func in sync context, using fallback"
                    )
                    client_id = "sync_fallback"
            else:
                client_id = client_key_func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Failed to extract client ID: {e}")
            client_id = "extraction_failed"

    async def async_execute():
        # Resolve client_id if it's a task
        resolved_client_id = client_id
        if asyncio.iscoroutine(client_id) or isinstance(client_id, asyncio.Task):
            try:
                resolved_client_id = await client_id
            except Exception as e:
                logger.warning(f"Failed to resolve async client ID: {e}")
                resolved_client_id = "async_fallback"

        try:
            # Try to acquire rate limit permission
            acquired = await limiter.acquire_async(client_id=resolved_client_id)

            if acquired:
                # Execute the function
                return await func(*args, **kwargs)
            else:
                # Rate limited - handle based on configuration
                return _handle_rate_limit_exceeded(
                    func, error_handler, fallback_value, limiter, resolved_client_id
                )

        except RateLimitExceededError as e:
            # Strict policy raised an exception
            if error_handler:
                try:
                    return await _call_error_handler(
                        error_handler, e, func, args, kwargs, is_async=True
                    )
                except Exception as handler_error:
                    logger.error(f"Error handler failed: {handler_error}")
                    raise e
            else:
                raise

    def sync_execute():
        # For sync execution, client_id should already be resolved
        resolved_client_id = client_id
        if asyncio.iscoroutine(client_id) or isinstance(client_id, asyncio.Task):
            logger.warning("Got async client_id in sync context, using fallback")
            resolved_client_id = "sync_async_fallback"

        try:
            # Try to acquire rate limit permission
            acquired = limiter.acquire(client_id=resolved_client_id)

            if acquired:
                # Execute the function
                return func(*args, **kwargs)
            else:
                # Rate limited - handle based on configuration
                return _handle_rate_limit_exceeded(
                    func, error_handler, fallback_value, limiter, resolved_client_id
                )

        except RateLimitExceededError as e:
            # Strict policy raised an exception
            if error_handler:
                try:
                    return _call_error_handler(
                        error_handler, e, func, args, kwargs, is_async=False
                    )
                except Exception as handler_error:
                    logger.error(f"Error handler failed: {handler_error}")
                    raise e
            else:
                raise

    if is_async:
        return async_execute()
    else:
        return sync_execute()


def _handle_rate_limit_exceeded(
    func, error_handler, fallback_value, limiter, client_id
):
    """Handle rate limit exceeded situation."""
    if error_handler:
        # Use custom error handler
        error = RateLimitExceededError(f"Rate limit exceeded for {func.__name__}")
        try:
            return error_handler(error, func, client_id)
        except Exception as handler_error:
            logger.error(f"Error handler failed: {handler_error}")

    # Log the rate limiting event
    logger.warning(
        f"Rate limit exceeded for {func.__name__}",
        function=func.__name__,
        client_id=client_id,
        limiter=limiter.name,
    )

    # Return fallback value
    return fallback_value


async def _call_error_handler(error_handler, error, func, args, kwargs, is_async):
    """Call error handler, handling both sync and async cases."""
    if is_async and inspect.iscoroutinefunction(error_handler):
        return await error_handler(error, func, args, kwargs)
    else:
        return error_handler(error, func, args, kwargs)


def _add_wrapper_methods(wrapper, limiter, original_func):
    """Add utility methods to the decorated function."""

    def get_rate_limiter():
        """Get the underlying rate limiter instance."""
        return limiter

    def get_stats(client_id=None):
        """Get rate limiting statistics."""
        return limiter.get_stats(client_id)

    def reset_limits(client_id=None):
        """Reset rate limiting state."""
        limiter.reset(client_id)

    def is_rate_limited(client_id=None):
        """Check if a client/function would be rate limited without consuming a token."""
        try:
            stats = limiter.get_stats(client_id)
            client_stats = stats.get("client_stats", {})
            return not client_stats.get("allowed", True)
        except Exception:
            return False

    def get_remaining(client_id=None):
        """Get remaining requests for a client."""
        try:
            stats = limiter.get_stats(client_id)
            client_stats = stats.get("client_stats", {})
            return client_stats.get("remaining", 0)
        except Exception:
            return 0

    def get_reset_time(client_id=None):
        """Get when rate limit resets for a client."""
        try:
            stats = limiter.get_stats(client_id)
            client_stats = stats.get("client_stats", {})
            return client_stats.get("reset_time", time.time())
        except Exception:
            return time.time()

    # Attach methods to wrapper
    wrapper.get_rate_limiter = get_rate_limiter
    wrapper.get_stats = get_stats
    wrapper.reset_limits = reset_limits
    wrapper.is_rate_limited = is_rate_limited
    wrapper.get_remaining = get_remaining
    wrapper.get_reset_time = get_reset_time
    wrapper._original_function = original_func
    wrapper._limiter_name = limiter.name


def conditional_rate_limit(
    condition: Callable[..., bool], limit: int, window: int = 60, **kwargs
):
    """
    Decorator that applies rate limiting only when a condition is met.

    Args:
        condition: Function that takes the same args/kwargs and returns bool
        limit: Maximum number of calls per window (when condition is True)
        window: Time window in seconds
        **kwargs: Additional arguments for rate_limited decorator

    Returns:
        Decorated function with conditional rate limiting
    """

    def decorator(func):
        # Create the rate limiter
        rate_limiter_decorator = rate_limited(limit, window, **kwargs)
        rate_limited_func = rate_limiter_decorator(func)

        @wraps(func)
        def sync_wrapper(*args, **kwargs_inner):
            # Check condition
            try:
                should_rate_limit = condition(*args, **kwargs_inner)
            except Exception as e:
                logger.warning(f"Condition check failed for {func.__name__}: {e}")
                should_rate_limit = True  # Default to rate limiting on error

            if should_rate_limit:
                return rate_limited_func(*args, **kwargs_inner)
            else:
                return func(*args, **kwargs_inner)

        @wraps(func)
        async def async_wrapper(*args, **kwargs_inner):
            # Check condition
            try:
                if inspect.iscoroutinefunction(condition):
                    should_rate_limit = await condition(*args, **kwargs_inner)
                else:
                    should_rate_limit = condition(*args, **kwargs_inner)
            except Exception as e:
                logger.warning(f"Condition check failed for {func.__name__}: {e}")
                should_rate_limit = True  # Default to rate limiting on error

            if should_rate_limit:
                return await rate_limited_func(*args, **kwargs_inner)
            else:
                return await func(*args, **kwargs_inner)

        # Choose appropriate wrapper
        if inspect.iscoroutinefunction(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper

        # Copy over rate limiter methods
        for attr in [
            "get_rate_limiter",
            "get_stats",
            "reset_limits",
            "is_rate_limited",
            "get_remaining",
            "get_reset_time",
        ]:
            if hasattr(rate_limited_func, attr):
                setattr(wrapper, attr, getattr(rate_limited_func, attr))

        wrapper._condition = condition
        wrapper._rate_limited_func = rate_limited_func

        return wrapper

    return decorator


def method_rate_limit(
    limit: int, window: int = 60, per_instance: bool = True, **kwargs
):
    """
    Decorator specifically designed for class methods.

    Args:
        limit: Maximum number of calls per window
        window: Time window in seconds
        per_instance: If True, rate limit per instance; if False, rate limit globally
        **kwargs: Additional arguments for rate_limited decorator

    Returns:
        Decorated method with rate limiting
    """

    def decorator(method):
        if per_instance:
            # Use instance ID as part of the client key
            def instance_client_key(*args, **kwargs_inner):
                if args:  # First arg should be self/cls
                    instance = args[0]
                    instance_id = f"{instance.__class__.__name__}_{id(instance)}"
                    return instance_id
                return "no_instance"

            kwargs["client_key"] = instance_client_key
            kwargs["per_client"] = True

        # Generate a unique limiter name for this method
        limiter_name = f"{method.__module__}.{method.__qualname__}"
        if per_instance:
            limiter_name += "_per_instance"
        kwargs["limiter_name"] = limiter_name

        return rate_limited(limit, window, **kwargs)(method)

    return decorator


def shared_rate_limit(group_name: str, limit: int, window: int = 60, **kwargs):
    """
    Decorator that shares rate limiting across multiple functions.

    All functions decorated with the same group_name will share the same rate limit.

    Args:
        group_name: Name of the rate limiting group
        limit: Maximum number of calls per window for the entire group
        window: Time window in seconds
        **kwargs: Additional arguments for rate_limited decorator

    Returns:
        Decorated function with shared rate limiting
    """

    def decorator(func):
        # Use the group name as the limiter name
        kwargs["limiter_name"] = f"shared_group_{group_name}"
        return rate_limited(limit, window, **kwargs)(func)

    return decorator


# Convenience decorators for common scenarios
def strict_rate_limit(limit: int, window: int = 60, **kwargs):
    """Rate limit with STRICT policy (raises exception when exceeded)."""
    return rate_limited(limit, window, policy=RateLimitPolicy.STRICT, **kwargs)


def wait_rate_limit(limit: int, window: int = 60, max_wait: float = 5.0, **kwargs):
    """Rate limit with WAIT policy (blocks until token available)."""
    return rate_limited(
        limit, window, policy=RateLimitPolicy.WAIT, max_wait_time=max_wait, **kwargs
    )


def throttle_rate_limit(limit: int, window: int = 60, **kwargs):
    """Rate limit with THROTTLE policy (introduces delays)."""
    return rate_limited(limit, window, policy=RateLimitPolicy.THROTTLE, **kwargs)


def per_user_rate_limit(limit: int, window: int = 60, **kwargs):
    """Rate limit per user (extracts user_id from request)."""
    return rate_limited(limit, window, client_key="user_id", per_client=True, **kwargs)


def per_ip_rate_limit(limit: int, window: int = 60, **kwargs):
    """Rate limit per IP address."""
    return rate_limited(limit, window, client_key="ip", per_client=True, **kwargs)


def api_rate_limit(limit: int, window: int = 60, **kwargs):
    """Rate limit per API key."""
    return rate_limited(limit, window, client_key="api_key", per_client=True, **kwargs)
