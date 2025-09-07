import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TypedDict


class TimeWindow(TypedDict):
    """Type for a time window of metrics."""

    start_time: float
    end_time: float
    requests: int
    successes: int
    failures: int
    timeouts: int
    rejections: int


@dataclass
class CircuitMetrics:
    """
    Comprehensive metrics for circuit breaker monitoring and analysis.

    Collects detailed statistics about circuit breaker performance including
    request counts, success/failure rates, response times, and state changes.
    Provides methods for analyzing trends and generating reports.
    """

    # Basic request counters
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rejected_requests: int = 0
    timeout_requests: int = 0

    # Response time tracking (in milliseconds)
    total_response_time_ms: float = 0
    min_response_time_ms: float = float("inf")
    max_response_time_ms: float = 0

    # State change history
    state_changes: List[Tuple[float, str]] = field(default_factory=list)

    # Time-based metrics for trend analysis
    created_at: float = field(default_factory=time.time)
    last_request_time: float = 0
    last_success_time: float = 0
    last_failure_time: float = 0

    # Time window metrics for trend analysis (1-minute windows)
    time_windows: List[TimeWindow] = field(default_factory=list)
    current_window_start: float = field(default_factory=time.time)
    window_size_seconds: int = 60
    max_windows: int = 60  # Keep up to 60 windows (1 hour with 1-minute windows)

    def record_request(
        self,
        success: bool = True,
        response_time_ms: float = 0,
        timeout: bool = False,
        rejected: bool = False,
    ) -> None:
        """
        Record a request in the metrics.

        Args:
            success: Whether the request was successful
            response_time_ms: Response time in milliseconds
            timeout: Whether the request timed out
            rejected: Whether the request was rejected by the circuit breaker
        """
        now = time.time()
        self.total_requests += 1
        self.last_request_time = now

        # Update request type counters
        if success:
            self.successful_requests += 1
            self.last_success_time = now
        else:
            self.failed_requests += 1
            self.last_failure_time = now

        if timeout:
            self.timeout_requests += 1

        if rejected:
            self.rejected_requests += 1

        # Update response time stats if provided
        if response_time_ms > 0:
            self.total_response_time_ms += response_time_ms
            self.min_response_time_ms = min(self.min_response_time_ms, response_time_ms)
            self.max_response_time_ms = max(self.max_response_time_ms, response_time_ms)

        # Update time window metrics
        self._update_time_windows(now, success, timeout, rejected)

    def record_state_change(self, from_state: str, to_state: str) -> None:
        """
        Record a state change in the metrics.

        Args:
            from_state: Previous state
            to_state: New state
        """
        now = time.time()
        self.state_changes.append((now, f"{from_state} -> {to_state}"))

    def _update_time_windows(
        self, timestamp: float, success: bool, timeout: bool, rejected: bool
    ) -> None:
        """
        Update time window metrics.

        Args:
            timestamp: Current timestamp
            success: Whether the request was successful
            timeout: Whether the request timed out
            rejected: Whether the request was rejected
        """
        # Check if we need to create a new window
        window_end = self.current_window_start + self.window_size_seconds

        # If the timestamp is beyond the current window, create a new window
        if timestamp >= window_end:
            # Create new windows until we catch up to the current time
            while timestamp >= window_end:
                self.current_window_start = window_end
                window_end = self.current_window_start + self.window_size_seconds

                # Create a new empty window
                self.time_windows.append(
                    {
                        "start_time": self.current_window_start,
                        "end_time": window_end,
                        "requests": 0,
                        "successes": 0,
                        "failures": 0,
                        "timeouts": 0,
                        "rejections": 0,
                    }
                )

                # Maintain maximum window count
                if len(self.time_windows) > self.max_windows:
                    self.time_windows = self.time_windows[-self.max_windows :]

        # Ensure we have at least one window
        if not self.time_windows:
            self.time_windows.append(
                {
                    "start_time": self.current_window_start,
                    "end_time": window_end,
                    "requests": 0,
                    "successes": 0,
                    "failures": 0,
                    "timeouts": 0,
                    "rejections": 0,
                }
            )

        # Update the current window
        current_window = self.time_windows[-1]
        current_window["requests"] += 1

        if success:
            current_window["successes"] += 1
        else:
            current_window["failures"] += 1

        if timeout:
            current_window["timeouts"] += 1

        if rejected:
            current_window["rejections"] += 1

    def get_success_rate(self, window_minutes: int = 0) -> float:
        """
        Get the success rate as a float between 0 and 1.

        Args:
            window_minutes: Number of minutes to look back (0 for all-time)

        Returns:
            Success rate as a float between 0 and 1
        """
        if window_minutes > 0:
            # Calculate success rate for the specified time window
            successes, total = self.get_window_metrics(window_minutes)
            return successes / max(1, total)
        else:
            # Calculate all-time success rate
            return self.successful_requests / max(1, self.total_requests)

    def get_window_metrics(self, window_minutes: int) -> Tuple[int, int]:
        """
        Get success and total request counts for a specific time window.

        Args:
            window_minutes: Number of minutes to look back

        Returns:
            Tuple of (successful_requests, total_requests)
        """
        # Convert minutes to seconds
        window_seconds = window_minutes * 60

        # Get current time
        now = time.time()

        # Calculate window start time
        window_start = now - window_seconds

        # Sum metrics from windows that fall within our time range
        successes = 0
        total = 0

        for window in self.time_windows:
            # Skip windows that end before our window starts
            if window["end_time"] < window_start:
                continue

            # Include windows that overlap with our time range
            successes += window["successes"]
            total += window["requests"]

        return successes, total

    def get_error_rate(self, window_minutes: int = 0) -> float:
        """
        Get the error rate as a float between 0 and 1.

        Args:
            window_minutes: Number of minutes to look back (0 for all-time)

        Returns:
            Error rate as a float between 0 and 1
        """
        return 1.0 - self.get_success_rate(window_minutes)

    def get_avg_response_time(self) -> float:
        """
        Get the average response time in milliseconds.

        Returns:
            Average response time or 0 if no requests have been recorded
        """
        if self.successful_requests > 0:
            return self.total_response_time_ms / self.successful_requests
        return 0

    def get_recovery_time(self) -> Optional[float]:
        """
        Calculate average recovery time (time from open to closed state).

        Returns:
            Average recovery time in seconds or None if not applicable
        """
        # Find pairs of state changes that match our pattern
        recovery_times = []
        last_open_time = None

        for timestamp, change in self.state_changes:
            if change == "closed -> open":
                last_open_time = timestamp
            elif change == "half_open -> closed" and last_open_time is not None:
                recovery_time = timestamp - last_open_time
                recovery_times.append(recovery_time)
                last_open_time = None

        # Calculate average recovery time
        if recovery_times:
            return sum(recovery_times) / len(recovery_times)
        return None

    def get_trends(self, window_count: int = 5) -> Dict[str, List[float]]:
        """
        Get trending metrics over recent time windows.

        Args:
            window_count: Number of recent windows to include

        Returns:
            Dictionary with trend data for key metrics
        """
        # Get the most recent windows
        recent_windows = self.time_windows[-window_count:] if self.time_windows else []

        # Initialize trend data
        trends = {
            "timestamps": [],
            "request_rate": [],
            "success_rate": [],
            "failure_rate": [],
            "rejection_rate": [],
        }

        # Fill trend data from windows
        for window in recent_windows:
            # Use the middle of the window as the timestamp
            timestamp = (window["start_time"] + window["end_time"]) / 2
            trends["timestamps"].append(timestamp)

            # Request rate per minute
            request_rate = window["requests"] / (self.window_size_seconds / 60)
            trends["request_rate"].append(request_rate)

            # Success rate
            total = max(1, window["requests"])
            trends["success_rate"].append(window["successes"] / total)

            # Failure rate
            trends["failure_rate"].append(window["failures"] / total)

            # Rejection rate
            trends["rejection_rate"].append(window["rejections"] / total)

        return trends

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert metrics to a comprehensive dictionary for reporting.

        Returns:
            Dictionary with all metrics data
        """
        # Calculate derived metrics
        success_rate = self.get_success_rate()
        avg_response_time = self.get_avg_response_time()
        uptime_seconds = time.time() - self.created_at
        recovery_time = self.get_recovery_time()

        # Get recent state changes
        recent_state_changes = [(ts, state) for ts, state in self.state_changes[-10:]]
        last_state_change = self.state_changes[-1] if self.state_changes else None

        # Format timestamps as readable strings
        formatted_state_changes = [
            (datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"), state)
            for ts, state in recent_state_changes
        ]

        formatted_last_change = None
        if last_state_change:
            formatted_last_change = (
                datetime.fromtimestamp(last_state_change[0]).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                last_state_change[1],
            )

        # Build the complete metrics dictionary
        return {
            # Basic request metrics
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "rejected_requests": self.rejected_requests,
            "timeout_requests": self.timeout_requests,
            # Derived metrics
            "success_rate": f"{success_rate:.2%}",
            "error_rate": f"{(1.0 - success_rate):.2%}",
            "rejection_rate": (
                f"{(self.rejected_requests / max(1, self.total_requests)):.2%}"
            ),
            # Response time metrics
            "avg_response_time_ms": round(avg_response_time, 2),
            "min_response_time_ms": (
                round(self.min_response_time_ms, 2)
                if self.min_response_time_ms != float("inf")
                else 0
            ),
            "max_response_time_ms": round(self.max_response_time_ms, 2),
            # Recovery metrics
            "avg_recovery_time_seconds": (
                round(recovery_time, 2) if recovery_time else None
            ),
            # State change history
            "state_changes": formatted_state_changes,
            "last_state_change": formatted_last_change,
            "state_change_count": len(self.state_changes),
            # Time window metrics (last 5 minutes)
            "recent_success_rate": f"{self.get_success_rate(5):.2%}",
            "recent_error_rate": f"{self.get_error_rate(5):.2%}",
            # System metrics
            "uptime_seconds": round(uptime_seconds, 1),
            "uptime_formatted": self._format_duration(uptime_seconds),
        }

    def to_prometheus_format(self) -> List[str]:
        """
        Convert metrics to Prometheus exposition format.

        Returns:
            List of strings in Prometheus exposition format
        """
        metrics = []
        prefix = "circuit_breaker"

        # Basic counters
        metrics.append(f"# HELP {prefix}_requests_total Total number of requests")
        metrics.append(f"# TYPE {prefix}_requests_total counter")
        metrics.append(f"{prefix}_requests_total {self.total_requests}")

        metrics.append(
            f"# HELP {prefix}_successful_requests_total Total number of successful requests"
        )
        metrics.append(f"# TYPE {prefix}_successful_requests_total counter")
        metrics.append(f"{prefix}_successful_requests_total {self.successful_requests}")

        metrics.append(
            f"# HELP {prefix}_failed_requests_total Total number of failed requests"
        )
        metrics.append(f"# TYPE {prefix}_failed_requests_total counter")
        metrics.append(f"{prefix}_failed_requests_total {self.failed_requests}")

        metrics.append(
            f"# HELP {prefix}_rejected_requests_total Total number of rejected requests"
        )
        metrics.append(f"# TYPE {prefix}_rejected_requests_total counter")
        metrics.append(f"{prefix}_rejected_requests_total {self.rejected_requests}")

        metrics.append(
            f"# HELP {prefix}_timeout_requests_total Total number of timed out requests"
        )
        metrics.append(f"# TYPE {prefix}_timeout_requests_total counter")
        metrics.append(f"{prefix}_timeout_requests_total {self.timeout_requests}")

        # Response time metrics
        metrics.append(
            f"# HELP {prefix}_response_time_ms Response time in milliseconds"
        )
        metrics.append(f"# TYPE {prefix}_response_time_ms gauge")
        metrics.append(
            f'{prefix}_response_time_ms {{type="avg"}} {self.get_avg_response_time()}'
        )

        if self.min_response_time_ms != float("inf"):
            metrics.append(
                f'{prefix}_response_time_ms {{type="min"}} {self.min_response_time_ms}'
            )
        else:
            metrics.append(f'{prefix}_response_time_ms {{type="min"}} 0')

        metrics.append(
            f'{prefix}_response_time_ms {{type="max"}} {self.max_response_time_ms}'
        )

        # State change metrics
        metrics.append(
            f"# HELP {prefix}_state_changes_total Total number of state changes"
        )
        metrics.append(f"# TYPE {prefix}_state_changes_total counter")
        metrics.append(f"{prefix}_state_changes_total {len(self.state_changes)}")

        # Success rate
        metrics.append(f"# HELP {prefix}_success_rate Success rate")
        metrics.append(f"# TYPE {prefix}_success_rate gauge")
        metrics.append(f"{prefix}_success_rate {self.get_success_rate()}")

        # Recent success rate
        metrics.append(
            f"# HELP {prefix}_recent_success_rate Success rate in last 5 minutes"
        )
        metrics.append(f"# TYPE {prefix}_recent_success_rate gauge")
        metrics.append(f"{prefix}_recent_success_rate {self.get_success_rate(5)}")

        return metrics

    def reset(self) -> None:
        """Reset all metrics to initial values."""
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.rejected_requests = 0
        self.timeout_requests = 0

        self.total_response_time_ms = 0
        self.min_response_time_ms = float("inf")
        self.max_response_time_ms = 0

        self.state_changes = []

        self.created_at = time.time()
        self.last_request_time = 0
        self.last_success_time = 0
        self.last_failure_time = 0

        self.time_windows = []
        self.current_window_start = time.time()

    def _format_duration(self, seconds: float) -> str:
        """
        Format duration in seconds to a human-readable string.

        Args:
            seconds: Duration in seconds

        Returns:
            Formatted duration string
        """
        minutes, seconds = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        components = []
        if days > 0:
            components.append(f"{days}d")
        if hours > 0 or days > 0:
            components.append(f"{hours}h")
        if minutes > 0 or hours > 0 or days > 0:
            components.append(f"{minutes}m")
        components.append(f"{seconds}s")

        return " ".join(components)
