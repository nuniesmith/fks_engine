"""
CORS (Cross-Origin Resource Sharing) middleware for FastAPI applications.

This module provides comprehensive CORS support with security-focused defaults,
configurable origins, methods, and headers, and proper handling of preflight requests.
"""

import os
import re
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, Union
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.responses import Response as FastAPIResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp


class CORSMiddleware(BaseHTTPMiddleware):
    """
    CORS middleware that handles cross-origin requests with security-focused defaults.

    This middleware provides comprehensive CORS support including:
    - Origin validation with wildcard and regex support
    - Proper preflight request handling
    - Configurable methods, headers, and credentials
    - Security-focused defaults for production environments
    - Detailed logging for debugging and security monitoring
    """

    def __init__(
        self,
        app: ASGIApp,
        allow_origins: List[str] = None,
        allow_origin_regex: Optional[str] = None,
        allow_methods: List[str] = None,
        allow_headers: List[str] = None,
        allow_credentials: bool = False,
        expose_headers: List[str] = None,
        max_age: int = 600,
        allow_all_origins: bool = False,
        preflight_response_class: type = PlainTextResponse,
        vary_header: bool = True,
        log_cors_requests: bool = True,
        environment: Optional[str] = None,
    ):
        """
        Initialize CORS middleware.

        Args:
            app: ASGI application
            allow_origins: List of allowed origins (exact matches)
            allow_origin_regex: Regex pattern for allowed origins
            allow_methods: List of allowed HTTP methods
            allow_headers: List of allowed headers
            allow_credentials: Whether to allow credentials
            expose_headers: List of headers to expose to the browser
            max_age: Maximum age for preflight cache in seconds
            allow_all_origins: Whether to allow all origins (WARNING: insecure)
            preflight_response_class: Response class for preflight requests
            vary_header: Whether to add Vary header
            log_cors_requests: Whether to log CORS requests
            environment: Environment name for configuration
        """
        super().__init__(app)

        # Determine environment
        self.environment = (
            environment or os.getenv("ENVIRONMENT", "development").lower()
        )

        # Configure origins
        self.allow_all_origins = allow_all_origins
        self.allow_origins = self._process_origins(allow_origins or [])
        self.allow_origin_regex = self._compile_origin_regex(allow_origin_regex)

        # Configure methods
        default_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"]
        self.allow_methods = set(allow_methods or default_methods)

        # Configure headers
        default_headers = [
            "accept",
            "accept-language",
            "content-language",
            "content-type",
            "authorization",
            "x-requested-with",
            "x-api-key",
            "x-request-id",
            "x-correlation-id",
        ]
        self.allow_headers = self._process_headers(allow_headers or default_headers)

        # Configure other settings
        self.allow_credentials = allow_credentials
        self.expose_headers = expose_headers or []
        self.max_age = max_age
        self.preflight_response_class = preflight_response_class
        self.vary_header = vary_header
        self.log_cors_requests = log_cors_requests

        # Security validations
        self._validate_configuration()

        # Statistics
        self.preflight_requests = 0
        self.cors_requests = 0
        self.blocked_requests = 0

        logger.info(f"CORS middleware initialized for {self.environment} environment")
        if self.allow_all_origins:
            logger.warning(
                "CORS configured to allow all origins - ensure this is intentional"
            )

    def _process_origins(self, origins: List[str]) -> Set[str]:
        """
        Process and validate origin configurations.

        Args:
            origins: List of origin strings

        Returns:
            Set of processed origins
        """
        processed = set()

        for origin in origins:
            # Remove trailing slash for consistency
            origin = origin.rstrip("/")

            # Validate origin format
            if origin == "*":
                if not self.allow_all_origins:
                    logger.warning(
                        "Wildcard origin '*' found but allow_all_origins is False"
                    )
                continue

            # Validate URL format
            try:
                parsed = urlparse(origin)
                if not parsed.scheme or not parsed.netloc:
                    logger.warning(f"Invalid origin format: {origin}")
                    continue

                # Reconstruct clean origin
                clean_origin = f"{parsed.scheme}://{parsed.netloc}"
                processed.add(clean_origin)

            except Exception as e:
                logger.warning(f"Failed to parse origin {origin}: {e}")

        return processed

    def _compile_origin_regex(self, pattern: Optional[str]) -> Optional[Pattern]:
        """
        Compile origin regex pattern.

        Args:
            pattern: Regex pattern string

        Returns:
            Compiled regex pattern or None
        """
        if not pattern:
            return None

        try:
            return re.compile(pattern)
        except re.error as e:
            logger.error(f"Invalid origin regex pattern '{pattern}': {e}")
            return None

    def _process_headers(self, headers: List[str]) -> Set[str]:
        """
        Process and normalize header names.

        Args:
            headers: List of header names

        Returns:
            Set of normalized header names
        """
        # Normalize to lowercase for case-insensitive matching
        return {header.lower() for header in headers}

    def _validate_configuration(self) -> None:
        """Validate CORS configuration for security issues."""

        # Check for insecure configurations in production
        if self.environment == "production":
            if self.allow_all_origins:
                logger.error(
                    "CORS allows all origins in production - this is a security risk"
                )

            if self.allow_credentials and self.allow_all_origins:
                logger.error(
                    "CORS allows credentials with all origins - this is prohibited by spec"
                )

            if "*" in self.allow_headers:
                logger.warning(
                    "CORS allows all headers in production - consider restricting"
                )

    def _is_origin_allowed(self, origin: str) -> bool:
        """
        Check if an origin is allowed.

        Args:
            origin: Origin to check

        Returns:
            bool: True if origin is allowed
        """
        if self.allow_all_origins:
            return True

        # Remove trailing slash for comparison
        origin = origin.rstrip("/")

        # Check exact matches
        if origin in self.allow_origins:
            return True

        # Check regex pattern
        if self.allow_origin_regex and self.allow_origin_regex.match(origin):
            return True

        return False

    def _get_cors_headers(self, origin: str, request_method: str) -> Dict[str, str]:
        """
        Get CORS headers for a response.

        Args:
            origin: Request origin
            request_method: HTTP method

        Returns:
            Dict of CORS headers
        """
        headers = {}

        # Access-Control-Allow-Origin
        if self.allow_all_origins:
            if self.allow_credentials:
                # When credentials are allowed, can't use wildcard
                headers["Access-Control-Allow-Origin"] = origin
            else:
                headers["Access-Control-Allow-Origin"] = "*"
        elif self._is_origin_allowed(origin):
            headers["Access-Control-Allow-Origin"] = origin

        # Access-Control-Allow-Credentials
        if self.allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"

        # Access-Control-Expose-Headers
        if self.expose_headers:
            headers["Access-Control-Expose-Headers"] = ", ".join(self.expose_headers)

        # Vary header for caching
        if self.vary_header and not self.allow_all_origins:
            headers["Vary"] = "Origin"

        return headers

    def _get_preflight_headers(
        self, origin: str, request_method: str, request_headers: str
    ) -> Dict[str, str]:
        """
        Get headers for preflight response.

        Args:
            origin: Request origin
            request_method: Requested method
            request_headers: Requested headers

        Returns:
            Dict of preflight headers
        """
        headers = self._get_cors_headers(origin, request_method)

        # Access-Control-Allow-Methods
        if request_method in self.allow_methods or request_method == "OPTIONS":
            headers["Access-Control-Allow-Methods"] = ", ".join(
                sorted(self.allow_methods)
            )

        # Access-Control-Allow-Headers
        if request_headers:
            requested_headers = {h.strip().lower() for h in request_headers.split(",")}

            # Check if all requested headers are allowed
            if "*" in self.allow_headers or requested_headers.issubset(
                self.allow_headers
            ):
                if "*" in self.allow_headers:
                    headers["Access-Control-Allow-Headers"] = request_headers
                else:
                    # Only include the actually allowed headers
                    allowed_requested = requested_headers.intersection(
                        self.allow_headers
                    )
                    if allowed_requested:
                        headers["Access-Control-Allow-Headers"] = ", ".join(
                            sorted(allowed_requested)
                        )

        # Access-Control-Max-Age
        headers["Access-Control-Max-Age"] = str(self.max_age)

        return headers

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process the request and handle CORS.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response: The HTTP response with CORS headers
        """
        origin = request.headers.get("origin")

        # If no origin header, this is not a CORS request
        if not origin:
            return await call_next(request)

        # Get request ID for logging context
        request_id = getattr(request.state, "request_id", None)
        log_context = {"request_id": request_id} if request_id else {}

        # Log CORS request if enabled
        if self.log_cors_requests:
            logger.debug(
                f"CORS request from origin: {origin}",
                origin=origin,
                method=request.method,
                path=request.url.path,
                **log_context,
            )

        # Check if origin is allowed
        if not self._is_origin_allowed(origin):
            self.blocked_requests += 1
            logger.warning(
                f"CORS request blocked - origin not allowed: {origin}",
                origin=origin,
                method=request.method,
                **log_context,
            )

            # Return a 403 response for blocked origins
            return PlainTextResponse(
                "CORS request blocked - origin not allowed", status_code=403
            )

        # Handle preflight requests
        if request.method == "OPTIONS":
            self.preflight_requests += 1

            request_method = request.headers.get("access-control-request-method")
            request_headers = request.headers.get("access-control-request-headers")

            # Validate preflight request
            if not request_method:
                logger.warning(
                    "Invalid preflight request - missing Access-Control-Request-Method",
                    origin=origin,
                    **log_context,
                )
                return PlainTextResponse("Invalid preflight request", status_code=400)

            # Check if method is allowed
            if request_method not in self.allow_methods:
                logger.warning(
                    f"CORS preflight blocked - method not allowed: {request_method}",
                    origin=origin,
                    method=request_method,
                    **log_context,
                )
                return PlainTextResponse("Method not allowed", status_code=405)

            # Get preflight headers
            cors_headers = self._get_preflight_headers(
                origin, request_method, request_headers
            )

            logger.debug(
                f"CORS preflight response for {origin}",
                origin=origin,
                requested_method=request_method,
                requested_headers=request_headers,
                **log_context,
            )

            return self.preflight_response_class(
                content="", status_code=204, headers=cors_headers
            )

        # Handle actual CORS request
        self.cors_requests += 1

        # Process the request
        response = await call_next(request)

        # Add CORS headers to response
        cors_headers = self._get_cors_headers(origin, request.method)

        for header_name, header_value in cors_headers.items():
            response.headers[header_name] = header_value

        return response

    def get_stats(self) -> Dict[str, Any]:
        """
        Get CORS middleware statistics.

        Returns:
            Dict: CORS statistics
        """
        total_requests = (
            self.preflight_requests + self.cors_requests + self.blocked_requests
        )

        return {
            "total_requests": total_requests,
            "preflight_requests": self.preflight_requests,
            "cors_requests": self.cors_requests,
            "blocked_requests": self.blocked_requests,
            "block_rate": (
                self.blocked_requests / total_requests if total_requests > 0 else 0
            ),
            "configuration": {
                "allow_all_origins": self.allow_all_origins,
                "allow_credentials": self.allow_credentials,
                "allowed_origins_count": len(self.allow_origins),
                "allowed_methods_count": len(self.allow_methods),
                "allowed_headers_count": len(self.allow_headers),
                "max_age": self.max_age,
            },
        }


def setup_cors(
    app: FastAPI,
    environment: str = None,
    allow_origins: List[str] = None,
    allow_credentials: bool = None,
    **kwargs,
) -> CORSMiddleware:
    """
    Setup CORS middleware with environment-specific defaults.

    Args:
        app: FastAPI application
        environment: Environment name (development, staging, production)
        allow_origins: List of allowed origins
        allow_credentials: Whether to allow credentials
        **kwargs: Additional CORS configuration options

    Returns:
        CORSMiddleware: The configured CORS middleware instance
    """
    if environment is None:
        environment = os.getenv("ENVIRONMENT", "development").lower()

    # Environment-specific defaults
    if environment == "production":
        defaults = {
            "allow_origins": allow_origins or [],
            "allow_credentials": (
                allow_credentials if allow_credentials is not None else False
            ),
            "allow_all_origins": False,
            "log_cors_requests": True,
            "max_age": 3600,  # Longer cache in production
        }
    elif environment == "staging":
        defaults = {
            "allow_origins": (
                allow_origins
                or ["https://staging.example.com", "http://localhost:3000"]
            ),
            "allow_credentials": (
                allow_credentials if allow_credentials is not None else True
            ),
            "allow_all_origins": False,
            "log_cors_requests": True,
            "max_age": 600,
        }
    else:  # development
        defaults = {
            "allow_origins": (
                allow_origins
                or [
                    "https://app.fkstrading.xyz",
                    "https://api.fkstrading.xyz", 
                    "https://data.fkstrading.xyz",
                    "http://localhost:3000",
                    "http://localhost:8080",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:8080",
                ]
            ),
            "allow_credentials": (
                allow_credentials if allow_credentials is not None else True
            ),
            "allow_all_origins": False,
            "log_cors_requests": False,  # Less verbose in development
            "max_age": 60,  # Short cache in development
        }

    # Merge with provided kwargs
    config = {**defaults, **kwargs, "environment": environment}

    # Create and add middleware
    cors_middleware = CORSMiddleware(app, **config)
    app.add_middleware(lambda app: cors_middleware)

    logger.info(f"CORS middleware configured for {environment} environment")
    if config.get("allow_all_origins"):
        logger.warning("CORS configured to allow all origins")

    return cors_middleware


def create_cors_middleware(
    allow_origins: List[str] = None,
    allow_origin_regex: str = None,
    allow_credentials: bool = False,
    **kwargs,
) -> CORSMiddleware:
    """
    Create a CORS middleware instance without adding it to an app.

    Args:
        allow_origins: List of allowed origins
        allow_origin_regex: Regex pattern for allowed origins
        allow_credentials: Whether to allow credentials
        **kwargs: Additional CORS configuration options

    Returns:
        CORSMiddleware: Configured CORS middleware instance
    """

    # This is a factory function that would be used with app.add_middleware()
    def middleware_factory(app: ASGIApp) -> CORSMiddleware:
        return CORSMiddleware(
            app,
            allow_origins=allow_origins,
            allow_origin_regex=allow_origin_regex,
            allow_credentials=allow_credentials,
            **kwargs,
        )

    return middleware_factory


# Utility functions for CORS validation
def validate_origin(origin: str) -> bool:
    """
    Validate if an origin string is properly formatted.

    Args:
        origin: Origin string to validate

    Returns:
        bool: True if origin is valid
    """
    try:
        parsed = urlparse(origin)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


def get_cors_preflight_response(
    origin: str,
    method: str,
    headers: str = None,
    allow_credentials: bool = False,
    max_age: int = 600,
) -> Response:
    """
    Create a manual CORS preflight response.

    Args:
        origin: Request origin
        method: Requested method
        headers: Requested headers
        allow_credentials: Whether to allow credentials
        max_age: Cache max age

    Returns:
        Response: CORS preflight response
    """
    cors_headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": method,
        "Access-Control-Max-Age": str(max_age),
    }

    if headers:
        cors_headers["Access-Control-Allow-Headers"] = headers

    if allow_credentials:
        cors_headers["Access-Control-Allow-Credentials"] = "true"

    return PlainTextResponse(content="", status_code=204, headers=cors_headers)


# Security-focused CORS configurations
CORS_SECURITY_CONFIGS = {
    "strict": {
        "allow_origins": [],
        "allow_credentials": False,
        "allow_all_origins": False,
        "max_age": 600,
        "log_cors_requests": True,
    },
    "api_only": {
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "PATCH"],
        "allow_headers": ["content-type", "authorization", "x-api-key"],
        "allow_credentials": True,
        "max_age": 3600,
    },
    "development": {
        "allow_origins": [
            "https://app.fkstrading.xyz",
            "https://api.fkstrading.xyz",
            "https://data.fkstrading.xyz",
            "http://localhost:3000",
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8080",
        ],
        "allow_credentials": True,
        "max_age": 60,
        "log_cors_requests": False,
    },
}


def setup_cors_security_config(
    app: FastAPI, config_name: str, **overrides
) -> CORSMiddleware:
    """
    Setup CORS with a predefined security configuration.

    Args:
        app: FastAPI application
        config_name: Name of security configuration ('strict', 'api_only', 'development')
        **overrides: Configuration overrides

    Returns:
        CORSMiddleware: Configured CORS middleware instance
    """
    if config_name not in CORS_SECURITY_CONFIGS:
        raise ValueError(f"Unknown CORS security config: {config_name}")

    config = {**CORS_SECURITY_CONFIGS[config_name], **overrides}

    cors_middleware = CORSMiddleware(app, **config)
    app.add_middleware(lambda app: cors_middleware)

    logger.info(f"CORS middleware configured with '{config_name}' security profile")

    return cors_middleware
