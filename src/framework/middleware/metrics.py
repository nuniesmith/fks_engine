"""
Metrics middleware for monitoring API performance.

This middleware tracks detailed metrics for all API requests, providing insights into
performance, error rates, and usage patterns. It integrates with the application's
metrics collection system and provides detailed context for analysis.
"""

import statistics
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Union

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class MetricType(Enum):
    """Types of metrics that can be collected."""

    REQUEST = "request"
    ERROR = "error"
    PERFORMANCE = "performance"
    CUSTOM = "custom"


@dataclass
class RequestMetrics:
    """Data class for storing request metrics."""

    endpoint: str
    method: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    status_code: Optional[int] = None
    response_size: int = 0
    error: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    metric_type: MetricType = MetricType.REQUEST
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Calculate derived fields after initialization."""
        if self.end_time and self.start_time:
            self.duration = self.end_time - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary format."""
        return {
            "endpoint": self.endpoint,
            "method": self.method,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "duration_ms": self.duration * 1000 if self.duration else None,
            "status_code": self.status_code,
            "response_size": self.response_size,
            "error": self.error,
            "context": self.context,
            "metric_type": self.metric_type.value,
            "timestamp": self.timestamp.isoformat(),
        }


class MetricsCollector:
    """Thread-safe metrics collector for aggregating request metrics."""

    def __init__(self, max_samples: int = 10000, retention_hours: int = 24):
        """
        Initialize metrics collector.

        Args:
            max_samples: Maximum number of samples to keep in memory
            retention_hours: How long to retain metrics in hours
        """
        self.max_samples = max_samples
        self.retention_hours = retention_hours
        self._lock = Lock()

        # Raw metrics storage
        self.metrics: deque = deque(maxlen=max_samples)

        # Aggregated statistics
        self.request_count = 0
        self.error_count = 0
        self.total_duration = 0.0

        # Per-endpoint statistics
        self.endpoint_stats = defaultdict(
            lambda: {
                "count": 0,
                "errors": 0,
                "total_duration": 0.0,
                "status_codes": defaultdict(int),
                "response_sizes": deque(maxlen=100),
                "durations": deque(maxlen=100),
            }
        )

        # Per-method statistics
        self.method_stats = defaultdict(
            lambda: {"count": 0, "errors": 0, "total_duration": 0.0}
        )

        # Performance buckets
        self.performance_buckets = {
            "fast": 0,  # < 100ms
            "normal": 0,  # 100ms - 500ms
            "slow": 0,  # 500ms - 1s
            "very_slow": 0,  # > 1s
        }

        # Status code tracking
        self.status_codes = defaultdict(int)

        logger.debug(f"Metrics collector initialized with max_samples={max_samples}")

    def add_metrics(self, metrics: RequestMetrics) -> None:
        """
        Add metrics to the collector.

        Args:
            metrics: Request metrics to add
        """
        with self._lock:
            # Add to raw metrics
            self.metrics.append(metrics)

            # Update global counters
            self.request_count += 1
            if metrics.error or (metrics.status_code and metrics.status_code >= 400):
                self.error_count += 1

            if metrics.duration:
                self.total_duration += metrics.duration

                # Update performance buckets
                duration_ms = metrics.duration * 1000
                if duration_ms < 100:
                    self.performance_buckets["fast"] += 1
                elif duration_ms < 500:
                    self.performance_buckets["normal"] += 1
                elif duration_ms < 1000:
                    self.performance_buckets["slow"] += 1
                else:
                    self.performance_buckets["very_slow"] += 1

            # Update endpoint statistics
            endpoint_key = f"{metrics.method} {metrics.endpoint}"
            endpoint_stat = self.endpoint_stats[endpoint_key]
            endpoint_stat["count"] += 1

            if metrics.error or (metrics.status_code and metrics.status_code >= 400):
                endpoint_stat["errors"] += 1

            if metrics.duration:
                endpoint_stat["total_duration"] += metrics.duration
                endpoint_stat["durations"].append(metrics.duration)

            if metrics.status_code:
                endpoint_stat["status_codes"][metrics.status_code] += 1
                self.status_codes[metrics.status_code] += 1

            if metrics.response_size:
                endpoint_stat["response_sizes"].append(metrics.response_size)

            # Update method statistics
            method_stat = self.method_stats[metrics.method]
            method_stat["count"] += 1
            if metrics.error or (metrics.status_code and metrics.status_code >= 400):
                method_stat["errors"] += 1
            if metrics.duration:
                method_stat["total_duration"] += metrics.duration

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics.

        Returns:
            Dict containing summary metrics
        """
        with self._lock:
            avg_duration = (
                (self.total_duration / self.request_count)
                if self.request_count > 0
                else 0
            )
            error_rate = (
                (self.error_count / self.request_count) if self.request_count > 0 else 0
            )

            return {
                "total_requests": self.request_count,
                "total_errors": self.error_count,
                "error_rate": error_rate,
                "avg_duration_ms": avg_duration * 1000,
                "performance_distribution": self.performance_buckets.copy(),
                "status_code_distribution": dict(self.status_codes),
                "samples_in_memory": len(self.metrics),
                "retention_hours": self.retention_hours,
            }

    def get_endpoint_stats(self, top_n: int = 10) -> Dict[str, Any]:
        """
        Get per-endpoint statistics.

        Args:
            top_n: Number of top endpoints to return

        Returns:
            Dict containing endpoint statistics
        """
        with self._lock:
            endpoint_summaries = {}

            for endpoint, stats in self.endpoint_stats.items():
                avg_duration = (
                    (stats["total_duration"] / stats["count"])
                    if stats["count"] > 0
                    else 0
                )
                error_rate = (
                    (stats["errors"] / stats["count"]) if stats["count"] > 0 else 0
                )

                # Calculate percentiles if we have duration data
                p95_duration = 0
                avg_response_size = 0

                if stats["durations"]:
                    try:
                        durations_sorted = sorted(stats["durations"])
                        p95_index = int(0.95 * len(durations_sorted))
                        p95_duration = durations_sorted[
                            min(p95_index, len(durations_sorted) - 1)
                        ]
                    except (IndexError, ValueError):
                        p95_duration = avg_duration

                if stats["response_sizes"]:
                    avg_response_size = sum(stats["response_sizes"]) / len(
                        stats["response_sizes"]
                    )

                endpoint_summaries[endpoint] = {
                    "count": stats["count"],
                    "errors": stats["errors"],
                    "error_rate": error_rate,
                    "avg_duration_ms": avg_duration * 1000,
                    "p95_duration_ms": p95_duration * 1000,
                    "avg_response_size_bytes": avg_response_size,
                    "status_codes": dict(stats["status_codes"]),
                }

            # Sort by request count and return top N
            sorted_endpoints = sorted(
                endpoint_summaries.items(), key=lambda x: x[1]["count"], reverse=True
            )

            return {
                "endpoints": dict(sorted_endpoints[:top_n]),
                "total_endpoints": len(endpoint_summaries),
            }

    def get_method_stats(self) -> Dict[str, Any]:
        """Get per-method statistics."""
        with self._lock:
            method_summaries = {}

            for method, stats in self.method_stats.items():
                avg_duration = (
                    (stats["total_duration"] / stats["count"])
                    if stats["count"] > 0
                    else 0
                )
                error_rate = (
                    (stats["errors"] / stats["count"]) if stats["count"] > 0 else 0
                )

                method_summaries[method] = {
                    "count": stats["count"],
                    "errors": stats["errors"],
                    "error_rate": error_rate,
                    "avg_duration_ms": avg_duration * 1000,
                }

            return method_summaries

    def get_recent_metrics(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent metrics.

        Args:
            limit: Maximum number of metrics to return

        Returns:
            List of recent metrics
        """
        with self._lock:
            recent = list(self.metrics)[-limit:]
            return [metric.to_dict() for metric in recent]

    def reset_stats(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self.metrics.clear()
            self.request_count = 0
            self.error_count = 0
            self.total_duration = 0.0
            self.endpoint_stats.clear()
            self.method_stats.clear()
            self.performance_buckets = {k: 0 for k in self.performance_buckets}
            self.status_codes.clear()
            logger.info("Metrics collector statistics reset")


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware that collects and records metrics for all API requests.

    Features:
    - Performance tracking (request duration)
    - Status code monitoring
    - Error tracking with context
    - Response size estimation
    - Path-based filtering
    - User agent and client tracking
    - Support for streaming responses
    """

    def __init__(
        self,
        app: ASGIApp,
        metrics_collector: Optional[MetricsCollector] = None,
        exclude_paths: Optional[List[str]] = None,
        metrics_paths: Optional[List[str]] = None,
        collect_user_agent: bool = True,
        collect_query_params: bool = False,
        sampling_rate: float = 1.0,
        enable_detailed_errors: bool = False,
    ):
        """
        Initialize metrics middleware.

        Args:
            app: ASGI application
            metrics_collector: Metrics collector instance
            exclude_paths: List of path prefixes to exclude from metrics
            metrics_paths: List of path prefixes considered metrics paths (excluded to avoid recursion)
            collect_user_agent: Whether to collect user agent information
            collect_query_params: Whether to collect query parameters
            sampling_rate: Percentage of requests to sample (0.0-1.0)
            enable_detailed_errors: Whether to include detailed error information
        """
        super().__init__(app)
        self.metrics_collector = metrics_collector or MetricsCollector()
        self.exclude_paths = exclude_paths or [
            "/health",
            "/docs",
            "/openapi.json",
            "/favicon.ico",
        ]
        self.metrics_paths = metrics_paths or ["/api/v1/metrics", "/metrics"]
        self.collect_user_agent = collect_user_agent
        self.collect_query_params = collect_query_params
        self.sampling_rate = sampling_rate
        self.enable_detailed_errors = enable_detailed_errors

        logger.info(
            f"Metrics middleware initialized with sampling_rate={sampling_rate}"
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process the request and collect metrics.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response: The HTTP response
        """
        # Skip excluded paths
        path = request.url.path
        for excluded in self.exclude_paths:
            if path.startswith(excluded):
                return await call_next(request)

        # Skip metrics endpoints themselves to avoid recursion
        for metrics_path in self.metrics_paths:
            if path.startswith(metrics_path):
                return await call_next(request)

        # Apply sampling if configured
        if self.sampling_rate < 1.0:
            import random

            if random.random() > self.sampling_rate:
                return await call_next(request)

        # Get core request information
        method = request.method
        request_id = getattr(request.state, "request_id", None)

        # Create context dictionary with request details
        context = self._build_context(request, request_id)

        # Create metrics object
        request_metrics = RequestMetrics(
            endpoint=path, method=method, start_time=time.time(), context=context
        )

        try:
            # Process the request
            response = await call_next(request)

            # Record metrics
            request_metrics.end_time = time.time()
            request_metrics.duration = (
                request_metrics.end_time - request_metrics.start_time
            )
            request_metrics.status_code = response.status_code

            # Add performance classification
            request_metrics.context["performance_class"] = self._classify_performance(
                request_metrics.duration
            )

            # Capture response metadata (without body)
            self._capture_response_metadata(response, request_metrics)

            # Add to metrics collector
            self.metrics_collector.add_metrics(request_metrics)

            return response

        except HTTPException as e:
            # Handle FastAPI HTTP exceptions
            return self._handle_http_exception(e, request_metrics)
        except Exception as e:
            # Handle unexpected exceptions
            return self._handle_unhandled_exception(e, request_metrics)

    def _build_context(
        self, request: Request, request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build detailed context information from the request.

        Args:
            request: The request object
            request_id: Optional request ID

        Returns:
            Dict containing context information
        """
        context = {
            "client_ip": request.client.host if request.client else None,
            "request_id": request_id,
            "content_type": request.headers.get("content-type"),
            "accept": request.headers.get("accept"),
        }

        # Add path and query parameters if configured
        if hasattr(request, "path_params"):
            context["path_params"] = dict(request.path_params)

        if self.collect_query_params:
            context["query_params"] = dict(request.query_params)

        # Add user agent if configured
        if self.collect_user_agent:
            context["user_agent"] = request.headers.get("user-agent", "")

        # Add API version if present
        api_version = request.headers.get("x-api-version")
        if api_version:
            context["api_version"] = api_version

        # Add authentication info if available
        auth_header = request.headers.get("authorization")
        if auth_header:
            context["has_auth"] = True
            if auth_header.lower().startswith("bearer"):
                context["auth_type"] = "bearer"
            elif auth_header.lower().startswith("basic"):
                context["auth_type"] = "basic"
            else:
                context["auth_type"] = "other"
        else:
            context["has_auth"] = False

        return context

    def _capture_response_metadata(
        self, response: Response, metrics: RequestMetrics
    ) -> None:
        """
        Capture metadata about the response without capturing the body.

        Args:
            response: The response object
            metrics: The metrics object to update
        """
        # Estimate response size without capturing body
        content_length = response.headers.get("content-length")
        if content_length:
            metrics.response_size = int(content_length)

        # Capture content type
        metrics.context["response_content_type"] = response.headers.get("content-type")

        # Handle specific response types
        if isinstance(response, StreamingResponse):
            metrics.context["response_type"] = "streaming"
        elif isinstance(response, JSONResponse):
            metrics.context["response_type"] = "json"
        else:
            metrics.context["response_type"] = response.__class__.__name__

        # Add caching headers if present
        cache_control = response.headers.get("cache-control")
        if cache_control:
            metrics.context["cache_control"] = cache_control

    def _classify_performance(self, duration: float) -> str:
        """
        Classify request performance based on duration.

        Args:
            duration: Request duration in seconds

        Returns:
            Performance classification string
        """
        duration_ms = duration * 1000
        if duration_ms < 100:
            return "fast"
        elif duration_ms < 500:
            return "normal"
        elif duration_ms < 1000:
            return "slow"
        else:
            return "very_slow"

    def _handle_http_exception(
        self, exc: HTTPException, metrics: RequestMetrics
    ) -> JSONResponse:
        """
        Handle HTTP exceptions and record metrics.

        Args:
            exc: The HTTP exception
            metrics: The metrics object

        Returns:
            JSONResponse with error details
        """
        # Record error metrics
        metrics.end_time = time.time()
        metrics.duration = metrics.end_time - metrics.start_time
        metrics.error = f"HTTPException: {exc.detail}"
        metrics.status_code = exc.status_code
        metrics.context["error_type"] = "http_exception"
        metrics.context["error_detail"] = str(exc.detail)

        # Add to metrics collector
        self.metrics_collector.add_metrics(metrics)

        # Log with appropriate level based on status code
        log_level = "warning" if exc.status_code < 500 else "error"
        getattr(logger, log_level)(
            f"HTTP exception: {exc.status_code} - {exc.detail}",
            request_id=metrics.context.get("request_id"),
            endpoint=metrics.endpoint,
            method=metrics.method,
        )

        # Return standard JSON response
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    def _handle_unhandled_exception(
        self, exc: Exception, metrics: RequestMetrics
    ) -> JSONResponse:
        """
        Handle unhandled exceptions and record metrics.

        Args:
            exc: The exception
            metrics: The metrics object

        Returns:
            JSONResponse with generic error message
        """
        # Record error metrics
        metrics.end_time = time.time()
        metrics.duration = metrics.end_time - metrics.start_time
        metrics.error = str(exc)
        metrics.status_code = 500
        metrics.context["error_type"] = exc.__class__.__name__

        if self.enable_detailed_errors:
            metrics.context["error_traceback"] = traceback.format_exc()

        # Add to metrics collector
        self.metrics_collector.add_metrics(metrics)

        # Log the error with context
        logger.error(
            f"Unhandled exception: {str(exc)}",
            exc_info=True,
            request_id=metrics.context.get("request_id"),
            endpoint=metrics.endpoint,
            method=metrics.method,
        )

        # Return generic error response
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred"},
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get metrics statistics."""
        return {
            "summary": self.metrics_collector.get_summary(),
            "endpoints": self.metrics_collector.get_endpoint_stats(),
            "methods": self.metrics_collector.get_method_stats(),
            "sampling_rate": self.sampling_rate,
            "exclude_paths": self.exclude_paths,
        }


# Utility functions for setting up metrics
def setup_metrics_middleware(
    app: FastAPI, metrics_collector: Optional[MetricsCollector] = None, **kwargs
) -> MetricsMiddleware:
    """
    Setup metrics middleware for a FastAPI application.

    Args:
        app: FastAPI application
        metrics_collector: Optional metrics collector instance
        **kwargs: Additional middleware configuration

    Returns:
        MetricsMiddleware: The configured middleware instance
    """
    if metrics_collector is None:
        metrics_collector = MetricsCollector()

    # Store metrics collector in app state for access by endpoints
    app.state.metrics = metrics_collector

    # Create and add middleware
    middleware = MetricsMiddleware(app, metrics_collector=metrics_collector, **kwargs)
    app.add_middleware(lambda app: middleware)

    logger.info("Metrics middleware configured and added to application")
    return middleware


def create_metrics_endpoint(app: FastAPI, path: str = "/metrics") -> None:
    """
    Create a metrics endpoint that exposes collected metrics.

    Args:
        app: FastAPI application
        path: Endpoint path for metrics
    """

    @app.get(path)
    async def get_metrics(
        summary_only: bool = False, recent_limit: int = 100, endpoint_limit: int = 20
    ) -> Dict[str, Any]:
        """
        Get application metrics.

        Args:
            summary_only: Return only summary statistics
            recent_limit: Number of recent metrics to include
            endpoint_limit: Number of top endpoints to include

        Returns:
            Dict containing metrics data
        """
        metrics_collector = getattr(app.state, "metrics", None)
        if not metrics_collector:
            return {"error": "Metrics collector not configured"}

        result = {
            "summary": metrics_collector.get_summary(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if not summary_only:
            result.update(
                {
                    "endpoints": metrics_collector.get_endpoint_stats(endpoint_limit),
                    "methods": metrics_collector.get_method_stats(),
                    "recent": metrics_collector.get_recent_metrics(recent_limit),
                }
            )

        return result

    logger.info(f"Metrics endpoint created at {path}")


# Legacy function-based middleware for backwards compatibility
async def metrics_middleware(request: Request, call_next: Callable) -> Response:
    """
    Legacy function-based middleware that tracks metrics for all API requests.

    This implementation is maintained for backwards compatibility.
    Consider using the MetricsMiddleware class for new projects.

    Args:
        request: The incoming request
        call_next: The next middleware or route handler

    Returns:
        Response: The HTTP response
    """
    path = request.url.path
    method = request.method

    # Skip metrics endpoints themselves to avoid recursion
    if path.startswith("/api/v1/metrics") or path.startswith("/metrics"):
        return await call_next(request)

    # Get request ID if available
    request_id = getattr(request.state, "request_id", None)

    # Get metrics collector from app state
    metrics_collector = getattr(request.app.state, "metrics", None)
    if not metrics_collector:
        # Create a default collector if none exists
        metrics_collector = MetricsCollector()
        request.app.state.metrics = metrics_collector

    # Create metrics object
    request_metrics = RequestMetrics(
        endpoint=path,
        method=method,
        start_time=time.time(),
        context={
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent", ""),
            "request_id": request_id,
        },
    )

    try:
        # Process the request
        response = await call_next(request)

        # Record metrics
        request_metrics.end_time = time.time()
        request_metrics.duration = request_metrics.end_time - request_metrics.start_time
        request_metrics.status_code = response.status_code

        # Estimate response size without capturing body
        content_length = response.headers.get("content-length")
        if content_length:
            request_metrics.response_size = int(content_length)

        # Add to metrics collector
        metrics_collector.add_metrics(request_metrics)

        return response

    except HTTPException as e:
        # Record error metrics
        request_metrics.end_time = time.time()
        request_metrics.duration = request_metrics.end_time - request_metrics.start_time
        request_metrics.error = str(e)
        request_metrics.status_code = e.status_code
        metrics_collector.add_metrics(request_metrics)

        # Log the error with context
        logger.warning(
            f"HTTP exception: {e.status_code} - {e.detail}", request_id=request_id
        )

        # Return appropriate error response
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})

    except Exception as e:
        # Record error metrics
        request_metrics.end_time = time.time()
        request_metrics.duration = request_metrics.end_time - request_metrics.start_time
        request_metrics.error = str(e)
        request_metrics.status_code = 500
        metrics_collector.add_metrics(request_metrics)

        # Log the error with context
        logger.error(f"Request error: {str(e)}", exc_info=True, request_id=request_id)

        # Generic server error for unhandled exceptions
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred"},
        )


# Export all important components
__all__ = [
    "MetricsMiddleware",
    "MetricsCollector",
    "RequestMetrics",
    "MetricType",
    "setup_metrics_middleware",
    "create_metrics_endpoint",
    "metrics_middleware",  # Legacy
]
