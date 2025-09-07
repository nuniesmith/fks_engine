"""
FKS Trading Systems configuration models.

This module contains data models and structures for configuration management.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class ConfigFormat(Enum):
    """Supported configuration file formats."""

    YAML = "yaml"
    JSON = "json"
    ENV = "env"
    TOML = "toml"


class Environment(Enum):
    """Application environment types."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


@dataclass
class DatabaseConfig:
    """Database configuration model."""

    host: str = "localhost"
    port: int = 5432
    database: str = "fks_trading"
    username: str = "postgres"
    password: str = ""
    ssl_mode: str = "prefer"
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False

    def get_url(self) -> str:
        """Get database connection URL."""
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class LoggingConfig:
    """Logging configuration model."""

    level: str = "INFO"
    format: str = (
        "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}"
    )
    file_path: Optional[str] = None
    rotation: str = "10 MB"
    retention: str = "30 days"
    console_enabled: bool = True
    file_enabled: bool = True
    structured: bool = False

    def __post_init__(self):
        """Validate logging configuration."""
        valid_levels = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.level.upper() not in valid_levels:
            raise ValueError(
                f"Invalid log level: {self.level}. Must be one of {valid_levels}"
            )


@dataclass
class APIConfig:
    """API configuration model."""

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    reload: bool = False
    workers: int = 1
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    cors_methods: List[str] = field(
        default_factory=lambda: ["GET", "POST", "PUT", "DELETE"]
    )
    cors_headers: List[str] = field(default_factory=lambda: ["*"])
    rate_limit: Optional[str] = None
    timeout: int = 30

    def get_base_url(self) -> str:
        """Get API base URL."""
        return f"http://{self.host}:{self.port}"


@dataclass
class RedisConfig:
    """Redis configuration model."""

    host: str = "localhost"
    port: int = 6379
    database: int = 0
    password: Optional[str] = None
    ssl: bool = False
    max_connections: int = 10
    socket_timeout: int = 5
    socket_connect_timeout: int = 5

    def get_url(self) -> str:
        """Get Redis connection URL."""
        auth = f":{self.password}@" if self.password else ""
        protocol = "rediss" if self.ssl else "redis"
        return f"{protocol}://{auth}{self.host}:{self.port}/{self.database}"


@dataclass
class MLConfig:
    """Machine learning configuration model."""

    model_type: str = "lstm"
    features: List[str] = field(default_factory=list)
    target: str = "close"
    sequence_length: int = 60
    batch_size: int = 32
    epochs: int = 100
    learning_rate: float = 0.001
    dropout: float = 0.2
    validation_split: float = 0.2
    early_stopping_patience: int = 10
    model_checkpoint: bool = True
    tensorboard_logs: bool = True
    random_seed: Optional[int] = 42


@dataclass
class TradingConfig:
    """Trading configuration model."""

    symbol: str = "BTCUSDT"
    base_currency: str = "BTC"
    quote_currency: str = "USDT"
    initial_balance: float = 10000.0
    max_position_size: float = 0.1
    risk_per_trade: float = 0.02
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    commission: float = 0.001
    slippage: float = 0.001
    min_trade_amount: float = 10.0


@dataclass
class PathConfig:
    """Application paths configuration."""

    base_dir: Path
    outputs_dir: Path
    data_dir: Path
    ml_dir: Path
    models_dir: Path
    logs_dir: Path
    backtest_dir: Path
    evaluation_dir: Path
    training_dir: Path
    cache_dir: Path

    def __post_init__(self):
        """Ensure all paths are Path objects."""
        for field_name, field_value in self.__dict__.items():
            if isinstance(field_value, str):
                setattr(self, field_name, Path(field_value))


@dataclass
class SecurityConfig:
    """Security configuration model."""

    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    password_min_length: int = 8
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 15

    def __post_init__(self):
        """Validate security configuration."""
        if not self.secret_key:
            import secrets

            self.secret_key = secrets.token_urlsafe(32)


@dataclass
class MonitoringConfig:
    """Monitoring and metrics configuration."""

    enabled: bool = True
    metrics_endpoint: str = "/metrics"
    health_endpoint: str = "/health"
    prometheus_enabled: bool = False
    grafana_enabled: bool = False
    alert_webhook_url: Optional[str] = None
    performance_monitoring: bool = True
    error_tracking: bool = True


@dataclass
class Config:
    """Main configuration container with typed access to all subsystems."""

    # Core configuration data
    data: Dict[str, Any] = field(default_factory=dict)

    # Typed configuration sections
    paths: Optional[PathConfig] = None
    database: Optional[DatabaseConfig] = None
    logging: Optional[LoggingConfig] = None
    api: Optional[APIConfig] = None
    redis: Optional[RedisConfig] = None
    ml: Optional[MLConfig] = None
    trading: Optional[TradingConfig] = None
    security: Optional[SecurityConfig] = None
    monitoring: Optional[MonitoringConfig] = None

    # Metadata
    environment: Environment = Environment.DEVELOPMENT
    app_name: str = "fks-trading"
    app_version: str = "1.0.0"
    debug: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with dot notation support."""
        keys = key.split(".")
        value = self.data

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value with dot notation support."""
        keys = key.split(".")
        target = self.data

        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]

        target[keys[-1]] = value

    def update(self, other: Dict[str, Any]) -> None:
        """Deep update configuration with another dictionary."""
        self._deep_update(self.data, other)
        self._update_typed_configs()

    def _deep_update(
        self, base_dict: Dict[str, Any], update_dict: Dict[str, Any]
    ) -> None:
        """Recursively update nested dictionaries."""
        for key, value in update_dict.items():
            if (
                key in base_dict
                and isinstance(base_dict[key], dict)
                and isinstance(value, dict)
            ):
                self._deep_update(base_dict[key], value)
            else:
                base_dict[key] = value

    def _update_typed_configs(self) -> None:
        """Update typed configuration objects from data dictionary."""
        config_mappings = {
            "database": DatabaseConfig,
            "logging": LoggingConfig,
            "api": APIConfig,
            "redis": RedisConfig,
            "ml": MLConfig,
            "trading": TradingConfig,
            "security": SecurityConfig,
            "monitoring": MonitoringConfig,
        }

        for key, config_class in config_mappings.items():
            if key in self.data:
                try:
                    config_data = self.data[key]
                    if isinstance(config_data, dict):
                        setattr(self, key, config_class(**config_data))
                except Exception as e:
                    # Log error but don't fail completely
                    import logging

                    logging.warning(f"Failed to create {key} config: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        result = self.data.copy()

        # Add typed configs
        typed_configs = [
            "database",
            "logging",
            "api",
            "redis",
            "ml",
            "trading",
            "security",
            "monitoring",
        ]
        for config_name in typed_configs:
            config_obj = getattr(self, config_name)
            if config_obj:
                if hasattr(config_obj, "__dict__"):
                    result[config_name] = {
                        k: str(v) if isinstance(v, Path) else v
                        for k, v in config_obj.__dict__.items()
                    }

        # Add paths if available
        if self.paths:
            result["paths"] = {k: str(v) for k, v in self.paths.__dict__.items()}

        # Add metadata
        result.update(
            {
                "environment": self.environment.value,
                "app_name": self.app_name,
                "app_version": self.app_version,
                "debug": self.debug,
            }
        )

        return result

    def to_json(self, indent: int = 2) -> str:
        """Convert configuration to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == Environment.PRODUCTION

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == Environment.DEVELOPMENT

    def is_testing(self) -> bool:
        """Check if running in testing environment."""
        return self.environment == Environment.TESTING

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        errors = []

        # Validate required fields based on environment
        if self.is_production():
            if not self.security or not self.security.secret_key:
                errors.append("Secret key is required in production")

            if self.debug:
                errors.append("Debug mode should be disabled in production")

        # Validate database configuration
        if self.database:
            if not self.database.host:
                errors.append("Database host is required")
            if not self.database.database:
                errors.append("Database name is required")

        # Validate API configuration
        if self.api:
            if self.api.port < 1 or self.api.port > 65535:
                errors.append("API port must be between 1 and 65535")

        # Validate ML configuration
        if self.ml:
            if self.ml.sequence_length <= 0:
                errors.append("ML sequence length must be positive")
            if self.ml.batch_size <= 0:
                errors.append("ML batch size must be positive")

        return errors


@dataclass
class ConfigSource:
    """Configuration source metadata."""

    path: Optional[Path] = None
    format: Optional[ConfigFormat] = None
    priority: int = 0
    required: bool = False
    watch: bool = False

    def __post_init__(self):
        """Auto-detect format from file extension if not provided."""
        if self.path and not self.format:
            suffix = self.path.suffix.lower()
            format_mapping = {
                ".yaml": ConfigFormat.YAML,
                ".yml": ConfigFormat.YAML,
                ".json": ConfigFormat.JSON,
                ".env": ConfigFormat.ENV,
                ".toml": ConfigFormat.TOML,
            }
            self.format = format_mapping.get(suffix)


@dataclass
class ValidationResult:
    """Configuration validation result."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Add validation error."""
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        """Add validation warning."""
        self.warnings.append(message)

    def has_errors(self) -> bool:
        """Check if validation has errors."""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Check if validation has warnings."""
        return len(self.warnings) > 0
