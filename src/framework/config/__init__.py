"""
FKS Trading Systems Configuration Package.

A comprehensive configuration management system for FKS Trading Systems with support
for multiple file formats, environment variables, cloud providers, and path management.

Usage:
    from fks.config import FKSConfigManager, Config

    # Initialize configuration manager
    config_manager = FKSConfigManager('config/app.yaml')

    # Access configuration
    db_host = config_manager.get('database.host')
    model_path = config_manager.get_models_path('my_model.pkl')

    # Load with overlays
    config = config_manager.load_with_overlays([
        'config/base.yaml',
        'config/production.yaml'
    ])
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Version information
__version__ = "1.0.0"
__author__ = "FKS Trading Systems"

# Add package to path for internal imports
_package_dir = Path(__file__).parent
if str(_package_dir) not in sys.path:
    sys.path.insert(0, str(_package_dir))

# Core imports
from .models import (
    APIConfig,
    Config,
    ConfigFormat,
    ConfigSource,
    DatabaseConfig,
    Environment,
    LoggingConfig,
    MLConfig,
    MonitoringConfig,
    PathConfig,
    RedisConfig,
    SecurityConfig,
    TradingConfig,
    ValidationResult,
)
from .providers import (
    ConfigProvider,
    ConfigProviderRegistry,
    EnvironmentProvider,
    FileProvider,
    URLProvider,
    provider_registry,
)

# Conditional cloud provider imports
try:
    from .providers import AWSParameterStoreProvider

    _AWS_AVAILABLE = True
except ImportError:
    _AWS_AVAILABLE = False

try:
    from .providers import ConsulProvider

    _CONSUL_AVAILABLE = True
except ImportError:
    _CONSUL_AVAILABLE = False

# Constants and defaults
from .constants import (
    APP_ENV,
    APP_NAME,
    APP_VERSION,
    DEFAULT_ML_CONFIG,
    DEFAULT_TRADING_CONFIG,
    FEATURE_FLAGS,
    AppEnvironment,
    get_app_info,
    get_default_config,
    is_development,
    is_production,
    is_testing,
)

# Main configuration manager
from .manager import ConfigProcessor, FKSConfigManager, PathManager

# Convenience aliases
ConfigManager = FKSConfigManager


def create_config_manager(
    config_path: Optional[Union[str, Path]] = None,
    env_prefix: str = "FKS_",
    watch_changes: bool = True,
    **kwargs,
) -> FKSConfigManager:
    """
    Create a configured FKS configuration manager.

    Args:
        config_path: Path to main configuration file (auto-detected if None)
        env_prefix: Environment variable prefix
        watch_changes: Whether to watch for configuration changes
        **kwargs: Additional arguments for FKSConfigManager

    Returns:
        Configured FKSConfigManager instance

    Example:
        config_manager = create_config_manager(
            config_path='config/app.yaml',
            env_prefix='MYAPP_'
        )
    """
    # Auto-detect config path if not provided
    if config_path is None:
        config_path = get_default_config_path()

    return FKSConfigManager(
        config_path=config_path,
        env_prefix=env_prefix,
        watch_for_changes=watch_changes,
        **kwargs,
    )


def load_config(
    sources: Union[str, Path, List[Union[str, Path, ConfigSource]]],
    env_prefix: str = "FKS_",
    base_dir: Optional[Path] = None,
    apply_defaults: bool = True,
) -> Config:
    """
    Load configuration from one or more sources.

    Args:
        sources: Configuration source(s) to load
        env_prefix: Environment variable prefix
        base_dir: Base directory for relative paths
        apply_defaults: Whether to apply default configuration values

    Returns:
        Loaded configuration object

    Example:
        config = load_config([
            'config/base.yaml',
            'config/production.yaml'
        ])
    """
    if isinstance(sources, (str, Path)):
        sources = [sources]

    # Start with defaults if requested
    if apply_defaults:
        merged_config = get_default_config()
    else:
        merged_config = {}

    # Load from all sources
    source_config = provider_registry.load_multiple(sources)

    # Add environment provider
    env_provider = EnvironmentProvider(prefix=env_prefix)
    env_config = env_provider.load()

    # Create config and merge everything
    config = Config(data=merged_config)
    config.update(source_config)
    config.update(env_config)

    return config


def load_config_from_env(prefix: str = "FKS_") -> Dict[str, Any]:
    """
    Load configuration from environment variables only.

    Args:
        prefix: Environment variable prefix

    Returns:
        Configuration dictionary

    Example:
        env_config = load_config_from_env('MYAPP_')
    """
    provider = EnvironmentProvider(prefix=prefix)
    return provider.load()


def get_default_config_path() -> Path:
    """
    Get the default configuration file path.

    Returns:
        Default configuration path
    """
    from .constants import DEFAULT_CONFIG_FILES, ENV_CONFIG_FILES

    # Look for environment-specific config first
    env_files = ENV_CONFIG_FILES.get(APP_ENV, [])

    # Combine environment-specific and default files
    all_config_files = env_files + DEFAULT_CONFIG_FILES

    # Search in common directories
    search_dirs = [
        Path.cwd() / "config",
        Path.cwd(),
        Path.home() / ".fks",
        Path("/etc/fks"),
    ]

    # Check each directory for each config file
    for directory in search_dirs:
        for config_file in all_config_files:
            config_path = directory / config_file
            if config_path.exists():
                return config_path

    # Return default path (config/config.yaml)
    return Path.cwd() / "config" / "config.yaml"


def validate_config(config: Union[Config, Dict[str, Any]]) -> ValidationResult:
    """
    Validate configuration object.

    Args:
        config: Configuration to validate

    Returns:
        Validation result

    Example:
        result = validate_config(config)
        if result.has_errors():
            print("Validation errors:", result.errors)
    """
    if isinstance(config, dict):
        config = Config(data=config)

    errors = config.validate()
    result = ValidationResult(is_valid=len(errors) == 0)

    for error in errors:
        result.add_error(error)

    return result


def setup_logging_from_config(config: Union[Config, LoggingConfig]) -> None:
    """
    Set up logging from configuration.

    Args:
        config: Configuration object or logging config

    Example:
        setup_logging_from_config(config_manager.config)
    """
    from loguru import logger

    if isinstance(config, Config):
        logging_config = config.logging
    else:
        logging_config = config

    if not logging_config:
        return

    # Remove default handler
    logger.remove()

    # Add console handler if enabled
    if logging_config.console_enabled:
        logger.add(sys.stderr, level=logging_config.level, format=logging_config.format)

    # Add file handler if enabled and path specified
    if logging_config.file_enabled and logging_config.file_path:
        logger.add(
            logging_config.file_path,
            level=logging_config.level,
            format=logging_config.format,
            rotation=logging_config.rotation,
            retention=logging_config.retention,
        )


def create_config_from_dict(data: Dict[str, Any]) -> Config:
    """
    Create a Config object from a dictionary.

    Args:
        data: Configuration data dictionary

    Returns:
        Config object

    Example:
        config_dict = {'database': {'host': 'localhost'}}
        config = create_config_from_dict(config_dict)
    """
    config = Config(data=data.copy())
    config._update_typed_configs()
    return config


# Utility functions for common configuration patterns
def get_env_or_default(key: str, default: Any = None, prefix: str = "FKS_") -> Any:
    """
    Get environment variable with optional prefix and default.

    Args:
        key: Environment variable key (without prefix)
        default: Default value if not found
        prefix: Environment variable prefix

    Returns:
        Environment variable value or default

    Example:
        db_host = get_env_or_default('DATABASE_HOST', 'localhost')
    """
    env_key = f"{prefix}{key}" if prefix else key
    return os.environ.get(env_key, default)


def get_feature_flag(flag_name: str, default: bool = False) -> bool:
    """
    Get feature flag value with environment override.

    Args:
        flag_name: Name of the feature flag
        default: Default value if flag not found

    Returns:
        Feature flag value

    Example:
        if get_feature_flag('enable_ml_predictions'):
            # ML predictions are enabled
            pass
    """
    from .constants import get_feature_flag as _get_feature_flag

    return _get_feature_flag(flag_name, default)


def create_default_config() -> Config:
    """
    Create a configuration object with default values.

    Returns:
        Configuration with default values applied

    Example:
        config = create_default_config()
        config.set('database.host', 'my-db-host')
    """
    default_data = get_default_config()
    config = Config(data=default_data)
    config._update_typed_configs()
    return config


def is_production() -> bool:
    """
    Check if running in production environment.

    Returns:
        True if in production environment
    """
    return APP_ENV == AppEnvironment.PRODUCTION


def is_development() -> bool:
    """
    Check if running in development environment.

    Returns:
        True if in development environment
    """
    return APP_ENV == AppEnvironment.DEVELOPMENT


def is_testing() -> bool:
    """
    Check if running in testing environment.

    Returns:
        True if in testing environment
    """
    return APP_ENV == AppEnvironment.TESTING


# Export all public symbols
__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__email__",
    # Core classes
    "Config",
    "PathConfig",
    "FKSConfigManager",
    "ConfigManager",  # Alias
    # Configuration models
    "DatabaseConfig",
    "LoggingConfig",
    "APIConfig",
    "RedisConfig",
    "MLConfig",
    "TradingConfig",
    "SecurityConfig",
    "MonitoringConfig",
    # Enums and metadata
    "ConfigFormat",
    "Environment",
    "ConfigSource",
    "ValidationResult",
    # Providers
    "ConfigProvider",
    "FileProvider",
    "EnvironmentProvider",
    "URLProvider",
    "ConfigProviderRegistry",
    "provider_registry",
    # Factory functions
    "create_config_manager",
    "load_config",
    "load_config_from_env",
    "create_config_from_dict",
    # Utility functions
    "get_default_config_path",
    "validate_config",
    "setup_logging_from_config",
    "get_env_or_default",
    "get_feature_flag",
    "create_default_config",
    "is_production",
    "is_development",
    "is_testing",
    # Path utilities
    "PathManager",
    "ConfigProcessor",
    # Constants and defaults
    "APP_NAME",
    "APP_VERSION",
    "APP_ENV",
    "AppEnvironment",
    "DEFAULT_TRADING_CONFIG",
    "DEFAULT_ML_CONFIG",
    "FEATURE_FLAGS",
    "get_app_info",
    "get_default_config",
]

# Add cloud providers to exports if available
if _AWS_AVAILABLE:
    __all__.append("AWSParameterStoreProvider")

if _CONSUL_AVAILABLE:
    __all__.append("ConsulProvider")


# Package metadata for setup.py
PACKAGE_INFO = {
    "name": "fks-config",
    "version": __version__,
    "description": "FKS Trading Systems Configuration Management",
    "long_description": __doc__,
    "author": __author__,
    "url": "https://github.com/fks-trading/fks-config",
    "packages": ["fks.config"],
    "install_requires": ["loguru>=0.6.0", "pyyaml>=6.0", "toml>=0.10.0"],
    "extras_require": {
        "aws": ["boto3>=1.20.0"],
        "consul": ["python-consul>=1.1.0"],
        "all": ["boto3>=1.20.0", "python-consul>=1.1.0"],
    },
    "python_requires": ">=3.8",
    "classifiers": [
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Systems Administration",
    ],
}


# Initialize package
def _initialize_package():
    """Initialize the package on import."""
    # Set up basic logging if not already configured
    try:
        from loguru import logger

        # Only add handler if none exist
        if not logger._core.handlers:
            logger.add(sys.stderr, level="INFO")
    except ImportError:
        pass


# Run initialization
_initialize_package()
