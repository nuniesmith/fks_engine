"""
Framework Middleware Package.

This package provides comprehensive middleware components for FastAPI applications including:
- Authentication and authorization
- CORS handling
- Error handling and structured responses
- Metrics collection and monitoring
- Rate limiting and throttling
- Request ID tracking and correlation
- Performance timing and analysis
"""

import os
from typing import Any, Callable, Dict, List, Optional, Union

from fastapi import FastAPI

# Import core middleware classes
from .auth import (
    authenticate_user,
    create_access_token,
    decode_token,
    get_auth_token,
)
from .cors import (
    CORSMiddleware,
    create_cors_middleware,
    setup_cors,
)
from .error import (
    ApplicationError,
    BadRequestError,
    ConflictError,
    ErrorContext,
    ErrorResponse,
    ForbiddenError,
    NotFoundError,
    add_error_handlers,
    create_error_logger,
    register_app_errors,
)
from .metrics import (
    MetricsMiddleware,
    metrics_middleware,
)
from .rate_limiter.rate_limit import (
    RateLimitMiddleware,
    rate_limit_middleware,
)
from .request_id import (
    RequestIdMiddleware,
    create_child_id,
    get_request_duration_ms,
    get_request_id,
    get_trace_info,
    request_id_middleware,
)
from .timing import (
    TimingMiddleware,
    TimingStats,
    get_request_timing,
    setup_timing_middleware,
)

# Version information
__version__ = "1.0.0"
__author__ = "Framework Middleware Team"

# Export all public symbols
__all__ = [
    # Authentication
    "create_access_token",
    "decode_token",
    "authenticate_user",
    "get_auth_token",
    # CORS
    "CORSMiddleware",
    "setup_cors",
    "create_cors_middleware",
    # Error handling
    "ErrorResponse",
    "add_error_handlers",
    "create_error_logger",
    "ErrorContext",
    "ApplicationError",
    "BadRequestError",
    "NotFoundError",
    "ForbiddenError",
    "ConflictError",
    "register_app_errors",
    # Metrics
    "MetricsMiddleware",
    "metrics_middleware",
    # Rate limiting
    "RateLimitMiddleware",
    "rate_limit_middleware",
    # Request ID
    "RequestIdMiddleware",
    "request_id_middleware",
    "get_request_id",
    "get_trace_info",
    "get_request_duration_ms",
    "create_child_id",
    # Timing
    "TimingMiddleware",
    "TimingStats",
    "get_request_timing",
    "setup_timing_middleware",
    # Setup functions
    "setup_all_middleware",
    "setup_basic_middleware",
    "setup_production_middleware",
    "setup_development_middleware",
    "MiddlewareConfig",
    "create_middleware_config",
]


# Configuration class for middleware setup
class MiddlewareConfig:
    """Configuration class for middleware setup."""

    def __init__(
        self,
        # Request ID configuration
        request_id_enabled: bool = True,
        request_id_header: str = "X-Request-ID",
        # Timing configuration
        timing_enabled: bool = True,
        timing_header: str = "X-Process-Time",
        timing_slow_threshold_ms: float = 500,
        # CORS configuration
        cors_enabled: bool = True,
        cors_origins: List[str] = None,
        cors_allow_credentials: bool = True,
        cors_allow_methods: List[str] = None,
        cors_allow_headers: List[str] = None,
        # Error handling configuration
        error_handling_enabled: bool = True,
        include_exception_details: bool = False,
        log_validation_errors: bool = True,
        # Metrics configuration
        metrics_enabled: bool = True,
        metrics_exclude_paths: List[str] = None,
        # Rate limiting configuration
        rate_limit_enabled: bool = False,
        rate_limit_requests: int = 100,
        rate_limit_window_seconds: int = 60,
        rate_limit_exclude_paths: List[str] = None,
        # Environment-specific settings
        environment: str = None,
    ):

        # Auto-detect environment if not provided
        if environment is None:
            environment = os.getenv("ENVIRONMENT", "development").lower()

        self.environment = environment

        # Request ID settings
        self.request_id_enabled = request_id_enabled
        self.request_id_header = request_id_header

        # Timing settings
        self.timing_enabled = timing_enabled
        self.timing_header = timing_header
        self.timing_slow_threshold_ms = timing_slow_threshold_ms

        # CORS settings
        self.cors_enabled = cors_enabled
        self.cors_origins = cors_origins or self._get_default_cors_origins()
        self.cors_allow_credentials = cors_allow_credentials
        self.cors_allow_methods = cors_allow_methods or [
            "GET",
            "POST",
            "PUT",
            "DELETE",
            "OPTIONS",
            "PATCH",
        ]
        self.cors_allow_headers = cors_allow_headers or ["*"]

        # Error handling settings
        self.error_handling_enabled = error_handling_enabled
        self.include_exception_details = (
            include_exception_details if environment != "production" else False
        )
        self.log_validation_errors = log_validation_errors

        # Metrics settings
        self.metrics_enabled = metrics_enabled
        self.metrics_exclude_paths = metrics_exclude_paths or [
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
        ]

        # Rate limiting settings
        self.rate_limit_enabled = rate_limit_enabled
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_window_seconds = rate_limit_window_seconds
        self.rate_limit_exclude_paths = rate_limit_exclude_paths or [
            "/health",
            "/docs",
            "/openapi.json",
        ]

    def _get_default_cors_origins(self) -> List[str]:
        """Get default CORS origins based on environment."""
        if self.environment == "production":
            # In production, be restrictive by default
            return []
        elif self.environment == "staging":
            # In staging, allow some common development origins
            return [
                "http://localhost:3000",
                "http://localhost:8080",
                "https://staging.example.com",
            ]
        else:
            # In development, allow common development origins
            return [
                "https://app.fkstrading.xyz",
                "https://api.fkstrading.xyz",
                "https://data.fkstrading.xyz",
                "http://localhost:3000",
                "http://localhost:8080",
                "http://localhost:8081",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:8080",
            ]


def create_middleware_config(environment: str = None, **kwargs) -> MiddlewareConfig:
    """
    Create a middleware configuration with environment-specific defaults.

    Args:
        environment: Environment name (development, staging, production)
        **kwargs: Override any MiddlewareConfig parameters

    Returns:
        MiddlewareConfig: Configured middleware settings
    """
    return MiddlewareConfig(environment=environment, **kwargs)


def setup_all_middleware(
    app: FastAPI, config: MiddlewareConfig = None, settings: Any = None
) -> Dict[str, Any]:
    """
    Setup all middleware components for a FastAPI application.

    Args:
        app: FastAPI application instance
        config: Middleware configuration
        settings: Application settings (optional)

    Returns:
        Dict: Information about configured middleware
    """
    if config is None:
        config = MiddlewareConfig()

    middleware_info = {
        "configured": [],
        "skipped": [],
        "environment": config.environment,
    }

    # Setup middleware in reverse order (last added is executed first)

    # 1. Error handling (should be first to catch all errors)
    if config.error_handling_enabled:
        add_error_handlers(
            app,
            include_exception_details=config.include_exception_details,
            log_validation_errors=config.log_validation_errors,
        )
        register_app_errors(app)
        middleware_info["configured"].append("error_handling")
    else:
        middleware_info["skipped"].append("error_handling")

    # 2. CORS (should be early to handle preflight requests)
    if config.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=config.cors_allow_credentials,
            allow_methods=config.cors_allow_methods,
            allow_headers=config.cors_allow_headers,
        )
        middleware_info["configured"].append("cors")
    else:
        middleware_info["skipped"].append("cors")

    # 3. Rate limiting (should be early to protect against abuse)
    if config.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            requests=config.rate_limit_requests,
            window_seconds=config.rate_limit_window_seconds,
            exclude_paths=config.rate_limit_exclude_paths,
        )
        middleware_info["configured"].append("rate_limiting")
    else:
        middleware_info["skipped"].append("rate_limiting")

    # 4. Metrics collection
    if config.metrics_enabled:
        app.add_middleware(
            MetricsMiddleware, exclude_paths=config.metrics_exclude_paths
        )
        middleware_info["configured"].append("metrics")
    else:
        middleware_info["skipped"].append("metrics")

    # 5. Timing middleware
    if config.timing_enabled:
        app.add_middleware(
            TimingMiddleware,
            header_name=config.timing_header,
            slow_threshold_ms=config.timing_slow_threshold_ms,
        )
        middleware_info["configured"].append("timing")
    else:
        middleware_info["skipped"].append("timing")

    # 6. Request ID (should be last to ensure all other middleware can use it)
    if config.request_id_enabled:
        app.add_middleware(RequestIdMiddleware, header_name=config.request_id_header)
        middleware_info["configured"].append("request_id")
    else:
        middleware_info["skipped"].append("request_id")

    return middleware_info


def setup_basic_middleware(app: FastAPI) -> Dict[str, Any]:
    """
    Setup basic middleware for simple applications.

    Args:
        app: FastAPI application instance

    Returns:
        Dict: Information about configured middleware
    """
    config = MiddlewareConfig(
        cors_enabled=True,
        error_handling_enabled=True,
        request_id_enabled=True,
        timing_enabled=True,
        metrics_enabled=False,
        rate_limit_enabled=False,
    )

    return setup_all_middleware(app, config)


def setup_production_middleware(
    app: FastAPI, cors_origins: List[str] = None, rate_limit_requests: int = 100
) -> Dict[str, Any]:
    """
    Setup production-ready middleware configuration.

    Args:
        app: FastAPI application instance
        cors_origins: Allowed CORS origins for production
        rate_limit_requests: Number of requests allowed per minute

    Returns:
        Dict: Information about configured middleware
    """
    config = MiddlewareConfig(
        environment="production",
        cors_origins=cors_origins or [],
        include_exception_details=False,
        rate_limit_enabled=True,
        rate_limit_requests=rate_limit_requests,
        timing_slow_threshold_ms=1000,  # Higher threshold for production
    )

    return setup_all_middleware(app, config)


def setup_development_middleware(app: FastAPI) -> Dict[str, Any]:
    """
    Setup development-friendly middleware configuration.

    Args:
        app: FastAPI application instance

    Returns:
        Dict: Information about configured middleware
    """
    config = MiddlewareConfig(
        environment="development",
        include_exception_details=True,
        rate_limit_enabled=False,
        timing_slow_threshold_ms=200,  # Lower threshold for development
    )

    return setup_all_middleware(app, config)


# Utility functions for middleware management
def get_middleware_info(app: FastAPI) -> Dict[str, Any]:
    """
    Get information about configured middleware.

    Args:
        app: FastAPI application instance

    Returns:
        Dict: Middleware information
    """
    middleware_stack = []

    for middleware in app.user_middleware:
        middleware_info = {
            "type": (
                middleware.cls.__name__
                if hasattr(middleware, "cls")
                else str(type(middleware))
            ),
            "args": getattr(middleware, "args", []),
            "kwargs": getattr(middleware, "kwargs", {}),
        }
        middleware_stack.append(middleware_info)

    return {"count": len(middleware_stack), "stack": middleware_stack}


def validate_middleware_config(config: MiddlewareConfig) -> List[str]:
    """
    Validate middleware configuration and return any warnings.

    Args:
        config: Middleware configuration to validate

    Returns:
        List[str]: List of warning messages
    """
    warnings = []

    # Check CORS configuration
    if (
        config.cors_enabled
        and not config.cors_origins
        and config.environment == "production"
    ):
        warnings.append("CORS is enabled in production but no origins are specified")

    # Check rate limiting
    if not config.rate_limit_enabled and config.environment == "production":
        warnings.append("Rate limiting is disabled in production environment")

    # Check exception details
    if config.include_exception_details and config.environment == "production":
        warnings.append("Exception details are enabled in production (security risk)")

    # Check timing thresholds
    if config.timing_slow_threshold_ms < 100:
        warnings.append(
            "Timing slow threshold is very low, may generate excessive logs"
        )

    return warnings


# Package metadata
__package_info__ = {
    "name": "framework.middleware",
    "version": __version__,
    "description": "Comprehensive middleware package for FastAPI applications",
    "features": [
        "JWT Authentication and authorization",
        "CORS handling with security defaults",
        "Structured error handling and responses",
        "Request metrics collection and monitoring",
        "Rate limiting and throttling",
        "Request ID tracking and distributed tracing",
        "Performance timing and analysis",
        "Environment-specific configurations",
        "Easy setup functions for common scenarios",
    ],
    "middleware_components": [
        "AuthMiddleware",
        "CORSMiddleware",
        "ErrorHandlingMiddleware",
        "MetricsMiddleware",
        "RateLimitMiddleware",
        "RequestIdMiddleware",
        "TimingMiddleware",
    ],
}


def get_package_info():
    """Get package information and features."""
    return __package_info__.copy()


# Health check for middleware package
def health_check(app: FastAPI) -> Dict[str, Any]:
    """
    Perform a health check on the middleware package.

    Args:
        app: FastAPI application instance

    Returns:
        Dict: Health check results
    """
    health_info = {
        "status": "healthy",
        "middleware_count": len(app.user_middleware),
        "components": {},
    }

    # Check each middleware component
    middleware_names = [
        m.cls.__name__ if hasattr(m, "cls") else str(type(m))
        for m in app.user_middleware
    ]

    health_info["components"] = {
        "request_id": "RequestIdMiddleware" in middleware_names,
        "timing": "TimingMiddleware" in middleware_names,
        "cors": "CORSMiddleware" in middleware_names,
        "metrics": "MetricsMiddleware" in middleware_names,
        "rate_limit": "RateLimitMiddleware" in middleware_names,
    }

    return health_info


# Context manager for temporary middleware configuration
class temporary_middleware:
    """Context manager for temporary middleware configuration."""

    def __init__(self, app: FastAPI, config: MiddlewareConfig):
        self.app = app
        self.config = config
        self.original_middleware = None

    def __enter__(self):
        # Store original middleware
        self.original_middleware = self.app.user_middleware.copy()

        # Clear existing middleware
        self.app.user_middleware.clear()

        # Setup new middleware
        setup_all_middleware(self.app, self.config)

        return self.app

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore original middleware
        if self.original_middleware is not None:
            self.app.user_middleware = self.original_middleware


# Add to exports
__all__.extend(
    [
        "get_middleware_info",
        "validate_middleware_config",
        "health_check",
        "temporary_middleware",
        "get_package_info",
    ]
)

# Auto-import check
try:
    from loguru import logger

    logger.debug("Framework middleware package imported successfully")
except ImportError:
    import logging

    logging.getLogger(__name__).info(
        "Framework middleware package imported successfully"
    )
