"""
timing middleware for measuring request performance.

This module provides a middleware for measuring and reporting the time
taken to process each request, with advanced classification, statistical
analysis, and monitoring capabilities.
"""

import statistics
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from fastapi import FastAPI, Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class TimingStats:
    """Simple statistics collector for request timing."""

    def __init__(self, max_samples: int = 1000):
        """
        Initialize statistics.

        Args:
            max_samples: Maximum number of samples to keep
        """
        self.samples = deque(maxlen=max_samples)
        self.lock = Lock()
        self.count = 0
        self.total_time = 0
        self.min_time = float("inf")
        self.max_time = 0

    def add_sample(self, time_ms: float) -> None:
        """
        Add a timing sample.

        Args:
            time_ms: Processing time in milliseconds
        """
        with self.lock:
            self.samples.append(time_ms)
            self.count += 1
            self.total_time += time_ms
            self.min_time = min(self.min_time, time_ms)
            self.max_time = max(self.max_time, time_ms)

    def get_stats(self) -> Dict[str, float]:
        """
        Get timing statistics.

        Returns:
            Dict: Timing statistics
        """
        with self.lock:
            if not self.samples:
                return {"count": 0, "avg_ms": 0, "min_ms": 0, "max_ms": 0, "p95_ms": 0}

            samples_list = list(self.samples)

            # Calculate percentiles
            try:
                p95 = statistics.quantiles(samples_list, n=20)[18]
            except (IndexError, ValueError):
                p95 = self.max_time

            return {
                "count": self.count,
                "avg_ms": self.total_time / self.count,
                "min_ms": self.min_time,
                "max_ms": self.max_time,
                "p95_ms": p95,
            }


class TimingMiddleware(BaseHTTPMiddleware):
    """
    middleware that measures and reports request processing time.

    This middleware calculates the time taken to process each request and
    provides advanced classification, statistical analysis, and monitoring
    capabilities for performance optimization.
    """

    def __init__(
        self,
        app: ASGIApp,
        header_name: str = "X-Process-Time",
        include_in_response: bool = True,
        log_timing: bool = True,
        slow_threshold_ms: Optional[float] = 500,
        exclude_paths: Optional[List[str]] = None,
        collect_stats: bool = True,
        max_stats_samples: int = 1000,
        custom_thresholds: Optional[Dict[str, float]] = None,
        classification_header: bool = False,
        classification_header_name: str = "X-Request-Classification",
    ):
        """
        Initialize timing middleware.

        Args:
            app: ASGI application
            header_name: Name of header to add timing information to
            include_in_response: Whether to include timing in response headers
            log_timing: Whether to log timing information
            slow_threshold_ms: Threshold in ms for logging slow requests
            exclude_paths: List of path prefixes to exclude from timing
            collect_stats: Whether to collect timing statistics
            max_stats_samples: Maximum number of samples to keep for statistics
            custom_thresholds: Custom thresholds for specific routes
            classification_header: Whether to include classification header
            classification_header_name: Name of classification header
        """
        super().__init__(app)
        self.header_name = header_name
        self.include_in_response = include_in_response
        self.log_timing = log_timing
        self.slow_threshold_ms = slow_threshold_ms
        self.exclude_paths = exclude_paths or []
        self.collect_stats = collect_stats
        self.custom_thresholds = custom_thresholds or {}
        self.classification_header = classification_header
        self.classification_header_name = classification_header_name

        # Initialize statistics collectors
        if collect_stats:
            self.global_stats = TimingStats(max_stats_samples)
            self.route_stats = defaultdict(lambda: TimingStats(max_stats_samples))
            self.method_stats = defaultdict(lambda: TimingStats(max_stats_samples))

        logger.debug(
            f"Timing middleware initialized with slow threshold: {slow_threshold_ms}ms"
        )

    def _should_exclude(self, path: str) -> bool:
        """
        Check if a path should be excluded from timing.

        Args:
            path: Request path

        Returns:
            bool: True if the path should be excluded
        """
        return any(path.startswith(excluded) for excluded in self.exclude_paths)

    def _get_slow_threshold(self, path: str) -> float:
        """
        Get the slow threshold for a specific path.

        Args:
            path: Request path

        Returns:
            float: Slow threshold in milliseconds
        """
        # Check for exact match
        if path in self.custom_thresholds:
            return self.custom_thresholds[path]

        # Check for prefix match
        for prefix, threshold in self.custom_thresholds.items():
            if path.startswith(prefix):
                return threshold

        # Use default threshold
        return (
            self.slow_threshold_ms
            if self.slow_threshold_ms is not None
            else float("inf")
        )

    def _classify_request(self, time_ms: float) -> str:
        """
        Classify a request based on its processing time.

        Args:
            time_ms: Processing time in milliseconds

        Returns:
            str: Classification (fast, normal, slow, very_slow, extremely_slow)
        """
        if time_ms < 100:
            return "fast"
        elif time_ms < 300:
            return "normal"
        elif time_ms < 1000:
            return "slow"
        elif time_ms < 3000:
            return "very_slow"
        else:
            return "extremely_slow"

    def _get_log_level(self, time_ms: float, threshold: float) -> str:
        """
        Get the appropriate log level based on request processing time.

        Args:
            time_ms: Processing time in milliseconds
            threshold: Slow threshold in milliseconds

        Returns:
            str: Log level (debug, info, warning, error)
        """
        classification = self._classify_request(time_ms)

        if classification in ["fast", "normal"]:
            return "debug"
        elif classification == "slow":
            # Use warning level if it exceeds the threshold
            return "warning" if time_ms > threshold else "info"
        elif classification == "very_slow":
            return "warning"
        else:
            return "error"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process the request and measure timing.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response: The HTTP response
        """
        # Skip timing for excluded paths
        if self._should_exclude(request.url.path):
            return await call_next(request)

        # Get request ID for context if available
        request_id = getattr(request.state, "request_id", None)

        # Start timing
        start_time = time.time()

        try:
            # Process the request
            response = await call_next(request)

            # Calculate processing time
            process_time = time.time() - start_time
            process_time_ms = process_time * 1000

            # Classify the request
            classification = self._classify_request(process_time_ms)

            # Add timing to request state for other middleware
            request.state.process_time = process_time
            request.state.process_time_ms = process_time_ms
            request.state.request_classification = classification

            # Add headers if configured
            if self.include_in_response:
                response.headers[self.header_name] = f"{process_time_ms:.2f}"

                if self.classification_header:
                    response.headers[self.classification_header_name] = classification

            # Collect statistics if enabled
            if self.collect_stats:
                self.global_stats.add_sample(process_time_ms)
                self.route_stats[request.url.path].add_sample(process_time_ms)
                self.method_stats[request.method].add_sample(process_time_ms)

            # Log timing information if configured
            if self.log_timing:
                # Create log context
                log_context = {
                    "process_time_ms": process_time_ms,
                    "classification": classification,
                    "status_code": response.status_code,
                }

                # Add request ID if available
                if request_id:
                    log_context["request_id"] = request_id

                # Get path-specific slow threshold
                slow_threshold = self._get_slow_threshold(request.url.path)

                # Determine if this is a slow request
                is_slow = slow_threshold and process_time_ms > slow_threshold

                # Determine log level
                log_level = self._get_log_level(process_time_ms, slow_threshold)

                # Construct log message
                log_message = (
                    f"Request timing: {request.method} {request.url.path} - "
                    f"{process_time_ms:.2f}ms ({classification})"
                )

                # Log at appropriate level
                if is_slow and log_level == "info":
                    log_level = "warning"

                getattr(logger, log_level)(log_message, **log_context)

            return response

        except Exception as e:
            # Still log timing for failed requests
            process_time = time.time() - start_time
            process_time_ms = process_time * 1000

            # Classify the request
            classification = self._classify_request(process_time_ms)

            # Create log context
            log_context = {
                "process_time_ms": process_time_ms,
                "classification": classification,
                "error": str(e),
                "error_type": e.__class__.__name__,
            }

            # Add request ID if available
            if request_id:
                log_context["request_id"] = request_id

            # Log failed request timing
            logger.error(
                f"Failed request timing: {request.method} {request.url.path} - {process_time_ms:.2f}ms ({classification})",
                **log_context,
            )

            # Re-raise the exception
            raise

    def get_stats(self) -> Dict[str, Any]:
        """
        Get timing statistics.

        Returns:
            Dict: Timing statistics
        """
        if not self.collect_stats:
            return {"stats_collection_disabled": True}

        # Get global stats
        stats: Dict[str, Any] = {"global": self.global_stats.get_stats()}

        # Get method stats
        method_stats = {}
        for method, collector in self.method_stats.items():
            method_stats[method] = collector.get_stats()
        stats["by_method"] = method_stats

        # Get route stats
        route_stats = {}
        for route, collector in self.route_stats.items():
            route_stats[route] = collector.get_stats()
        stats["by_route"] = route_stats

        # Add slow routes (top 5)
        slow_routes = []
        for route, route_collector in self.route_stats.items():
            route_stats = route_collector.get_stats()
            if route_stats["count"] > 0:
                slow_routes.append(
                    {
                        "route": route,
                        "avg_ms": route_stats["avg_ms"],
                        "count": route_stats["count"],
                        "p95_ms": route_stats["p95_ms"],
                    }
                )

        # Sort by average time (descending)
        slow_routes.sort(key=lambda x: x["avg_ms"], reverse=True)

        # Take top 5
        stats["slow_routes"] = slow_routes[:5]

        return stats

    def reset_stats(self) -> None:
        """Reset all collected statistics."""
        if self.collect_stats:
            self.global_stats = TimingStats()
            self.route_stats.clear()
            self.method_stats.clear()


def get_request_timing(request: Request) -> Dict[str, Any]:
    """
    Get timing information from a request.

    Args:
        request: FastAPI request

    Returns:
        Dict: Timing information
    """
    return {
        "process_time": getattr(request.state, "process_time", None),
        "process_time_ms": getattr(request.state, "process_time_ms", None),
        "classification": getattr(request.state, "request_classification", None),
    }


def get_timing_middleware(app: FastAPI) -> Optional[TimingMiddleware]:
    """
    Get the TimingMiddleware instance from a FastAPI application.

    Args:
        app: FastAPI application

    Returns:
        Optional[TimingMiddleware]: TimingMiddleware instance if found
    """
    for middleware in app.user_middleware:
        if hasattr(middleware, "cls") and isinstance(middleware.cls, TimingMiddleware):
            return middleware.cls
    return None


def setup_timing_middleware(
    app: FastAPI,
    settings: Any = None,
) -> TimingMiddleware:
    """
    Set up timing middleware for a FastAPI application.

    Args:
        app: FastAPI application
        settings: Application settings

    Returns:
        TimingMiddleware: The initialized middleware instance
    """
    # Extract settings with defaults
    header_name = getattr(settings, "TIMING_HEADER", "X-Process-Time")
    include_in_response = getattr(settings, "INCLUDE_TIMING_IN_RESPONSE", True)
    log_timing = getattr(settings, "TIMING_LOG_ENABLED", True)
    slow_threshold_ms = getattr(settings, "TIMING_SLOW_THRESHOLD_MS", 500)
    exclude_paths = getattr(settings, "TIMING_EXCLUDE_PATHS", [])
    collect_stats = getattr(settings, "TIMING_COLLECT_STATS", True)
    classification_header = getattr(settings, "TIMING_CLASSIFICATION_HEADER", False)

    # Create custom thresholds from settings if available
    custom_thresholds = {}
    if (
        hasattr(settings, "TIMING_ROUTE_THRESHOLDS")
        and settings.TIMING_ROUTE_THRESHOLDS
    ):
        custom_thresholds = settings.TIMING_ROUTE_THRESHOLDS

    # Initialize the middleware
    middleware = TimingMiddleware(
        app,
        header_name=header_name,
        include_in_response=include_in_response,
        log_timing=log_timing,
        slow_threshold_ms=slow_threshold_ms,
        exclude_paths=exclude_paths,
        collect_stats=collect_stats,
        custom_thresholds=custom_thresholds,
        classification_header=classification_header,
    )

    # Add the middleware to the application
    app.add_middleware(lambda app: middleware)

    logger.info(
        f"Timing middleware configured with slow threshold: {slow_threshold_ms}ms, "
        f"header: {header_name}, statistics collection: {collect_stats}"
    )

    return middleware
