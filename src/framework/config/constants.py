"""
FKS Trading Systems constants and default values.

This module contains application-wide constants, default configurations,
and system-level settings used throughout the FKS Trading Systems platform.
"""

import os
from enum import Enum
from typing import Any, Dict, Optional

# =============================================================================
# Application Metadata
# =============================================================================

APP_NAME = "FKS Trading Systems"
APP_SHORT_NAME = "fks-trading"
APP_VERSION = "2.1.0"
APP_DESCRIPTION = "Advanced AI-Powered Cryptocurrency Trading Platform"
APP_AUTHOR = "FKS Trading Systems"
APP_URL = "https://github.com/fks-trading/fks-trading-systems"
APP_LICENSE = "MIT"

# Build and deployment info
BUILD_NUMBER = os.environ.get("BUILD_NUMBER", "local")
GIT_COMMIT = os.environ.get("GIT_COMMIT", "unknown")
BUILD_DATE = os.environ.get("BUILD_DATE", "unknown")


# =============================================================================
# Environment Configuration
# =============================================================================


class AppEnvironment(Enum):
    """Application environment types."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"
    LOCAL = "local"


# Current environment detection
APP_ENV = AppEnvironment(os.environ.get("FKS_ENVIRONMENT", "development").lower())
DEBUG = os.environ.get("FKS_DEBUG", "false").lower() in ("true", "1", "yes", "on")


# =============================================================================
# File and Path Constants
# =============================================================================

# Configuration file names
DEFAULT_CONFIG_FILES = [
    "config.yaml",
    "config.yml",
    "app.yaml",
    "app.yml",
    "fks.yaml",
    "fks.yml",
]

# Environment-specific config files
ENV_CONFIG_FILES = {
    AppEnvironment.DEVELOPMENT: ["config.dev.yaml", "config.development.yaml"],
    AppEnvironment.STAGING: ["config.staging.yaml", "config.stage.yaml"],
    AppEnvironment.PRODUCTION: ["config.prod.yaml", "config.production.yaml"],
    AppEnvironment.TESTING: ["config.test.yaml", "config.testing.yaml"],
    AppEnvironment.LOCAL: ["config.local.yaml"],
}

# Directory names
DEFAULT_DIRECTORIES = {
    "config": "config",
    "data": "data",
    "models": "models",
    "logs": "logs",
    "outputs": "outputs",
    "cache": "cache",
    "temp": "temp",
    "backups": "backups",
    "static": "static",
    "templates": "templates",
}

# File extensions
SUPPORTED_CONFIG_FORMATS = [".yaml", ".yml", ".json", ".toml", ".env"]
DATA_FILE_FORMATS = [".csv", ".parquet", ".json", ".pkl", ".h5", ".feather"]
MODEL_FILE_FORMATS = [".pkl", ".joblib", ".h5", ".pb", ".onnx", ".pt", ".pth"]


# =============================================================================
# Network and API Constants
# =============================================================================

# Default ports
DEFAULT_PORTS = {
    "api": 8000,
    "web": 3000,
    "websocket": 8001,
    "metrics": 9090,
    "admin": 8080,
}

# HTTP settings
HTTP_TIMEOUT = 30
HTTP_MAX_RETRIES = 3
HTTP_RETRY_BACKOFF = 0.3
HTTP_USER_AGENT = f"{APP_SHORT_NAME}/{APP_VERSION}"

# WebSocket settings
WS_HEARTBEAT_INTERVAL = 30
WS_RECONNECT_DELAY = 5
WS_MAX_RECONNECT_ATTEMPTS = 10

# Rate limiting
DEFAULT_RATE_LIMITS = {
    "api_requests_per_minute": 1000,
    "websocket_messages_per_second": 100,
    "data_requests_per_hour": 10000,
}


# =============================================================================
# Database Constants
# =============================================================================

# Connection settings
DB_POOL_SIZE = 10
DB_MAX_OVERFLOW = 20
DB_POOL_TIMEOUT = 30
DB_POOL_RECYCLE = 3600
DB_ECHO_SQL = DEBUG

# Query settings
DB_QUERY_TIMEOUT = 30
DB_BATCH_SIZE = 1000
DB_MAX_CONNECTIONS = 100

# Table prefixes
DB_TABLE_PREFIX = "fks_"
DB_SCHEMA_NAME = "trading"


# =============================================================================
# Cache and Redis Constants
# =============================================================================

# Redis settings
REDIS_DEFAULT_PORT = 6379
REDIS_DEFAULT_DB = 0
REDIS_CONNECTION_POOL_SIZE = 10
REDIS_SOCKET_TIMEOUT = 5
REDIS_SOCKET_CONNECT_TIMEOUT = 5

# Cache settings
CACHE_DEFAULT_TTL = 3600  # 1 hour
CACHE_KEY_PREFIX = f"{APP_SHORT_NAME}:"
CACHE_SERIALIZER = "pickle"

# Cache TTL for different data types
CACHE_TTLS = {
    "market_data": 60,  # 1 minute
    "user_session": 1800,  # 30 minutes
    "configuration": 3600,  # 1 hour
    "model_results": 7200,  # 2 hours
    "historical_data": 86400,  # 24 hours
}


# =============================================================================
# Logging Constants
# =============================================================================

# Log levels
LOG_LEVELS = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
DEFAULT_LOG_LEVEL = "INFO"

# Log formats
LOG_FORMAT_SIMPLE = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
LOG_FORMAT_DETAILED = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}"
)
LOG_FORMAT_JSON = '{"timestamp": "{time:YYYY-MM-DD HH:mm:ss.SSS}", "level": "{level}", "logger": "{name}", "function": "{function}", "line": {line}, "message": "{message}"}'

# Default log format
DEFAULT_LOG_FORMAT = LOG_FORMAT_DETAILED if DEBUG else LOG_FORMAT_SIMPLE

# Log rotation
LOG_ROTATION = "10 MB"
LOG_RETENTION = "30 days"
LOG_COMPRESSION = "gz"

# Log file names
LOG_FILES = {
    "main": "fks_trading.log",
    "api": "api.log",
    "trading": "trading.log",
    "ml": "ml.log",
    "data": "data.log",
    "errors": "errors.log",
    "audit": "audit.log",
}


# =============================================================================
# Security Constants
# =============================================================================

# JWT settings
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30
JWT_REFRESH_TOKEN_EXPIRE_DAYS = 7

# Password settings
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PASSWORD_HASH_ROUNDS = 12

# Security headers
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'",
}

# Rate limiting
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
API_RATE_LIMIT = "1000/hour"


# =============================================================================
# Trading Constants
# =============================================================================

# Supported exchanges
SUPPORTED_EXCHANGES = [
    "binance",
    "coinbase_pro",
    "kraken",
    "bitfinex",
    "huobi",
    "okx",
    "bybit",
]

# Currency pairs
MAJOR_CRYPTO_PAIRS = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "DOT/USDT",
    "DOGE/USDT",
    "AVAX/USDT",
    "LUNA/USDT",
    "LINK/USDT",
    "MATIC/USDT",
]

# Default trading parameters
DEFAULT_TRADING_CONFIG = {
    "base_currency": "USDT",
    "initial_balance": 10000.0,
    "max_position_size": 0.1,  # 10% of portfolio
    "risk_per_trade": 0.02,  # 2% risk per trade
    "stop_loss_pct": 0.05,  # 5% stop loss
    "take_profit_pct": 0.10,  # 10% take profit
    "commission": 0.001,  # 0.1% commission
    "slippage": 0.001,  # 0.1% slippage
    "min_trade_amount": 10.0,
}

# Market data intervals
TIMEFRAMES = [
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
]

# Default timeframe for analysis
DEFAULT_TIMEFRAME = "1h"

# Order types
ORDER_TYPES = [
    "market",
    "limit",
    "stop_loss",
    "stop_loss_limit",
    "take_profit",
    "take_profit_limit",
    "trailing_stop",
]


# =============================================================================
# Machine Learning Constants
# =============================================================================

# Model types
ML_MODEL_TYPES = [
    "lstm",
    "gru",
    "transformer",
    "cnn_lstm",
    "random_forest",
    "xgboost",
    "lightgbm",
    "linear_regression",
    "ridge",
    "lasso",
]

# Default ML parameters
DEFAULT_ML_CONFIG = {
    "sequence_length": 60,
    "batch_size": 32,
    "epochs": 100,
    "learning_rate": 0.001,
    "dropout": 0.2,
    "validation_split": 0.2,
    "early_stopping_patience": 10,
    "random_seed": 42,
}

# Feature types
FEATURE_TYPES = [
    "price",
    "volume",
    "technical_indicators",
    "sentiment",
    "social_media",
    "on_chain",
    "market_microstructure",
    "volatility",
]

# Technical indicators
TECHNICAL_INDICATORS = [
    "sma",
    "ema",
    "rsi",
    "macd",
    "bollinger_bands",
    "stochastic",
    "williams_r",
    "cci",
    "atr",
    "adx",
    "vwap",
    "obv",
    "mfi",
    "momentum",
    "roc",
]

# Model evaluation metrics
EVALUATION_METRICS = [
    "mse",
    "rmse",
    "mae",
    "mape",
    "r2_score",
    "accuracy",
    "precision",
    "recall",
    "f1_score",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
]


# =============================================================================
# Data Processing Constants
# =============================================================================

# Data sources
DATA_SOURCES = [
    "binance",
    "coinbase",
    "kraken",
    "yahoo_finance",
    "alpha_vantage",
    "quandl",
    "cryptocompare",
    "coingecko",
]

# Data frequencies
DATA_FREQUENCIES = {
    "tick": "tick",
    "second": "1s",
    "minute": "1m",
    "hourly": "1h",
    "daily": "1d",
    "weekly": "1w",
    "monthly": "1M",
}

# Data validation thresholds
DATA_QUALITY_THRESHOLDS = {
    "missing_data_threshold": 0.05,  # 5% missing data tolerance
    "outlier_threshold": 3.0,  # 3 standard deviations
    "correlation_threshold": 0.95,  # High correlation threshold
    "variance_threshold": 0.01,  # Low variance threshold
}

# File formats and compression
COMPRESSION_FORMATS = ["gzip", "bz2", "xz", "snappy"]
DEFAULT_COMPRESSION = "snappy"

# Batch processing
BATCH_SIZES = {"small": 1000, "medium": 10000, "large": 100000, "xlarge": 1000000}


# =============================================================================
# Monitoring and Metrics Constants
# =============================================================================

# Health check endpoints
HEALTH_CHECK_ENDPOINTS = [
    "/health",
    "/health/ready",
    "/health/live",
    "/metrics",
    "/status",
]

# Monitoring intervals (seconds)
MONITORING_INTERVALS = {
    "health_check": 30,
    "metrics_collection": 60,
    "log_rotation": 3600,
    "cleanup": 86400,
}

# Alert thresholds
ALERT_THRESHOLDS = {
    "cpu_usage": 80,  # 80% CPU usage
    "memory_usage": 85,  # 85% memory usage
    "disk_usage": 90,  # 90% disk usage
    "error_rate": 0.05,  # 5% error rate
    "response_time": 5000,  # 5 seconds response time
    "queue_depth": 1000,  # 1000 items in queue
}

# Metrics collection
METRICS_RETENTION_DAYS = 30
METRICS_AGGREGATION_INTERVALS = ["1m", "5m", "1h", "1d"]


# =============================================================================
# Feature Flags and Experimental Settings
# =============================================================================

# Feature flags
FEATURE_FLAGS = {
    "enable_ml_predictions": True,
    "enable_real_time_trading": False,
    "enable_advanced_analytics": True,
    "enable_social_sentiment": False,
    "enable_news_analysis": False,
    "enable_portfolio_optimization": True,
    "enable_risk_management": True,
    "enable_backtesting": True,
}

# Experimental features (disabled by default)
EXPERIMENTAL_FEATURES = {
    "quantum_ml": False,
    "reinforcement_learning": False,
    "federated_learning": False,
    "automated_hyperparameter_tuning": False,
    "multi_asset_trading": False,
}


# =============================================================================
# System Resource Limits
# =============================================================================

# Memory limits (in MB)
MEMORY_LIMITS = {
    "api_worker": 512,
    "ml_training": 4096,
    "data_processing": 2048,
    "web_server": 256,
    "background_tasks": 1024,
}

# CPU limits (number of cores)
CPU_LIMITS = {
    "api_worker": 1,
    "ml_training": 4,
    "data_processing": 2,
    "web_server": 1,
    "background_tasks": 2,
}

# Disk space limits (in GB)
DISK_LIMITS = {"logs": 10, "data": 100, "models": 50, "cache": 20, "temp": 10}


# =============================================================================
# Error Codes and Messages
# =============================================================================

# Application-specific error codes
ERROR_CODES = {
    # Configuration errors (1000-1099)
    "CONFIG_NOT_FOUND": 1001,
    "CONFIG_INVALID": 1002,
    "CONFIG_MISSING_REQUIRED": 1003,
    # Authentication errors (1100-1199)
    "AUTH_INVALID_CREDENTIALS": 1101,
    "AUTH_TOKEN_EXPIRED": 1102,
    "AUTH_ACCESS_DENIED": 1103,
    # Trading errors (1200-1299)
    "TRADING_INSUFFICIENT_BALANCE": 1201,
    "TRADING_INVALID_PAIR": 1202,
    "TRADING_ORDER_FAILED": 1203,
    # ML errors (1300-1399)
    "ML_MODEL_NOT_FOUND": 1301,
    "ML_TRAINING_FAILED": 1302,
    "ML_PREDICTION_FAILED": 1303,
    # Data errors (1400-1499)
    "DATA_SOURCE_UNAVAILABLE": 1401,
    "DATA_VALIDATION_FAILED": 1402,
    "DATA_PROCESSING_FAILED": 1403,
}

# Default error messages
ERROR_MESSAGES = {
    1001: "Configuration file not found",
    1002: "Invalid configuration format",
    1003: "Required configuration parameter missing",
    1101: "Invalid username or password",
    1102: "Authentication token has expired",
    1103: "Access denied - insufficient permissions",
    1201: "Insufficient balance for trade",
    1202: "Invalid trading pair",
    1203: "Order execution failed",
    1301: "ML model not found",
    1302: "Model training failed",
    1303: "Prediction generation failed",
    1401: "Data source is currently unavailable",
    1402: "Data validation failed",
    1403: "Data processing failed",
}


# =============================================================================
# Utility Functions
# =============================================================================


def get_app_info() -> Dict[str, str]:
    """Get application information dictionary."""
    return {
        "name": APP_NAME,
        "short_name": APP_SHORT_NAME,
        "version": APP_VERSION,
        "description": APP_DESCRIPTION,
        "author": APP_AUTHOR,
        "url": APP_URL,
        "license": APP_LICENSE,
        "environment": APP_ENV.value,
        "debug": str(DEBUG),
        "build_number": BUILD_NUMBER,
        "git_commit": GIT_COMMIT,
        "build_date": BUILD_DATE,
    }


def get_default_config() -> Dict[str, Any]:
    """Get default configuration dictionary."""
    return {
        "app": get_app_info(),
        "trading": DEFAULT_TRADING_CONFIG,
        "ml": DEFAULT_ML_CONFIG,
        "cache": {
            "ttl": CACHE_DEFAULT_TTL,
            "key_prefix": CACHE_KEY_PREFIX,
            "ttls": CACHE_TTLS,
        },
        "logging": {
            "level": DEFAULT_LOG_LEVEL,
            "format": DEFAULT_LOG_FORMAT,
            "rotation": LOG_ROTATION,
            "retention": LOG_RETENTION,
        },
        "monitoring": {
            "intervals": MONITORING_INTERVALS,
            "thresholds": ALERT_THRESHOLDS,
        },
        "features": FEATURE_FLAGS,
        "experimental": EXPERIMENTAL_FEATURES,
    }


def is_production() -> bool:
    """Check if running in production environment."""
    return APP_ENV == AppEnvironment.PRODUCTION


def is_development() -> bool:
    """Check if running in development environment."""
    return APP_ENV == AppEnvironment.DEVELOPMENT


def is_testing() -> bool:
    """Check if running in testing environment."""
    return APP_ENV == AppEnvironment.TESTING


def get_feature_flag(flag_name: str, default: bool = False) -> bool:
    """Get feature flag value with environment override."""
    env_var = f"FKS_FEATURE_{flag_name.upper()}"
    env_value = os.environ.get(env_var)

    if env_value is not None:
        return env_value.lower() in ("true", "1", "yes", "on")

    return FEATURE_FLAGS.get(flag_name, default)


def get_resource_limit(resource_type: str, component: str) -> Optional[int]:
    """Get resource limit for a specific component."""
    limits_map = {"memory": MEMORY_LIMITS, "cpu": CPU_LIMITS, "disk": DISK_LIMITS}

    limits = limits_map.get(resource_type)
    if limits:
        return limits.get(component)

    return None


# =============================================================================
# Export All Constants
# =============================================================================

__all__ = [
    # Application metadata
    "APP_NAME",
    "APP_SHORT_NAME",
    "APP_VERSION",
    "APP_DESCRIPTION",
    "APP_AUTHOR",
    # "APP_EMAIL",  # TODO: Define this constant or remove from exports
    "APP_URL",
    "APP_LICENSE",
    "BUILD_NUMBER",
    "GIT_COMMIT",
    "BUILD_DATE",
    # Environment
    "AppEnvironment",
    "APP_ENV",
    "DEBUG",
    # File and path constants
    "DEFAULT_CONFIG_FILES",
    "ENV_CONFIG_FILES",
    "DEFAULT_DIRECTORIES",
    "SUPPORTED_CONFIG_FORMATS",
    "DATA_FILE_FORMATS",
    "MODEL_FILE_FORMATS",
    # Network and API
    "DEFAULT_PORTS",
    "HTTP_TIMEOUT",
    "HTTP_MAX_RETRIES",
    "WS_HEARTBEAT_INTERVAL",
    "DEFAULT_RATE_LIMITS",
    # Database
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_QUERY_TIMEOUT",
    "DB_TABLE_PREFIX",
    # Cache and Redis
    "REDIS_DEFAULT_PORT",
    "CACHE_DEFAULT_TTL",
    "CACHE_KEY_PREFIX",
    "CACHE_TTLS",
    # Logging
    "LOG_LEVELS",
    "DEFAULT_LOG_LEVEL",
    "LOG_FORMAT_SIMPLE",
    "LOG_FORMAT_DETAILED",
    "DEFAULT_LOG_FORMAT",
    "LOG_FILES",
    # Security
    "JWT_ALGORITHM",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    "PASSWORD_MIN_LENGTH",
    "SECURITY_HEADERS",
    "MAX_LOGIN_ATTEMPTS",
    # Trading
    "SUPPORTED_EXCHANGES",
    "MAJOR_CRYPTO_PAIRS",
    "DEFAULT_TRADING_CONFIG",
    "TIMEFRAMES",
    "DEFAULT_TIMEFRAME",
    "ORDER_TYPES",
    # Machine Learning
    "ML_MODEL_TYPES",
    "DEFAULT_ML_CONFIG",
    "FEATURE_TYPES",
    "TECHNICAL_INDICATORS",
    "EVALUATION_METRICS",
    # Data Processing
    "DATA_SOURCES",
    "DATA_FREQUENCIES",
    "DATA_QUALITY_THRESHOLDS",
    "BATCH_SIZES",
    "DEFAULT_COMPRESSION",
    # Monitoring
    "HEALTH_CHECK_ENDPOINTS",
    "MONITORING_INTERVALS",
    "ALERT_THRESHOLDS",
    # Feature flags
    "FEATURE_FLAGS",
    "EXPERIMENTAL_FEATURES",
    # Resource limits
    "MEMORY_LIMITS",
    "CPU_LIMITS",
    "DISK_LIMITS",
    # Error handling
    "ERROR_CODES",
    "ERROR_MESSAGES",
    # Utility functions
    "get_app_info",
    "get_default_config",
    "is_production",
    "is_development",
    "is_testing",
    "get_feature_flag",
    "get_resource_limit",
]
