from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CircuitBreakerConfig:
    """
    Configuration parameters for the CircuitBreaker.
    """

    failure_threshold: int = 5  # Number of failures before opening circuit
    reset_timeout: float = 60.0  # Seconds before trying again (half-open)
    success_threshold: int = 2  # Successes needed to close circuit again
    timeout: float = 10.0  # Request timeout in seconds
    excluded_exceptions: List[type] = field(
        default_factory=list
    )  # Exceptions that don't count as failures
    use_persistent_storage: bool = False  # Whether to persist state to external storage
    track_metrics: bool = True  # Whether to track performance metrics
    max_state_history: int = 100  # Maximum number of state changes to track
    log_level_state_change: str = "INFO"  # Log level for state changes
    log_level_failure: str = "ERROR"  # Log level for failures
    storage_provider: Optional[str] = (
        None  # Storage provider type ("memory", "redis", etc.)
    )

    def __post_init__(self):
        """Validate configuration parameters."""
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if self.reset_timeout <= 0:
            raise ValueError("reset_timeout must be positive")
        if self.success_threshold <= 0:
            raise ValueError("success_threshold must be positive")
        if self.timeout < 0:  # Allow 0 for "no timeout"
            raise ValueError("timeout must be non-negative")
        if self.max_state_history <= 0:
            raise ValueError("max_state_history must be positive")

        # Validate log levels
        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level_state_change not in valid_log_levels:
            raise ValueError(
                f"log_level_state_change must be one of {valid_log_levels}"
            )
        if self.log_level_failure not in valid_log_levels:
            raise ValueError(f"log_level_failure must be one of {valid_log_levels}")

        # Validate storage provider if specified
        if self.storage_provider and self.storage_provider not in {"memory", "redis"}:
            raise ValueError("storage_provider must be one of: memory, redis")
