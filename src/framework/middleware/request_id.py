"""
Request ID middleware for distributed request tracing.

This module provides a comprehensive middleware implementation for generating,
extracting, and propagating request IDs across services, enabling distributed
tracing and request correlation in both logs and monitoring systems.
"""

import hashlib
import platform
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds a unique request ID to each request.

    This middleware ensures that every request has a unique identifier
    which can be used for tracing through logs and across services.

    Features include:
    - Generation of UUIDs for each request
    - Reading existing request IDs from headers
    - Adding request IDs to all log messages
    - Propagating request IDs to response headers
    - Support for W3C Trace Context and other tracing standards
    - Integration with popular tracing systems
    - Performance metrics for request tracking
    """

    def __init__(
        self,
        app: ASGIApp,
        header_name: str = "X-Request-ID",
        response_header_name: Optional[str] = None,
        include_in_response: bool = True,
        enforce_uuid_format: bool = False,
        contextualizer_name: str = "request_id",
        generator: Optional[Callable[[], str]] = None,
        trace_header_names: Optional[List[str]] = None,
        include_trace_context: bool = True,
        include_timing: bool = True,
        node_id: Optional[str] = None,
        max_id_length: int = 128,
    ):
        """
        Initialize request ID middleware.

        Args:
            app: ASGI application
            header_name: Name of header to extract request ID from
            response_header_name: Name of header for response (defaults to header_name)
            include_in_response: Whether to include the request ID in response headers
            enforce_uuid_format: Whether to enforce UUID format for incoming request IDs
            contextualizer_name: Name for loguru contextualizer
            generator: Function to generate request IDs (defaults to UUID4)
            trace_header_names: Additional headers to check for request IDs
            include_trace_context: Whether to include W3C trace context headers
            include_timing: Whether to add timing information to request state
            node_id: Optional identifier for this service node (for distributed tracing)
            max_id_length: Maximum allowed length for request IDs
        """
        super().__init__(app)
        self.header_name = header_name
        self.response_header_name = response_header_name or header_name
        self.include_in_response = include_in_response
        self.enforce_uuid_format = enforce_uuid_format
        self.contextualizer_name = contextualizer_name
        self.generator = generator or self._default_id_generator
        self.max_id_length = max_id_length
        self.include_trace_context = include_trace_context
        self.include_timing = include_timing

        # Combine user-provided trace headers with defaults
        default_trace_headers = [
            "X-B3-TraceId",  # Zipkin
            "X-Request-ID",  # General
            "X-Correlation-ID",  # General
            "traceparent",  # W3C Trace Context
            "X-Cloud-Trace-Context",  # Google Cloud Trace
            "X-Amzn-Trace-Id",  # AWS X-Ray
            "uber-trace-id",  # Jaeger
            "request-id",  # Microsoft
            "X-Datadog-Trace-ID",  # Datadog
        ]

        user_headers = trace_header_names or []
        self.trace_header_names = list(set(default_trace_headers + user_headers))

        # Generate or use provided node ID
        self.node_id = node_id or self._generate_node_id()

        # Metrics for observability
        self.new_ids_generated = 0
        self.ids_propagated = 0

        logger.debug(
            f"Request ID middleware initialized with header: {header_name}, "
            + f"node_id: {self.node_id[:8]}..., "
            + f"trace headers: {len(self.trace_header_names)}"
        )

    def _default_id_generator(self) -> str:
        """
        Default request ID generator using UUID4.

        Returns:
            str: Generated request ID
        """
        return str(uuid.uuid4())

    def _generate_node_id(self) -> str:
        """
        Generate a unique ID for this service node.

        Returns:
            str: Node ID
        """
        # Combine hostname, process ID, and random bits for uniqueness
        host = platform.node() or "unknown"
        pid = str(hash(time.process_time()))
        random_bits = uuid.uuid4().hex[:8]

        # Create a hash to avoid leaking potentially sensitive system information
        node_id = hashlib.md5(f"{host}-{pid}-{random_bits}".encode()).hexdigest()

        return node_id

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process the request and add request ID.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response: The HTTP response
        """
        # Start timing if configured
        start_time = time.time() if self.include_timing else None

        # Get or generate a request ID and trace info
        request_id, trace_info = self._get_or_generate_request_id(request)

        # Store in request state for other middleware and endpoints
        request.state.request_id = request_id

        # Store trace info if present
        if trace_info:
            request.state.trace_info = trace_info

        # Add timing methods if configured
        if self.include_timing:
            self._add_timing_info(request, start_time)

        # Create correlation context for logs
        correlation_context = {
            self.contextualizer_name: request_id,
            "method": request.method,
            "path": request.url.path,
        }

        # Add trace info to context if available
        if trace_info:
            correlation_context.update({f"trace_{k}": v for k, v in trace_info.items()})

        # Log request with context
        with logger.contextualize(**correlation_context):
            logger.debug(
                f"Request started: {request.method} {request.url.path}",
                request_id=request_id,
                client_ip=request.client.host if request.client else None,
                trace_info=trace_info,
            )

            try:
                # Process the request
                response = await call_next(request)

                # Add request ID to response headers if configured
                if self.include_in_response and request_id:
                    response.headers[self.response_header_name] = request_id

                # Add trace context headers if configured
                if self.include_trace_context and trace_info:
                    self._add_trace_context_headers(response, request_id, trace_info)

                # Get duration if timing is enabled
                duration_ms = None
                if self.include_timing:
                    elapsed_time = getattr(request.state, "get_elapsed_time", None)
                    if elapsed_time and callable(elapsed_time):
                        duration_ms = elapsed_time() * 1000  # Convert to ms

                # Log completion
                logger.debug(
                    f"Request completed: {response.status_code}",
                    request_id=request_id,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )

                return response

            except Exception as e:
                # Calculate duration on error if timing is enabled
                duration_ms = None
                if self.include_timing:
                    duration_ms = (
                        (time.time() - start_time) * 1000 if start_time else None
                    )

                # Log exception with request context
                logger.exception(
                    f"Request failed: {str(e)}",
                    request_id=request_id,
                    error=str(e),
                    error_type=e.__class__.__name__,
                    duration_ms=duration_ms,
                )
                raise

    def _get_or_generate_request_id(
        self, request: Request
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Get existing request ID from headers or generate a new one.

        Args:
            request: The incoming request

        Returns:
            Tuple[str, Optional[Dict]]: Request ID and trace info if available
        """
        request_id = None
        trace_info = {}

        # Check the primary header first
        if self.header_name in request.headers:
            request_id = request.headers.get(self.header_name)
            if request_id:
                self.ids_propagated += 1
                logger.trace(f"Using request ID from {self.header_name}: {request_id}")

        # If not found, try alternative trace headers
        if not request_id:
            for header in self.trace_header_names:
                if header.lower() in request.headers:
                    header_value = request.headers[header]

                    # Process special headers that contain additional trace info
                    if header.lower() == "traceparent":
                        # W3C Trace Context format: version-traceid-parentid-flags
                        try:
                            parts = header_value.split("-")
                            if len(parts) >= 3:
                                request_id = parts[1]  # Use trace ID as request ID
                                trace_info["version"] = parts[0]
                                trace_info["parent_id"] = parts[2]
                                if len(parts) > 3:
                                    trace_info["flags"] = parts[3]
                        except Exception:
                            # If parsing fails, just use the whole value
                            request_id = header_value

                    elif header.lower() == "x-b3-traceid":
                        # Zipkin B3 format has separate headers for trace ID and span ID
                        request_id = header_value
                        # Try to get span ID if present
                        span_id = request.headers.get("X-B3-SpanId")
                        if span_id:
                            trace_info["span_id"] = span_id

                        # Check for additional B3 headers
                        parent_span_id = request.headers.get("X-B3-ParentSpanId")
                        if parent_span_id:
                            trace_info["parent_span_id"] = parent_span_id

                        sampled = request.headers.get("X-B3-Sampled")
                        if sampled:
                            trace_info["sampled"] = sampled

                    else:
                        # For other headers, just use the value directly
                        request_id = header_value

                    if request_id:
                        self.ids_propagated += 1
                        logger.trace(f"Using request ID from {header}: {request_id}")
                        break

        # Validate UUID format if required
        if request_id and self.enforce_uuid_format:
            try:
                # Verify it's a valid UUID
                uuid.UUID(request_id)
            except ValueError:
                logger.debug(
                    f"Invalid UUID format in request ID: {request_id}, generating new one"
                )
                request_id = None

        # Generate a new ID if needed
        if not request_id:
            request_id = self.generator()
            self.new_ids_generated += 1
            logger.debug(f"Generated new request ID: {request_id}")

            # Initialize trace info for new IDs
            trace_info = {
                "node_id": self.node_id,
                "generated": True,
                "timestamp": time.time(),
            }

        # Ensure ID doesn't exceed maximum length
        if len(request_id) > self.max_id_length:
            request_id = request_id[: self.max_id_length]

        return request_id, trace_info if trace_info else None

    def _add_timing_info(self, request: Request, start_time: Optional[float]) -> None:
        """
        Add timing information to the request state.

        Args:
            request: The request to add timing info to
            start_time: Start time of request processing
        """
        if start_time is None:
            return

        # Add start time to request state
        request.state.start_time = start_time

        # Add a method to get elapsed time
        def get_elapsed_time():
            return time.time() - request.state.start_time

        request.state.get_elapsed_time = get_elapsed_time

    def _add_trace_context_headers(
        self, response: Response, request_id: str, trace_info: Optional[Dict[str, Any]]
    ) -> None:
        """
        Add W3C Trace Context headers to the response.

        Args:
            response: The HTTP response
            request_id: The request ID
            trace_info: Additional trace information
        """
        if not trace_info:
            return

        # If we received a traceparent header, propagate it
        if "version" in trace_info and "parent_id" in trace_info:
            version = trace_info.get("version", "00")
            parent_id = trace_info.get("parent_id", "")
            flags = trace_info.get("flags", "01")  # Default to sampled

            # Construct W3C traceparent
            traceparent = f"{version}-{request_id}-{parent_id}-{flags}"
            response.headers["traceparent"] = traceparent

        # If we have B3 trace info, propagate it
        if "span_id" in trace_info:
            response.headers["X-B3-TraceId"] = request_id
            response.headers["X-B3-SpanId"] = trace_info["span_id"]

            if "parent_span_id" in trace_info:
                response.headers["X-B3-ParentSpanId"] = trace_info["parent_span_id"]

            if "sampled" in trace_info:
                response.headers["X-B3-Sampled"] = trace_info["sampled"]

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the request ID middleware.

        Returns:
            Dict: Middleware statistics
        """
        total_requests = self.new_ids_generated + self.ids_propagated
        propagation_rate = (
            (self.ids_propagated / total_requests) if total_requests > 0 else 0
        )

        return {
            "new_ids_generated": self.new_ids_generated,
            "ids_propagated": self.ids_propagated,
            "total_requests": total_requests,
            "propagation_rate": propagation_rate,
            "node_id": self.node_id,
        }


# Utils for working with request IDs


def get_request_id(request: Request) -> Optional[str]:
    """
    Get the request ID from a request object.

    Args:
        request: FastAPI request

    Returns:
        Optional[str]: Request ID if available
    """
    return getattr(request.state, "request_id", None)


def get_trace_info(request: Request) -> Optional[Dict[str, Any]]:
    """
    Get trace information from a request object.

    Args:
        request: FastAPI request

    Returns:
        Optional[Dict]: Trace information if available
    """
    return getattr(request.state, "trace_info", None)


def get_request_duration_ms(request: Request) -> Optional[float]:
    """
    Get the current request duration in milliseconds.

    Args:
        request: FastAPI request

    Returns:
        Optional[float]: Duration in milliseconds if available
    """
    elapsed_time = getattr(request.state, "get_elapsed_time", None)
    if elapsed_time and callable(elapsed_time):
        return elapsed_time() * 1000  # Convert to ms
    return None


def create_child_id(parent_id: str) -> str:
    """
    Create a child request ID for internal service calls.

    Args:
        parent_id: Parent request ID

    Returns:
        str: Child request ID
    """
    # Create a child ID that's linked to the parent
    child_id = str(uuid.uuid4())
    return f"{parent_id[:8]}-{child_id}"


# Legacy function-based middleware for backward compatibility
async def request_id_middleware(request: Request, call_next: Callable) -> Response:
    """
    Legacy function-based middleware that adds a unique request ID to each request.

    This implementation is maintained for backward compatibility.
    New code should use the RequestIdMiddleware class.

    Args:
        request: The incoming request
        call_next: The next middleware or route handler

    Returns:
        Response: The HTTP response
    """
    # Check for existing request ID
    request_id = request.headers.get("X-Request-ID")

    # Generate a new ID if not present
    if not request_id:
        request_id = str(uuid.uuid4())

    # Add request ID to request state
    request.state.request_id = request_id

    # Create a new context with request ID for logging
    with logger.contextualize(request_id=request_id):
        logger.debug(f"Request started: {request.method} {request.url.path}")

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.debug(f"Request completed: {response.status_code}")
            return response
        except Exception as e:
            logger.exception(f"Request failed: {str(e)}")
            raise
