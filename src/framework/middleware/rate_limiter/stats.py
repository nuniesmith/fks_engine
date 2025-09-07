import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RateLimitStats:
    """
    Statistics for rate limiter monitoring.

    This class tracks various metrics about rate limiter usage including:
    - Request counts (total, allowed, throttled, rejected)
    - Wait times (total, average, maximum)
    - Time series data for requests per minute
    - Peak rate information
    """

    # Basic counters
    total_requests: int = 0
    allowed_requests: int = 0
    throttled_requests: int = 0
    rejected_requests: int = 0

    # Wait time tracking
    total_wait_time_ms: float = 0
    max_wait_time_ms: float = 0
    last_wait_time_ms: float = 0

    # Time series data (minute buckets)
    requests_per_minute: List[Tuple[int, int]] = field(default_factory=list)

    # Creation timestamp
    created_at: float = field(default_factory=time.time)

    # Peak rate tracking
    peak_minute_rate: int = 0
    peak_minute_timestamp: Optional[int] = None

    # Recent activity tracking
    last_request_time: float = field(default_factory=time.time)

    def record_request(
        self, allowed: bool, throttled: bool = False, wait_time_ms: float = 0
    ) -> None:
        """
        Record a request in the statistics.

        Args:
            allowed: Whether the request was allowed
            throttled: Whether the request was throttled (slowed down)
            wait_time_ms: Wait time in milliseconds
        """
        self.total_requests += 1

        # Update request status counters
        if allowed:
            self.allowed_requests += 1
        else:
            self.rejected_requests += 1

        if throttled:
            self.throttled_requests += 1

        # Track wait times
        if wait_time_ms > 0:
            self.total_wait_time_ms += wait_time_ms
            self.max_wait_time_ms = max(self.max_wait_time_ms, wait_time_ms)
            self.last_wait_time_ms = wait_time_ms

        # Update last request time
        self.last_request_time = time.time()

        # Record in time series (1-minute buckets)
        now = int(time.time())
        minute_bucket = now - (now % 60)

        # Add a new minute or update the current one
        if (
            not self.requests_per_minute
            or self.requests_per_minute[-1][0] != minute_bucket
        ):
            self.requests_per_minute.append((minute_bucket, 1))
            # Keep only last 60 minutes
            if len(self.requests_per_minute) > 60:
                self.requests_per_minute = self.requests_per_minute[-60:]
        else:
            current_count = self.requests_per_minute[-1][1] + 1
            self.requests_per_minute[-1] = (minute_bucket, current_count)

            # Update peak rate if necessary
            if current_count > self.peak_minute_rate:
                self.peak_minute_rate = current_count
                self.peak_minute_timestamp = minute_bucket

    def get_current_rate(self) -> float:
        """
        Get the current request rate (requests per second) based on recent data.

        Returns:
            Current request rate as requests per second
        """
        if not self.requests_per_minute:
            return 0.0

        now = int(time.time())
        minute_bucket = now - (now % 60)

        # If we have data for the current minute
        if (
            self.requests_per_minute
            and self.requests_per_minute[-1][0] == minute_bucket
        ):
            # Calculate seconds elapsed in current minute
            seconds_elapsed = now % 60 or 60  # If 0, use 60 (full minute)
            return self.requests_per_minute[-1][1] / seconds_elapsed

        # No data for current minute, return 0
        return 0.0

    def get_average_rate(self) -> float:
        """
        Get the average request rate over the recorded period.

        Returns:
            Average request rate as requests per second
        """
        uptime = time.time() - self.created_at
        if uptime <= 0:
            return 0.0
        return self.total_requests / uptime

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert statistics to a dictionary.

        Returns:
            Dictionary with all statistics
        """
        # Calculate rate metrics
        avg_wait_time = 0
        if self.allowed_requests > 0:
            avg_wait_time = self.total_wait_time_ms / self.allowed_requests

        # Calculate rates
        current_rate = self.get_current_rate()
        avg_rate = self.get_average_rate()

        # Format timestamp for peak rate
        peak_time_str = ""
        if self.peak_minute_timestamp:
            peak_time = datetime.fromtimestamp(self.peak_minute_timestamp)
            peak_time_str = peak_time.strftime("%Y-%m-%d %H:%M:%S")

        return {
            # Request counts
            "total_requests": self.total_requests,
            "allowed_requests": self.allowed_requests,
            "throttled_requests": self.throttled_requests,
            "rejected_requests": self.rejected_requests,
            # Request rates
            "rejection_rate": (
                f"{(self.rejected_requests / max(1, self.total_requests)) * 100:.2f}%"
            ),
            "throttle_rate": (
                f"{(self.throttled_requests / max(1, self.total_requests)) * 100:.2f}%"
            ),
            "current_rate_per_second": f"{current_rate:.2f}",
            "average_rate_per_second": f"{avg_rate:.2f}",
            # Wait time metrics
            "avg_wait_time_ms": f"{avg_wait_time:.2f}",
            "max_wait_time_ms": self.max_wait_time_ms,
            "last_wait_time_ms": self.last_wait_time_ms,
            # Peak metrics
            "peak_requests_per_minute": self.peak_minute_rate,
            "peak_time": peak_time_str,
            # Time metrics
            "uptime_seconds": time.time() - self.created_at,
            "last_request_ago_seconds": time.time() - self.last_request_time,
            # Time series data (recent activity)
            "requests_per_minute": self.requests_per_minute[-10:],  # Last 10 minutes
        }

    def reset(self) -> None:
        """Reset all statistics to initial values."""
        self.total_requests = 0
        self.allowed_requests = 0
        self.throttled_requests = 0
        self.rejected_requests = 0
        self.total_wait_time_ms = 0
        self.max_wait_time_ms = 0
        self.last_wait_time_ms = 0
        self.requests_per_minute = []
        self.created_at = time.time()
        self.peak_minute_rate = 0
        self.peak_minute_timestamp = None
        self.last_request_time = time.time()
