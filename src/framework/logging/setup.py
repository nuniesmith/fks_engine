"""
Logging Setup and Configuration Module.

This module provides comprehensive logging configuration for the framework,
including structured logging, multiple output targets, log rotation,
performance monitoring, and environment-specific configurations.
"""

import json
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

try:
    from loguru import logger

    LOGURU_AVAILABLE = True
except ImportError:
    import logging

    logger = logging.getLogger("framework.logging")
    LOGURU_AVAILABLE = False

# Default configuration
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
DEFAULT_LOG_DIR = "logs"
DEFAULT_MAX_FILE_SIZE = "100 MB"
DEFAULT_RETENTION = "30 days"
DEFAULT_ROTATION = "1 day"

# Environment-specific configurations
ENVIRONMENT_CONFIGS = {
    "development": {
        "level": "DEBUG",
        "console": True,
        "file": True,
        "structured": False,
        "colorize": True,
        "backtrace": True,
        "diagnose": True,
    },
    "staging": {
        "level": "INFO",
        "console": True,
        "file": True,
        "structured": True,
        "colorize": False,
        "backtrace": True,
        "diagnose": False,
    },
    "production": {
        "level": "WARNING",
        "console": False,
        "file": True,
        "structured": True,
        "colorize": False,
        "backtrace": False,
        "diagnose": False,
    },
}


@dataclass
class LogConfig:
    """Configuration for logging setup."""

    level: str = DEFAULT_LOG_LEVEL
    console: bool = True
    file: bool = True
    structured: bool = False
    colorize: bool = True
    backtrace: bool = True
    diagnose: bool = True
    log_dir: str = DEFAULT_LOG_DIR
    max_file_size: str = DEFAULT_MAX_FILE_SIZE
    retention: str = DEFAULT_RETENTION
    rotation: str = DEFAULT_ROTATION
    format_string: Optional[str] = None
    json_logs: bool = False
    request_id_header: str = "X-Request-ID"
    correlation_id_header: str = "X-Correlation-ID"
    enable_performance_logging: bool = True
    enable_audit_logging: bool = True
    enable_security_logging: bool = True
    extra_fields: Dict[str, Any] = None

    def __post_init__(self):
        if self.extra_fields is None:
            self.extra_fields = {}


class RequestContext:
    """Thread-local context for request tracking."""

    def __init__(self):
        self._local = threading.local()

    def set_request_id(self, request_id: str):
        """Set the current request ID."""
        self._local.request_id = request_id

    def get_request_id(self) -> Optional[str]:
        """Get the current request ID."""
        return getattr(self._local, "request_id", None)

    def set_correlation_id(self, correlation_id: str):
        """Set the current correlation ID."""
        self._local.correlation_id = correlation_id

    def get_correlation_id(self) -> Optional[str]:
        """Get the current correlation ID."""
        return getattr(self._local, "correlation_id", None)

    def set_user_id(self, user_id: str):
        """Set the current user ID."""
        self._local.user_id = user_id

    def get_user_id(self) -> Optional[str]:
        """Get the current user ID."""
        return getattr(self._local, "user_id", None)

    def set_session_id(self, session_id: str):
        """Set the current session ID."""
        self._local.session_id = session_id

    def get_session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return getattr(self._local, "session_id", None)

    def clear(self):
        """Clear all context."""
        for attr in ["request_id", "correlation_id", "user_id", "session_id"]:
            if hasattr(self._local, attr):
                delattr(self._local, attr)

    def get_context_dict(self) -> Dict[str, str]:
        """Get all context as a dictionary."""
        context = {}
        for attr in ["request_id", "correlation_id", "user_id", "session_id"]:
            value = getattr(self._local, attr, None)
            if value:
                context[attr] = value
        return context


# Global request context
request_context = RequestContext()


def custom_formatter(record):
    """Custom formatter that adds context information."""

    # Add request context to record
    context = request_context.get_context_dict()
    for key, value in context.items():
        record["extra"][key] = value

    # Add timestamp in ISO format
    record["extra"]["timestamp_iso"] = datetime.utcnow().isoformat() + "Z"

    # Add process and thread info
    record["extra"]["process_id"] = os.getpid()
    record["extra"]["thread_id"] = threading.get_ident()
    record["extra"]["thread_name"] = threading.current_thread().name

    return record


def json_formatter(record):
    """JSON formatter for structured logging."""

    # Apply custom formatting first
    record = custom_formatter(record)

    # Create JSON structure
    log_entry = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "message": record["message"],
        "module": record["module"],
        "function": record["function"],
        "line": record["line"],
        "file": record["file"].name,
        "process_id": record["extra"].get("process_id"),
        "thread_id": record["extra"].get("thread_id"),
        "thread_name": record["extra"].get("thread_name"),
    }

    # Add context information
    for key in ["request_id", "correlation_id", "user_id", "session_id"]:
        if key in record["extra"]:
            log_entry[key] = record["extra"][key]

    # Add exception information if present
    if record["exception"]:
        log_entry["exception"] = {
            "type": record["exception"].type.__name__,
            "value": str(record["exception"].value),
            "traceback": record["exception"].traceback,
        }

    # Add any extra fields
    extra_fields = {
        k: v
        for k, v in record["extra"].items()
        if k
        not in [
            "process_id",
            "thread_id",
            "thread_name",
            "timestamp_iso",
            "request_id",
            "correlation_id",
            "user_id",
            "session_id",
        ]
    }
    if extra_fields:
        log_entry["extra"] = extra_fields

    return json.dumps(log_entry, default=str, ensure_ascii=False)


def setup_console_logging(config: LogConfig):
    """Setup console logging handler."""

    if not config.console:
        return None

    format_string = config.format_string or DEFAULT_LOG_FORMAT

    if config.structured or config.json_logs:
        logger.add(
            sys.stdout,
            level=config.level,
            format=json_formatter,
            colorize=False,
            backtrace=config.backtrace,
            diagnose=config.diagnose,
            filter=lambda record: custom_formatter(record) or True,
        )
    else:
        logger.add(
            sys.stdout,
            level=config.level,
            format=format_string,
            colorize=config.colorize,
            backtrace=config.backtrace,
            diagnose=config.diagnose,
            filter=lambda record: custom_formatter(record) or True,
        )


def setup_file_logging(config: LogConfig):
    """Setup file logging handlers."""

    if not config.file:
        return None

    # Create log directory
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Main application log
    app_log_file = log_dir / "app.log"

    if config.structured or config.json_logs:
        logger.add(
            str(app_log_file),
            level=config.level,
            format=json_formatter,
            rotation=config.rotation,
            retention=config.retention,
            compression="gz",
            backtrace=config.backtrace,
            diagnose=config.diagnose,
            filter=lambda record: custom_formatter(record) or True,
        )
    else:
        format_string = config.format_string or DEFAULT_LOG_FORMAT
        logger.add(
            str(app_log_file),
            level=config.level,
            format=format_string,
            rotation=config.rotation,
            retention=config.retention,
            compression="gz",
            backtrace=config.backtrace,
            diagnose=config.diagnose,
            filter=lambda record: custom_formatter(record) or True,
        )

    # Error log (separate file for errors and above)
    error_log_file = log_dir / "error.log"
    logger.add(
        str(error_log_file),
        level="ERROR",
        format=(
            json_formatter if (config.structured or config.json_logs) else format_string
        ),
        rotation=config.rotation,
        retention=config.retention,
        compression="gz",
        backtrace=True,
        diagnose=config.diagnose,
        filter=lambda record: custom_formatter(record) or True,
    )


def setup_audit_logging(config: LogConfig):
    """Setup audit logging for security and compliance."""

    if not config.enable_audit_logging:
        return None

    log_dir = Path(config.log_dir)
    audit_log_file = log_dir / "audit.log"

    # Audit logs should always be JSON for compliance
    logger.add(
        str(audit_log_file),
        level="INFO",
        format=json_formatter,
        rotation=config.rotation,
        retention="1 year",  # Keep audit logs longer
        compression="gz",
        filter=lambda record: record["extra"].get("audit", False)
        and (custom_formatter(record) or True),
    )


def setup_performance_logging(config: LogConfig):
    """Setup performance logging for monitoring."""

    if not config.enable_performance_logging:
        return None

    log_dir = Path(config.log_dir)
    perf_log_file = log_dir / "performance.log"

    logger.add(
        str(perf_log_file),
        level="INFO",
        format=json_formatter,
        rotation=config.rotation,
        retention=config.retention,
        compression="gz",
        filter=lambda record: record["extra"].get("performance", False)
        and (custom_formatter(record) or True),
    )


def setup_security_logging(config: LogConfig):
    """Setup security logging for threat detection."""

    if not config.enable_security_logging:
        return None

    log_dir = Path(config.log_dir)
    security_log_file = log_dir / "security.log"

    logger.add(
        str(security_log_file),
        level="WARNING",
        format=json_formatter,
        rotation=config.rotation,
        retention="6 months",  # Keep security logs longer
        compression="gz",
        filter=lambda record: record["extra"].get("security", False)
        and (custom_formatter(record) or True),
    )


def configure_logging(
    config: Optional[Union[LogConfig, Dict[str, Any]]] = None,
    environment: Optional[str] = None,
) -> LogConfig:
    """
    Configure logging based on configuration and environment.

    Args:
        config: Logging configuration (LogConfig or dict)
        environment: Environment name for default configuration

    Returns:
        LogConfig: The final configuration used
    """

    if not LOGURU_AVAILABLE:
        print("Warning: loguru not available, falling back to standard logging")
        return LogConfig()

    # Remove all existing handlers
    logger.remove()

    # Determine environment
    if environment is None:
        environment = os.getenv("ENVIRONMENT", "development").lower()

    # Start with environment defaults
    env_config = ENVIRONMENT_CONFIGS.get(
        environment, ENVIRONMENT_CONFIGS["development"]
    )

    # Create config object
    if config is None:
        final_config = LogConfig(**env_config)
    elif isinstance(config, dict):
        # Merge with environment config
        merged_config = {**env_config, **config}
        final_config = LogConfig(**merged_config)
    else:
        final_config = config

    # Override with environment variables
    final_config.level = os.getenv("LOG_LEVEL", final_config.level).upper()
    final_config.log_dir = os.getenv("LOG_DIR", final_config.log_dir)

    # Parse boolean environment variables
    if os.getenv("LOG_JSON"):
        final_config.json_logs = os.getenv("LOG_JSON", "").lower() in (
            "true",
            "1",
            "yes",
        )
    if os.getenv("LOG_CONSOLE"):
        final_config.console = os.getenv("LOG_CONSOLE", "").lower() in (
            "true",
            "1",
            "yes",
        )
    if os.getenv("LOG_FILE"):
        final_config.file = os.getenv("LOG_FILE", "").lower() in ("true", "1", "yes")

    # Setup logging handlers
    try:
        setup_console_logging(final_config)
        setup_file_logging(final_config)
        setup_audit_logging(final_config)
        setup_performance_logging(final_config)
        setup_security_logging(final_config)

        # Log the configuration
        logger.info(
            f"Logging configured for {environment} environment",
            extra={
                "log_config": {
                    "level": final_config.level,
                    "console": final_config.console,
                    "file": final_config.file,
                    "structured": final_config.structured,
                    "log_dir": final_config.log_dir,
                }
            },
        )

    except Exception as e:
        print(f"Error configuring logging: {e}")
        traceback.print_exc()

    return final_config


# Performance monitoring utilities
class PerformanceLogger:
    """Performance logging utilities."""

    @staticmethod
    def log_execution_time(func_name: str, execution_time: float, **extra):
        """Log function execution time."""
        logger.info(
            f"Function {func_name} executed in {execution_time:.3f}s",
            extra={
                "performance": True,
                "function_name": func_name,
                "execution_time_ms": execution_time * 1000,
                "execution_time_s": execution_time,
                **extra,
            },
        )

    @staticmethod
    def log_api_request(
        method: str, url: str, status_code: int, response_time: float, **extra
    ):
        """Log API request performance."""
        logger.info(
            f"API {method} {url} - {status_code} in {response_time:.3f}s",
            extra={
                "performance": True,
                "api_method": method,
                "api_url": url,
                "api_status_code": status_code,
                "api_response_time_ms": response_time * 1000,
                "api_response_time_s": response_time,
                **extra,
            },
        )

    @staticmethod
    def log_database_query(
        query: str, execution_time: float, rows_affected: int = None, **extra
    ):
        """Log database query performance."""
        logger.info(
            f"Database query executed in {execution_time:.3f}s",
            extra={
                "performance": True,
                "db_query": query[:200] + "..." if len(query) > 200 else query,
                "db_execution_time_ms": execution_time * 1000,
                "db_execution_time_s": execution_time,
                "db_rows_affected": rows_affected,
                **extra,
            },
        )


# Audit logging utilities
class AuditLogger:
    """Audit logging utilities for compliance and security."""

    @staticmethod
    def log_user_action(action: str, user_id: str, resource: str = None, **extra):
        """Log user action for audit trail."""
        logger.info(
            f"User {user_id} performed {action}"
            + (f" on {resource}" if resource else ""),
            extra={
                "audit": True,
                "audit_action": action,
                "audit_user_id": user_id,
                "audit_resource": resource,
                "audit_timestamp": datetime.utcnow().isoformat() + "Z",
                **extra,
            },
        )

    @staticmethod
    def log_data_access(user_id: str, data_type: str, operation: str, **extra):
        """Log data access for compliance."""
        logger.info(
            f"User {user_id} {operation} {data_type}",
            extra={
                "audit": True,
                "audit_data_access": True,
                "audit_user_id": user_id,
                "audit_data_type": data_type,
                "audit_operation": operation,
                "audit_timestamp": datetime.utcnow().isoformat() + "Z",
                **extra,
            },
        )

    @staticmethod
    def log_system_event(event: str, severity: str = "info", **extra):
        """Log system event for audit trail."""
        logger.info(
            f"System event: {event}",
            extra={
                "audit": True,
                "audit_system_event": True,
                "audit_event": event,
                "audit_severity": severity,
                "audit_timestamp": datetime.utcnow().isoformat() + "Z",
                **extra,
            },
        )


# Security logging utilities
class SecurityLogger:
    """Security logging utilities for threat detection."""

    @staticmethod
    def log_authentication_attempt(
        user_id: str, success: bool, ip_address: str = None, **extra
    ):
        """Log authentication attempt."""
        level = "INFO" if success else "WARNING"
        message = (
            f"Authentication {'successful' if success else 'failed'} for user {user_id}"
        )

        getattr(logger, level.lower())(
            message,
            extra={
                "security": True,
                "security_auth": True,
                "security_user_id": user_id,
                "security_auth_success": success,
                "security_ip_address": ip_address,
                "security_timestamp": datetime.utcnow().isoformat() + "Z",
                **extra,
            },
        )

    @staticmethod
    def log_authorization_failure(user_id: str, resource: str, action: str, **extra):
        """Log authorization failure."""
        logger.warning(
            f"Authorization failed: user {user_id} attempted {action} on {resource}",
            extra={
                "security": True,
                "security_authz": True,
                "security_user_id": user_id,
                "security_resource": resource,
                "security_action": action,
                "security_timestamp": datetime.utcnow().isoformat() + "Z",
                **extra,
            },
        )

    @staticmethod
    def log_suspicious_activity(
        activity: str, user_id: str = None, ip_address: str = None, **extra
    ):
        """Log suspicious activity."""
        logger.warning(
            f"Suspicious activity detected: {activity}",
            extra={
                "security": True,
                "security_suspicious": True,
                "security_activity": activity,
                "security_user_id": user_id,
                "security_ip_address": ip_address,
                "security_timestamp": datetime.utcnow().isoformat() + "Z",
                **extra,
            },
        )


# Context managers for request tracking
@contextmanager
def log_request_context(
    request_id: str,
    correlation_id: str = None,
    user_id: str = None,
    session_id: str = None,
):
    """Context manager for request logging."""

    # Set context
    request_context.set_request_id(request_id)
    if correlation_id:
        request_context.set_correlation_id(correlation_id)
    if user_id:
        request_context.set_user_id(user_id)
    if session_id:
        request_context.set_session_id(session_id)

    try:
        yield
    finally:
        # Clear context
        request_context.clear()


@contextmanager
def log_performance_context(operation_name: str):
    """Context manager for performance logging."""

    start_time = time.time()
    try:
        yield
    finally:
        execution_time = time.time() - start_time
        PerformanceLogger.log_execution_time(operation_name, execution_time)


# Decorator for automatic performance logging
def log_performance(operation_name: str = None):
    """Decorator for automatic performance logging."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            name = operation_name or f"{func.__module__}.{func.__name__}"

            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                execution_time = time.time() - start_time
                PerformanceLogger.log_execution_time(name, execution_time)

        return wrapper

    return decorator


# Get configured logger instance
def get_logger(name: str = None):
    """
    Get a logger instance with the specified name.

    Args:
        name: Logger name (defaults to calling module)

    Returns:
        Logger instance
    """
    if name is None:
        # Get calling module name
        import inspect

        frame = inspect.currentframe().f_back
        name = frame.f_globals.get("__name__", "unknown")

    if LOGURU_AVAILABLE:
        return logger.bind(logger_name=name)
    else:
        return logging.getLogger(name)


# Default configuration for immediate use
_default_config_applied = False


def apply_default_config():
    """Apply default logging configuration if none has been applied."""
    global _default_config_applied

    if not _default_config_applied and LOGURU_AVAILABLE:
        configure_logging()
        _default_config_applied = True


# Apply default config on import
apply_default_config()
