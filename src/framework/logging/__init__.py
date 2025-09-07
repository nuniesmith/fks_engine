"""
Framework Logging Package.

This package provides comprehensive logging functionality for the framework including:
- Structured logging with JSON support
- Multiple output targets (console, file, audit, performance, security)
- Request correlation and tracing
- Performance monitoring and metrics
- Audit trails for compliance
- Security event logging
- Environment-specific configurations
- Automatic log rotation and retention
"""

import os
import sys
from typing import Any, Dict, Optional, Union

# Import core logging functionality
from .setup import (
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
    ENVIRONMENT_CONFIGS,
    LOGURU_AVAILABLE,
    AuditLogger,
    LogConfig,
    PerformanceLogger,
    RequestContext,
    SecurityLogger,
    configure_logging,
    custom_formatter,
    get_logger,
    json_formatter,
    log_performance,
    log_performance_context,
    log_request_context,
    request_context,
)

# Import loguru logger if available
if LOGURU_AVAILABLE:
    try:
        from loguru import logger
    except ImportError:
        import logging

        logger = logging.getLogger("framework.logging")
else:
    import logging

    logger = logging.getLogger("framework.logging")

# Version information
__version__ = "1.0.0"
__author__ = "Framework Logging Team"

# Global configuration state
_logging_configured = False
_current_config = None


def setup_logging(
    config: Optional[Union[LogConfig, Dict[str, Any]]] = None,
    environment: Optional[str] = None,
    force_reconfigure: bool = False,
) -> LogConfig:
    """
    Setup logging for the application.

    Args:
        config: Logging configuration (LogConfig or dict)
        environment: Environment name ('development', 'staging', 'production')
        force_reconfigure: Force reconfiguration even if already configured

    Returns:
        LogConfig: The configuration that was applied
    """
    global _logging_configured, _current_config

    if _logging_configured and not force_reconfigure:
        logger.debug("Logging already configured, skipping setup")
        return _current_config

    # Configure logging
    _current_config = configure_logging(config=config, environment=environment)
    _logging_configured = True

    logger.info(
        "Framework logging setup completed",
        extra={"logging_setup": True, "environment": environment or "auto-detected"},
    )

    return _current_config


def get_current_config() -> Optional[LogConfig]:
    """
    Get the current logging configuration.

    Returns:
        LogConfig: Current configuration or None if not configured
    """
    return _current_config


def is_configured() -> bool:
    """
    Check if logging has been configured.

    Returns:
        bool: True if logging is configured
    """
    return _logging_configured


# Convenience logger functions
def debug(message: str, **kwargs):
    """Log a debug message."""
    logger.debug(message, **kwargs)


def info(message: str, **kwargs):
    """Log an info message."""
    logger.info(message, **kwargs)


def warning(message: str, **kwargs):
    """Log a warning message."""
    logger.warning(message, **kwargs)


def error(message: str, **kwargs):
    """Log an error message."""
    logger.error(message, **kwargs)


def critical(message: str, **kwargs):
    """Log a critical message."""
    logger.critical(message, **kwargs)


def exception(message: str, **kwargs):
    """Log an exception with traceback."""
    logger.exception(message, **kwargs)


# Structured logging helpers
def log_api_call(
    method: str, url: str, status_code: int, response_time: float, **extra
):
    """Log an API call with structured data."""
    PerformanceLogger.log_api_request(
        method=method,
        url=url,
        status_code=status_code,
        response_time=response_time,
        **extra,
    )


def log_database_operation(
    operation: str,
    table: str,
    execution_time: float,
    rows_affected: int = None,
    **extra,
):
    """Log a database operation with structured data."""
    PerformanceLogger.log_database_query(
        query=f"{operation} on {table}",
        execution_time=execution_time,
        rows_affected=rows_affected,
        **extra,
    )


def log_user_action(action: str, user_id: str, resource: str = None, **extra):
    """Log a user action for audit purposes."""
    AuditLogger.log_user_action(
        action=action, user_id=user_id, resource=resource, **extra
    )


def log_security_event(
    event: str,
    user_id: str = None,
    ip_address: str = None,
    severity: str = "warning",
    **extra,
):
    """Log a security event."""
    if severity.lower() == "warning":
        SecurityLogger.log_suspicious_activity(
            activity=event, user_id=user_id, ip_address=ip_address, **extra
        )
    else:
        SecurityLogger.log_system_event(event=event, severity=severity, **extra)


def log_performance_metric(metric_name: str, value: float, unit: str = "ms", **extra):
    """Log a performance metric."""
    logger.info(
        f"Performance metric: {metric_name} = {value} {unit}",
        extra={
            "performance": True,
            "metric_name": metric_name,
            "metric_value": value,
            "metric_unit": unit,
            **extra,
        },
    )


# Trading-specific logging helpers
def log_trade_execution(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    execution_time: float,
    order_id: str = None,
    **extra,
):
    """Log trade execution for audit and performance tracking."""
    logger.info(
        f"Trade executed: {side} {quantity} {symbol} @ {price}",
        extra={
            "audit": True,
            "performance": True,
            "trade_symbol": symbol,
            "trade_side": side,
            "trade_quantity": quantity,
            "trade_price": price,
            "trade_execution_time_ms": execution_time * 1000,
            "trade_order_id": order_id,
            **extra,
        },
    )


def log_market_data_update(symbol: str, data_type: str, latency: float = None, **extra):
    """Log market data updates for performance monitoring."""
    message = f"Market data update: {symbol} {data_type}"
    if latency:
        message += f" (latency: {latency:.3f}s)"

    logger.debug(
        message,
        extra={
            "performance": True,
            "market_data": True,
            "md_symbol": symbol,
            "md_type": data_type,
            "md_latency_ms": latency * 1000 if latency else None,
            **extra,
        },
    )


def log_strategy_decision(
    strategy_name: str, symbol: str, decision: str, confidence: float = None, **extra
):
    """Log trading strategy decisions."""
    logger.info(
        f"Strategy {strategy_name} decision for {symbol}: {decision}",
        extra={
            "audit": True,
            "strategy_name": strategy_name,
            "strategy_symbol": symbol,
            "strategy_decision": decision,
            "strategy_confidence": confidence,
            **extra,
        },
    )


def log_risk_alert(
    alert_type: str,
    message: str,
    severity: str = "warning",
    portfolio_impact: float = None,
    **extra,
):
    """Log risk management alerts."""
    log_level = severity.lower()
    getattr(logger, log_level)(
        f"Risk Alert [{alert_type}]: {message}",
        extra={
            "security": True,
            "audit": True,
            "risk_alert": True,
            "risk_type": alert_type,
            "risk_severity": severity,
            "risk_portfolio_impact": portfolio_impact,
            **extra,
        },
    )


# Request correlation helpers
def set_request_id(request_id: str):
    """Set the current request ID for correlation."""
    request_context.set_request_id(request_id)


def set_correlation_id(correlation_id: str):
    """Set the current correlation ID."""
    request_context.set_correlation_id(correlation_id)


def set_user_context(user_id: str, session_id: str = None):
    """Set user context for logging."""
    request_context.set_user_id(user_id)
    if session_id:
        request_context.set_session_id(session_id)


def clear_context():
    """Clear all request context."""
    request_context.clear()


def get_context():
    """Get current request context as dict."""
    return request_context.get_context_dict()


# Logger factory with framework defaults
def create_logger(
    name: str,
    level: Optional[str] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Create a logger with framework defaults.

    Args:
        name: Logger name
        level: Log level override
        extra_fields: Extra fields to include in all log messages

    Returns:
        Logger instance with framework configuration
    """
    logger_instance = get_logger(name)

    if extra_fields:
        logger_instance = logger_instance.bind(**extra_fields)

    return logger_instance


# Quick setup functions for common environments
def setup_development_logging(log_dir: str = "logs", level: str = "DEBUG"):
    """Quick setup for development environment."""
    config = LogConfig(
        level=level,
        console=True,
        file=True,
        structured=False,
        colorize=True,
        backtrace=True,
        diagnose=True,
        log_dir=log_dir,
        json_logs=False,
    )
    return setup_logging(config, environment="development")


def setup_production_logging(log_dir: str = "/var/log/app", level: str = "WARNING"):
    """Quick setup for production environment."""
    config = LogConfig(
        level=level,
        console=False,
        file=True,
        structured=True,
        colorize=False,
        backtrace=False,
        diagnose=False,
        log_dir=log_dir,
        json_logs=True,
        enable_audit_logging=True,
        enable_security_logging=True,
    )
    return setup_logging(config, environment="production")


def setup_testing_logging(level: str = "ERROR"):
    """Quick setup for testing environment (minimal logging)."""
    config = LogConfig(
        level=level,
        console=True,
        file=False,
        structured=False,
        colorize=False,
        backtrace=False,
        diagnose=False,
    )
    return setup_logging(config, environment="testing")


# Auto-configuration based on environment
def auto_configure_logging():
    """Auto-configure logging based on environment variables."""
    environment = os.getenv("ENVIRONMENT", "development").lower()

    if environment == "production":
        setup_production_logging()
    elif environment == "staging":
        config = LogConfig(
            level="INFO",
            console=True,
            file=True,
            structured=True,
            json_logs=True,
            log_dir=os.getenv("LOG_DIR", "logs"),
        )
        setup_logging(config, environment="staging")
    elif environment in ["test", "testing"]:
        setup_testing_logging()
    else:
        setup_development_logging()


# Export all public symbols
__all__ = [
    # Core configuration
    "LogConfig",
    "setup_logging",
    "configure_logging",
    "get_current_config",
    "is_configured",
    # Logger utilities
    "get_logger",
    "create_logger",
    "logger",
    # Basic logging functions
    "debug",
    "info",
    "warning",
    "error",
    "critical",
    "exception",
    # Structured logging
    "log_api_call",
    "log_database_operation",
    "log_user_action",
    "log_security_event",
    "log_performance_metric",
    # Trading-specific logging
    "log_trade_execution",
    "log_market_data_update",
    "log_strategy_decision",
    "log_risk_alert",
    # Context management
    "set_request_id",
    "set_correlation_id",
    "set_user_context",
    "clear_context",
    "get_context",
    "log_request_context",
    "log_performance_context",
    "log_performance",
    "request_context",
    # Utility classes
    "PerformanceLogger",
    "AuditLogger",
    "SecurityLogger",
    "RequestContext",
    # Quick setup functions
    "setup_development_logging",
    "setup_production_logging",
    "setup_testing_logging",
    "auto_configure_logging",
    # Constants
    "ENVIRONMENT_CONFIGS",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_LOG_DIR",
]

# Package metadata
__package_info__ = {
    "name": "framework.logging",
    "version": __version__,
    "description": (
        "Comprehensive logging framework with structured logging and monitoring"
    ),
    "features": [
        "Structured JSON logging",
        "Multiple output targets (console, file, audit, performance, security)",
        "Request correlation and tracing",
        "Performance monitoring and metrics",
        "Audit trails for compliance",
        "Security event logging and threat detection",
        "Environment-specific configurations",
        "Automatic log rotation and retention",
        "Trading-specific logging utilities",
        "Context managers for request tracking",
        "Decorators for automatic performance logging",
    ],
    "dependencies": [
        "loguru",  # Primary logging library
    ],
}


def get_package_info():
    """Get package information and features."""
    return __package_info__.copy()


# Health check for logging system
def health_check() -> Dict[str, Any]:
    """
    Perform a health check on the logging system.

    Returns:
        Dict containing health status and metrics
    """
    health_info = {
        "status": "healthy",
        "configured": _logging_configured,
        "loguru_available": LOGURU_AVAILABLE,
        "current_config": None,
        "log_directory_writable": False,
        "handlers_count": 0,
    }

    if _current_config:
        health_info["current_config"] = {
            "level": _current_config.level,
            "console": _current_config.console,
            "file": _current_config.file,
            "log_dir": _current_config.log_dir,
        }

        # Check if log directory is writable
        try:
            log_dir = _current_config.log_dir
            if os.path.exists(log_dir) and os.access(log_dir, os.W_OK):
                health_info["log_directory_writable"] = True
        except Exception:
            pass

    # Count handlers if using loguru
    if LOGURU_AVAILABLE:
        try:
            health_info["handlers_count"] = len(logger._core.handlers)
        except Exception:
            pass

    return health_info


# Context manager for temporary logging configuration
class temporary_logging_config:
    """Context manager for temporary logging configuration."""

    def __init__(self, config: Union[LogConfig, Dict[str, Any]]):
        self.temp_config = config
        self.original_config = None
        self.was_configured = False

    def __enter__(self):
        global _current_config, _logging_configured

        self.original_config = _current_config
        self.was_configured = _logging_configured

        setup_logging(self.temp_config, force_reconfigure=True)
        return _current_config

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _current_config, _logging_configured

        if self.original_config:
            setup_logging(self.original_config, force_reconfigure=True)
        else:
            _current_config = None
            _logging_configured = self.was_configured


# Add to exports
__all__.extend(
    [
        "health_check",
        "temporary_logging_config",
        "get_package_info",
    ]
)

# Auto-configure on import if not in testing environment
if not os.getenv("SKIP_LOGGING_AUTO_CONFIG"):
    try:
        if not _logging_configured:
            auto_configure_logging()
    except Exception as e:
        # Don't fail import if logging setup fails
        print(f"Warning: Auto-configuration of logging failed: {e}")

# Final initialization message
if LOGURU_AVAILABLE and _logging_configured:
    logger.debug("Framework logging package initialized successfully")
else:
    print("Framework logging package loaded (loguru not available or not configured)")
