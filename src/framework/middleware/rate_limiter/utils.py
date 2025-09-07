"""
Utility functions for rate limiting.
"""

import hashlib
from typing import Any, Callable, List, Optional

from fastapi import Request


class ClientIdentifier:
    """
    Utilities for identifying clients for rate limiting purposes.

    Provides various strategies for extracting client identifiers from requests,
    which can be used alone or combined for more sophisticated identification.
    """

    @staticmethod
    def get_client_ip(request: Request) -> str:
        """
        Extract client IP address from request.

        Checks common proxy headers before falling back to direct client IP.

        Args:
            request: FastAPI/Starlette request object

        Returns:
            Client IP address as string
        """
        # Check for forwarded headers (common in production with load balancers/proxies)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain (original client)
            return forwarded_for.split(",")[0].strip()

        # Check for real IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        # Check CloudFlare connecting IP
        cf_connecting_ip = request.headers.get("CF-Connecting-IP")
        if cf_connecting_ip:
            return cf_connecting_ip.strip()

        # Fallback to direct client IP
        if request.client and request.client.host:
            return request.client.host

        return "unknown"

    @staticmethod
    def get_api_key(request: Request, header_name: str = "X-API-Key") -> Optional[str]:
        """
        Extract API key from request headers.

        Args:
            request: FastAPI/Starlette request object
            header_name: Header name to check for API key

        Returns:
            API key string or None if not found
        """
        return request.headers.get(header_name)

    @staticmethod
    def get_user_id(request: Request) -> Optional[str]:
        """
        Extract user ID from authenticated request.

        This function checks common locations where authentication middleware
        might store user information.

        Args:
            request: FastAPI/Starlette request object

        Returns:
            User ID string or None if not found
        """
        # Check request state (common in FastAPI with auth middleware)
        user_info = getattr(request.state, "user", None)
        if user_info:
            # Try different common attribute names
            for attr in ["user_id", "id", "sub", "username"]:
                if hasattr(user_info, attr):
                    return str(getattr(user_info, attr))

            # If user_info is a dict
            if isinstance(user_info, dict):
                for key in ["user_id", "id", "sub", "username"]:
                    if key in user_info:
                        return str(user_info[key])

        # Check JWT token payload
        token_payload = getattr(request.state, "token_payload", None)
        if token_payload and isinstance(token_payload, dict):
            for key in ["sub", "user_id", "id", "username"]:
                if key in token_payload:
                    return str(token_payload[key])

        # Check for user ID in headers (some custom auth schemes)
        user_header = request.headers.get("X-User-ID")
        if user_header:
            return user_header

        return None

    @staticmethod
    def get_endpoint_path(request: Request) -> str:
        """
        Get the endpoint path from request.

        Args:
            request: FastAPI/Starlette request object

        Returns:
            Request path as string
        """
        return request.url.path

    @staticmethod
    def get_user_agent(request: Request) -> str:
        """
        Get user agent from request.

        Args:
            request: FastAPI/Starlette request object

        Returns:
            User agent string
        """
        return request.headers.get("User-Agent", "unknown")

    @staticmethod
    def create_composite_id(request: Request, components: List[str]) -> str:
        """
        Create a composite client ID from multiple components.

        This allows for sophisticated client identification strategies by
        combining multiple request attributes.

        Args:
            request: FastAPI/Starlette request object
            components: List of component names to include

        Returns:
            Hashed composite identifier
        """
        id_parts = []

        # Map component names to extraction functions
        extractors = {
            "ip": ClientIdentifier.get_client_ip,
            "user_id": ClientIdentifier.get_user_id,
            "api_key": ClientIdentifier.get_api_key,
            "endpoint": ClientIdentifier.get_endpoint_path,
            "user_agent": ClientIdentifier.get_user_agent,
        }

        for component in components:
            if component in extractors:
                value = extractors[component](request)
                id_parts.append(str(value) if value is not None else "unknown")
            else:
                # Try to get as custom header
                header_value = request.headers.get(component, "unknown")
                id_parts.append(header_value)

        # Create composite string
        composite_str = ":".join(id_parts)

        # Hash for consistent length and privacy
        return hashlib.sha256(composite_str.encode()).hexdigest()[:16]

    @staticmethod
    def create_custom_identifier(
        extractor_func: Callable[[Request], str],
    ) -> Callable[[Request], str]:
        """
        Create a custom client identifier function.

        Args:
            extractor_func: Function that takes a Request and returns a string ID

        Returns:
            Wrapped extractor function with error handling
        """

        def safe_extractor(request: Request) -> str:
            try:
                result = extractor_func(request)
                return str(result) if result is not None else "unknown"
            except Exception:
                return "unknown"

        return safe_extractor


def create_client_key_func(
    strategy: str = "ip",
    components: Optional[List[str]] = None,
    custom_func: Optional[Callable[[Request], str]] = None,
) -> Callable[[Any], str]:
    """
    Factory function to create client key extraction functions for decorators.

    This creates functions that can be used with the @rate_limited decorator
    to extract client identifiers from function arguments.

    Args:
        strategy: Strategy to use ('ip', 'user_id', 'api_key', 'composite', 'custom')
        components: List of components for composite strategy
        custom_func: Custom extraction function

    Returns:
        Function that extracts client ID from decorator arguments
    """
    if strategy == "custom" and custom_func:

        def extract_custom(*args, **kwargs):
            # Find Request object in arguments
            for arg in args:
                if hasattr(arg, "headers") and hasattr(
                    arg, "client"
                ):  # Likely a Request
                    return custom_func(arg)
            return "unknown"

        return extract_custom

    elif strategy == "composite":
        if not components:
            components = ["ip"]

        def extract_composite(*args, **kwargs):
            for arg in args:
                if hasattr(arg, "headers") and hasattr(
                    arg, "client"
                ):  # Likely a Request
                    return ClientIdentifier.create_composite_id(arg, components)
            return "unknown"

        return extract_composite

    else:
        # Simple extraction strategies
        extractors = {
            "ip": ClientIdentifier.get_client_ip,
            "user_id": ClientIdentifier.get_user_id,
            "api_key": ClientIdentifier.get_api_key,
        }

        extractor = extractors.get(strategy, ClientIdentifier.get_client_ip)

        def extract_simple(*args, **kwargs):
            for arg in args:
                if hasattr(arg, "headers") and hasattr(
                    arg, "client"
                ):  # Likely a Request
                    result = extractor(arg)
                    return str(result) if result is not None else "unknown"
            return "unknown"

        return extract_simple


def format_rate_limit_message(
    limit: int,
    window: int,
    retry_after: float = 0,
    algorithm: str = "",
    custom_message: Optional[str] = None,
) -> str:
    """
    Format a user-friendly rate limit exceeded message.

    Args:
        limit: Rate limit (requests per window)
        window: Time window in seconds
        retry_after: Seconds until next request allowed
        algorithm: Algorithm name for context
        custom_message: Custom message template

    Returns:
        Formatted error message
    """
    if custom_message:
        return custom_message.format(
            limit=limit, window=window, retry_after=retry_after, algorithm=algorithm
        )

    # Default message format
    if window >= 3600:  # 1 hour or more
        window_str = f"{window // 3600} hour(s)"
    elif window >= 60:  # 1 minute or more
        window_str = f"{window // 60} minute(s)"
    else:
        window_str = f"{window} second(s)"

    message = f"Rate limit exceeded: {limit} requests per {window_str}"

    if retry_after > 0:
        if retry_after >= 60:
            retry_str = f"{retry_after // 60:.0f} minute(s)"
        else:
            retry_str = f"{retry_after:.1f} second(s)"
        message += f". Try again in {retry_str}"

    return message


def calculate_reset_time(window_start: float, window_duration: int) -> float:
    """
    Calculate when a rate limit window will reset.

    Args:
        window_start: Start time of the current window
        window_duration: Duration of the window in seconds

    Returns:
        Timestamp when the window resets
    """
    return window_start + window_duration


def get_retry_after_header(reset_time: float) -> str:
    """
    Calculate Retry-After header value.

    Args:
        reset_time: Timestamp when rate limit resets

    Returns:
        Retry-After value as string (seconds)
    """
    import time

    retry_after = max(0, int(reset_time - time.time()))
    return str(retry_after)
