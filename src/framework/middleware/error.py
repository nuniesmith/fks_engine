"""
Error handling module for FastAPI applications.

This module provides comprehensive error handling for FastAPI applications,
including structured error responses, detailed validation error formatting,
error categorization, and integration with the application's logging system.
"""

import json
import sys
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


# Error response structure
class ErrorResponse:
    """Helper class for creating consistent error responses."""

    @staticmethod
    def create(
        status_code: int,
        message: str,
        error_type: str,
        details: Optional[Any] = None,
        error_code: Optional[str] = None,
        path: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a structured error response.

        Args:
            status_code: HTTP status code
            message: Human-readable error message
            error_type: Error classification
            details: Additional error details
            error_code: Application-specific error code
            path: Request path where the error occurred
            request_id: Request ID for correlation

        Returns:
            Dict: Structured error response
        """
        error = {
            "code": error_code or status_code,
            "message": message,
            "type": error_type,
        }

        if details:
            error["details"] = details

        if path:
            error["path"] = path

        if request_id:
            error["request_id"] = request_id

        return {"error": error}


def add_error_handlers(
    app: FastAPI,
    include_exception_details: bool = False,
    log_validation_errors: bool = True,
    include_request_id: bool = True,
    custom_errors: Optional[Dict[Type[Exception], int]] = None,
) -> None:
    """
    Add error handlers to the FastAPI application.

    Args:
        app: FastAPI application
        include_exception_details: Include exception details in 500 responses
            (should be False in production)
        log_validation_errors: Whether to log validation errors
        include_request_id: Include request ID in error responses
        custom_errors: Mapping of custom exception types to status codes
    """

    # Register HTTP exception handler
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Handle HTTP exceptions."""
        # Get request ID if available
        request_id = None
        if include_request_id:
            request_id = getattr(request.state, "request_id", None)

        headers = getattr(exc, "headers", None)

        # Create response
        content = ErrorResponse.create(
            status_code=exc.status_code,
            message=str(exc.detail),
            error_type="http_error",
            path=request.url.path,
            request_id=request_id,
        )

        # Log error with context
        log_context = {"request_id": request_id, "status_code": exc.status_code}
        logger.warning(
            f"HTTP exception: {exc.status_code} - {exc.detail}", **log_context
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=headers,
        )

    # Register validation error handler
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle request validation errors."""
        # Get request ID if available
        request_id = None
        if include_request_id:
            request_id = getattr(request.state, "request_id", None)

        # Extract error details
        error_details = []
        for error in exc.errors():
            # Format location for better readability
            loc = error.get("loc", [])
            location = " → ".join(str(loc_item) for loc_item in loc)

            # Add error detail
            error_details.append(
                {
                    "location": location,
                    "input_location": loc,
                    "message": error.get("msg", ""),
                    "type": error.get("type", ""),
                }
            )

        # Create response
        content = ErrorResponse.create(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="Request validation error",
            error_type="validation_error",
            details=error_details,
            path=request.url.path,
            request_id=request_id,
        )

        # Log validation errors if configured
        if log_validation_errors:
            log_context = {"request_id": request_id, "path": request.url.path}
            logger.warning(
                f"Validation error: {len(error_details)} errors", **log_context
            )
            for error in error_details:
                logger.debug(f"Validation error detail: {error}", **log_context)

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=content,
        )

    # Register Pydantic validation error handler
    @app.exception_handler(ValidationError)
    async def pydantic_validation_handler(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        """Handle Pydantic validation errors."""
        return await validation_exception_handler(
            request, RequestValidationError(exc.errors())
        )

    # Register custom error handlers
    if custom_errors:
        for exc_class, status_code in custom_errors.items():

            @app.exception_handler(exc_class)
            async def custom_exception_handler(
                request: Request,
                exc: Exception,
                status_code=status_code,
                exc_class=exc_class,
            ) -> JSONResponse:
                """Handle custom exception type."""
                # Get request ID if available
                request_id = None
                if include_request_id:
                    request_id = getattr(request.state, "request_id", None)

                # Create response
                error_type = exc_class.__name__.lower()
                if error_type.endswith("error") or error_type.endswith("exception"):
                    error_type = error_type.replace("error", "").replace(
                        "exception", ""
                    )
                    error_type = f"{error_type}_error" if error_type else "custom_error"

                content = ErrorResponse.create(
                    status_code=status_code,
                    message=str(exc),
                    error_type=error_type,
                    path=request.url.path,
                    request_id=request_id,
                )

                # Log error with context
                log_context = {"request_id": request_id, "error_type": error_type}
                logger.error(
                    f"Custom exception ({exc_class.__name__}): {str(exc)}",
                    **log_context,
                )

                return JSONResponse(
                    status_code=status_code,
                    content=content,
                )

    # Register catch-all exception handler
    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Handle all other exceptions."""
        # Get request ID if available
        request_id = None
        if include_request_id:
            request_id = getattr(request.state, "request_id", None)

        # Get exception details
        exception_details = None
        if include_exception_details:
            exception_details = {
                "exception": exc.__class__.__name__,
                "message": str(exc),
                "traceback": traceback.format_exception(
                    type(exc), exc, exc.__traceback__
                ),
            }

        # Create response
        content = ErrorResponse.create(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal server error",
            error_type="server_error",
            details=exception_details,
            path=request.url.path,
            request_id=request_id,
        )

        # Log the full exception with traceback and context
        log_context = {"request_id": request_id, "path": request.url.path}
        logger.error(f"Unhandled exception: {str(exc)}", **log_context)
        logger.error(traceback.format_exc())

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=content,
        )


def create_error_logger(
    app: FastAPI,
    log_request_body: bool = False,
    include_headers: bool = False,
    sensitive_headers: Optional[Set[str]] = None,
) -> Callable[[Request, Exception], Any]:
    """
    Create a middleware to log errors.

    Args:
        app: FastAPI application
        log_request_body: Whether to log request body on error
        include_headers: Whether to include request headers in logs
        sensitive_headers: Set of headers to redact from logs

    Returns:
        Error logging middleware function
    """
    sensitive_headers = sensitive_headers or {
        "authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie",
        "x-auth-token",
    }

    @app.middleware("http")
    async def log_errors(request: Request, call_next):
        """Log errors in requests."""
        # Start time for request duration
        start_time = time.time()

        # Get request ID if available
        request_id = getattr(request.state, "request_id", None)

        method = request.method
        path = request.url.path
        query_string = request.url.query
        client_host = request.client.host if request.client else None

        # Create log context
        log_context = {
            "method": method,
            "path": path,
            "client_ip": client_host,
        }

        if request_id:
            log_context["request_id"] = request_id

        if query_string:
            log_context["query"] = query_string

        # Include headers if configured
        if include_headers:
            # Filter sensitive headers
            safe_headers = {}
            for header_name, header_value in request.headers.items():
                if header_name.lower() in sensitive_headers:
                    safe_headers[header_name] = "[REDACTED]"
                else:
                    safe_headers[header_name] = header_value

            log_context["headers"] = safe_headers

        # Include request body if configured
        request_body = None
        if log_request_body:
            try:
                # Try to get JSON body
                request_body = await request.json()
                log_context["request_body"] = request_body
            except Exception:
                # Not JSON or other error, ignore
                pass

        try:
            # Process the request
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log successful response at debug level
            logger.debug(
                f"Request completed: {method} {path} - {response.status_code} ({duration_ms:.2f}ms)",
                status_code=response.status_code,
                duration_ms=duration_ms,
                **log_context,
            )

            return response

        except Exception as exc:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log the exception with context
            logger.error(
                f"Error processing request: {method} {path} - {str(exc)} ({duration_ms:.2f}ms)",
                exc_info=True,
                error=str(exc),
                error_type=exc.__class__.__name__,
                duration_ms=duration_ms,
                **log_context,
            )

            # Add additional request context to state for error handlers
            request.state.duration_ms = duration_ms

            # Re-raise the exception to be handled by exception handlers
            raise

    return log_errors


class ErrorContext:
    """Utility class for adding context to errors."""

    @staticmethod
    def add_context(request: Request, **kwargs) -> None:
        """
        Add error context to request state.

        This can be used to add additional information to error responses.

        Args:
            request: FastAPI request object
            **kwargs: Additional context key-value pairs
        """
        if not hasattr(request.state, "error_context"):
            request.state.error_context = {}

        request.state.error_context.update(kwargs)

    @staticmethod
    def get_context(request: Request) -> Dict[str, Any]:
        """
        Get error context from request state.

        Args:
            request: FastAPI request object

        Returns:
            Dict: Error context
        """
        return getattr(request.state, "error_context", {})


# Common custom exceptions
class ApplicationError(Exception):
    """Base class for application-specific errors."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_type = "application_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details
        super().__init__(message)


class BadRequestError(ApplicationError):
    """Error raised when the request contains invalid data."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_type = "bad_request_error"


class NotFoundError(ApplicationError):
    """Error raised when a requested resource is not found."""

    status_code = status.HTTP_404_NOT_FOUND
    error_type = "not_found_error"


class ForbiddenError(ApplicationError):
    """Error raised when the user does not have access to a resource."""

    status_code = status.HTTP_403_FORBIDDEN
    error_type = "forbidden_error"


class ConflictError(ApplicationError):
    """Error raised when a resource already exists or a conflict occurs."""

    status_code = status.HTTP_409_CONFLICT
    error_type = "conflict_error"


# Register application-specific errors
def register_app_errors(app: FastAPI) -> None:
    """
    Register handlers for application-specific errors.

    Args:
        app: FastAPI application
    """

    @app.exception_handler(ApplicationError)
    async def app_error_handler(
        request: Request, exc: ApplicationError
    ) -> JSONResponse:
        """Handle application errors."""
        # Get request ID if available
        request_id = getattr(request.state, "request_id", None)

        # Get additional context
        error_context = ErrorContext.get_context(request)

        # Merge error details with context
        details = exc.details or {}
        if error_context:
            details.update(error_context)

        # Create response
        content = ErrorResponse.create(
            status_code=exc.status_code,
            message=exc.message,
            error_type=exc.error_type,
            details=details if details else None,
            path=request.url.path,
            request_id=request_id,
        )

        # Log error with context
        log_context = {"request_id": request_id, "error_type": exc.error_type}
        logger.error(f"Application error: {exc.message}", **log_context)

        return JSONResponse(
            status_code=exc.status_code,
            content=content,
        )
