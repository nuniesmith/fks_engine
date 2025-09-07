"""
Framework Services Package

A comprehensive package for service lifecycle management, registry patterns,
and microservice templates.

This package provides:
- Service Registry: Centralized service lifecycle management with dependency resolution
- Strategy Registry: Trading strategy registration and management
- Service Template: Robust microservice template with health endpoints
- Lifecycle Management: Context managers and graceful shutdown handling

Example Usage:
    Basic service registration:
    ```python
    from framework.services import get_service_registry

    registry = get_service_registry()
    registry.register("my_service", service_instance, startup_priority=10)

    async with registry.lifecycle():
        # All services started automatically
        await do_work()
        # All services stopped automatically
    ```

    Microservice template:
    ```python
    from framework.services import ServiceTemplate, ServiceConfig

    config = ServiceConfig(
        name="my_api",
        port=8080,
        enable_metrics=True
    )

    service = ServiceTemplate(config)
    service.run()
    ```

    Strategy registration:
    ```python
    from framework.services import get_strategy_registry

    strategy_registry = get_strategy_registry()
    strategy_registry.register(
        "momentum_strategy",
        MomentumStrategy,
        metadata={"timeframe": "1h", "market": "crypto"},
        tags={"momentum", "trend_following"}
    )
    ```
"""

import logging
from typing import Optional

# Package metadata
__version__ = "1.0.0"
__author__ = "Framework Team"
__email__ = "team@framework.dev"
__description__ = "Service lifecycle management and microservice templates"

# Configure package logger
_logger = logging.getLogger(__name__)

# Import core components from registry module
try:
    from .registry import (
        ServiceInfo,
        ServiceProtocol,
        ServiceRegistry,
        ServiceStatus,
        StrategyInfo,
        StrategyRegistry,
        get_service_registry,
        get_strategy_registry,
    )

    _REGISTRY_AVAILABLE = True
    _logger.debug("Registry module loaded successfully")

except ImportError as e:
    _logger.error(f"Failed to import registry module: {e}")
    _REGISTRY_AVAILABLE = False

    # Provide stub implementations to prevent import errors
    class ServiceRegistry:
        def __init__(self):
            raise ImportError("Registry module not available")

    class StrategyRegistry:
        def __init__(self):
            raise ImportError("Registry module not available")

    def get_service_registry():
        raise ImportError("Registry module not available")

    def get_strategy_registry():
        raise ImportError("Registry module not available")


# Import service template components
try:
    from .template import (
        HealthEndpoint,
        ServiceConfig,
        ServiceTemplate,
        start,
        start_template_service,
    )

    _TEMPLATE_AVAILABLE = True
    _logger.debug("Template module loaded successfully")

except ImportError as e:
    _logger.error(f"Failed to import template module: {e}")
    _TEMPLATE_AVAILABLE = False

    # Provide stub implementations
    class ServiceTemplate:
        def __init__(self, *args, **kwargs):
            raise ImportError("Template module not available")

    class ServiceConfig:
        def __init__(self, *args, **kwargs):
            raise ImportError("Template module not available")

    class HealthEndpoint:
        def __init__(self, *args, **kwargs):
            raise ImportError("Template module not available")

    def start_template_service(*args, **kwargs):
        raise ImportError("Template module not available")

    def start(*args, **kwargs):
        raise ImportError("Template module not available")


# Public API - these are the symbols that will be available when doing "from framework.services import *"
__all__ = [
    # Metadata
    "__version__",
    "__author__",
    "__email__",
    "__description__",
    # Registry components
    "ServiceRegistry",
    "StrategyRegistry",
    "ServiceStatus",
    "ServiceInfo",
    "StrategyInfo",
    "ServiceProtocol",
    "get_service_registry",
    "get_strategy_registry",
    # Template components
    "ServiceTemplate",
    "ServiceConfig",
    "HealthEndpoint",
    "start_template_service",
    "start",
    # Convenience functions
    "create_service",
    "register_service",
    "register_strategy",
    "check_availability",
]


def check_availability() -> dict:
    """
    Check availability of package components.

    Returns:
        Dictionary with availability status of each component
    """
    return {
        "registry": _REGISTRY_AVAILABLE,
        "template": _TEMPLATE_AVAILABLE,
        "version": __version__,
    }


def create_service(
    name: str,
    port: int = 8080,
    environment: str = "development",
    version: str = "1.0.0",
    **kwargs,
) -> Optional[ServiceTemplate]:
    """
    Convenience function to create a service template with common configuration.

    Args:
        name: Service name
        port: Port to run on
        environment: Environment (development, staging, production)
        version: Service version
        **kwargs: Additional ServiceConfig parameters

    Returns:
        ServiceTemplate instance or None if template module not available

    Example:
        ```python
        service = create_service("my_api", port=8080, enable_metrics=True)
        service.run()
        ```
    """
    if not _TEMPLATE_AVAILABLE:
        _logger.error("Template module not available, cannot create service")
        return None

    config = ServiceConfig(
        name=name, port=port, environment=environment, version=version, **kwargs
    )

    return ServiceTemplate(config)


def register_service(
    name: str,
    service_instance,
    startup_priority: int = 100,
    dependencies: Optional[set] = None,
    health_check: Optional[callable] = None,
) -> bool:
    """
    Convenience function to register a service with the global registry.

    Args:
        name: Service name
        service_instance: Service object to register
        startup_priority: Startup priority (lower = earlier)
        dependencies: Set of service names this depends on
        health_check: Optional health check function

    Returns:
        True if registration successful, False otherwise

    Example:
        ```python
        register_service("database", db_service, startup_priority=1)
        register_service("api", api_service, startup_priority=10, dependencies={"database"})
        ```
    """
    if not _REGISTRY_AVAILABLE:
        _logger.error("Registry module not available, cannot register service")
        return False

    try:
        registry = get_service_registry()
        registry.register(
            name=name,
            service=service_instance,
            startup_priority=startup_priority,
            dependencies=dependencies,
            health_check=health_check,
        )
        return True
    except Exception as e:
        _logger.error(f"Failed to register service {name}: {e}")
        return False


def register_strategy(
    name: str,
    strategy_class,
    metadata: Optional[dict] = None,
    description: Optional[str] = None,
    version: str = "1.0.0",
    tags: Optional[set] = None,
) -> bool:
    """
    Convenience function to register a strategy with the global registry.

    Args:
        name: Strategy name
        strategy_class: Strategy class to register
        metadata: Additional metadata
        description: Human-readable description
        version: Strategy version
        tags: Set of tags for categorization

    Returns:
        True if registration successful, False otherwise

    Example:
        ```python
        register_strategy(
            "momentum_v1",
            MomentumStrategy,
            description="Momentum trading strategy",
            tags={"momentum", "trend"},
            metadata={"timeframe": "1h"}
        )
        ```
    """
    if not _REGISTRY_AVAILABLE:
        _logger.error("Registry module not available, cannot register strategy")
        return False

    try:
        registry = get_strategy_registry()
        registry.register(
            name=name,
            strategy_class=strategy_class,
            metadata=metadata,
            description=description,
            version=version,
            tags=tags,
        )
        return True
    except Exception as e:
        _logger.error(f"Failed to register strategy {name}: {e}")
        return False


# Package initialization
def _initialize_package():
    """Initialize the package and log status."""
    _logger.info(f"Framework Services v{__version__} initialized")

    availability = check_availability()
    available_components = [
        name
        for name, available in availability.items()
        if available and name != "version"
    ]

    if available_components:
        _logger.info(f"Available components: {', '.join(available_components)}")
    else:
        _logger.warning("No components available - check dependencies")

    # Log any missing dependencies
    if not _REGISTRY_AVAILABLE:
        _logger.warning(
            "Registry functionality unavailable - service and strategy registration disabled"
        )

    if not _TEMPLATE_AVAILABLE:
        _logger.warning(
            "Template functionality unavailable - microservice templates disabled"
        )


# Initialize package on import
_initialize_package()


# Convenience shortcuts for common patterns
class Services:
    """
    Namespace for service-related utilities.

    Provides convenient access to registries and common operations.
    """

    @staticmethod
    def registry():
        """Get the service registry."""
        return get_service_registry() if _REGISTRY_AVAILABLE else None

    @staticmethod
    def strategies():
        """Get the strategy registry."""
        return get_strategy_registry() if _REGISTRY_AVAILABLE else None

    @staticmethod
    def create(name: str, **kwargs):
        """Create a service template."""
        return create_service(name, **kwargs)

    @staticmethod
    def register(name: str, service, **kwargs):
        """Register a service."""
        return register_service(name, service, **kwargs)


# Create singleton instance for convenience
services = Services()

# Add to __all__ for export
__all__.extend(["Services", "services"])
