"""
Application Lifecycle Management Package.

This package provides comprehensive lifecycle management for applications including:
- System initialization and configuration loading
- Application lifespan management with startup/shutdown hooks
- Graceful teardown and resource cleanup
- Service registry and dependency management
- Error handling and recovery mechanisms
"""

# Import core initialization functionality
from .initialization import (
    CORE_COMPONENTS,
    DEFAULT_CONFIG_PATH,
    DEFAULT_ENVIRONMENT,
    DEFAULT_LOG_LEVEL,
    check_dependencies,
    initialize,
    load_configuration,
    setup_database_connections,
    validate_environment,
)

# Import lifespan management
from .lifespan import (
    ApplicationLifecycle,
    get_app_lifecycle,
    get_lifespan_manager,
    get_sync_lifespan_manager,
    run_async,
    setup_fastapi_lifespan,
)

# Import the main lifecycle manager
from .manager import (
    LifecycleManager,
    LifecyclePhase,
    LifecycleState,
    create_lifecycle_manager,
    get_lifecycle_manager,
)

# Import teardown functionality
from .teardown import (
    DEFAULT_TEARDOWN_TIMEOUT,
    emergency_shutdown,
    get_teardown_state,
    shutdown_cache,
    shutdown_databases,
    shutdown_event_system,
    shutdown_filesystem,
    shutdown_scheduler,
    shutdown_security,
    teardown,
)

# Version information
__version__ = "1.0.0"
__author__ = "Framework Lifecycle Team"

# Global lifecycle manager instance
_global_lifecycle_manager = None


def get_global_lifecycle_manager() -> "LifecycleManager":
    """
    Get the global lifecycle manager instance.

    Returns:
        LifecycleManager: Global lifecycle manager instance
    """
    global _global_lifecycle_manager
    if _global_lifecycle_manager is None:
        _global_lifecycle_manager = LifecycleManager()
    return _global_lifecycle_manager


# Convenience aliases
lifecycle_manager = get_global_lifecycle_manager()
app_lifecycle = get_app_lifecycle()

# Export all public symbols
__all__ = [
    # Core lifecycle management
    "LifecycleManager",
    "LifecycleState",
    "LifecyclePhase",
    "get_lifecycle_manager",
    "create_lifecycle_manager",
    # Initialization functions
    "initialize",
    "validate_environment",
    "load_configuration",
    "check_dependencies",
    "setup_database_connections",
    # Lifespan management
    "get_lifespan_manager",
    "get_sync_lifespan_manager",
    "setup_fastapi_lifespan",
    "run_async",
    "ApplicationLifecycle",
    "get_app_lifecycle",
    # Teardown functions
    "teardown",
    "emergency_shutdown",
    "get_teardown_state",
    "shutdown_databases",
    "shutdown_cache",
    "shutdown_event_system",
    "shutdown_scheduler",
    "shutdown_filesystem",
    "shutdown_security",
    # Constants
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_ENVIRONMENT",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_TEARDOWN_TIMEOUT",
    "CORE_COMPONENTS",
    # Global instances
    "lifecycle_manager",
    "app_lifecycle",
    "get_global_lifecycle_manager",
]

# Package metadata
__package_info__ = {
    "name": "framework.lifecycle",
    "version": __version__,
    "description": "Comprehensive application lifecycle management framework",
    "features": [
        "Complete application initialization and startup",
        "Graceful shutdown and resource cleanup",
        "Service dependency management",
        "Configuration loading and validation",
        "Database connection management",
        "Event-driven lifecycle hooks",
        "Error handling and recovery",
        "FastAPI lifespan integration",
        "Async and sync support",
        "Component-based architecture",
    ],
    "dependencies": [
        "loguru",  # Logging
        "pyyaml",  # Configuration loading
        "sqlalchemy",  # Database connections (optional)
    ],
}


def get_package_info():
    """Get package information and features."""
    return __package_info__.copy()


# Lifecycle hooks for package-level events
_package_hooks = {
    "on_import": [],
    "on_initialize": [],
    "on_teardown": [],
}


def register_package_hook(event: str, callback):
    """
    Register a package-level lifecycle hook.

    Args:
        event: Event name ('on_import', 'on_initialize', 'on_teardown')
        callback: Function to call when event occurs
    """
    if event in _package_hooks:
        _package_hooks[event].append(callback)


def _fire_package_hook(event: str, *args, **kwargs):
    """Fire package-level lifecycle hooks."""
    for callback in _package_hooks.get(event, []):
        try:
            callback(*args, **kwargs)
        except Exception as e:
            try:
                from loguru import logger

                logger.warning(f"Package hook {event} failed: {e}")
            except ImportError:
                import logging

                logging.getLogger(__name__).warning(f"Package hook {event} failed: {e}")


# Fire on_import hooks when package is imported
_fire_package_hook("on_import")


# Auto-configuration based on environment
def auto_configure():
    """
    Auto-configure the lifecycle system based on environment.

    This function attempts to detect the runtime environment and
    configure appropriate defaults for the lifecycle system.
    """
    import os

    # Detect if we're in a FastAPI environment
    try:
        import fastapi

        os.environ.setdefault("LIFECYCLE_FRAMEWORK", "fastapi")
    except ImportError:
        pass

    # Detect if we're in a Flask environment
    try:
        import flask

        if "LIFECYCLE_FRAMEWORK" not in os.environ:
            os.environ.setdefault("LIFECYCLE_FRAMEWORK", "flask")
    except ImportError:
        pass

    # Set default framework if none detected
    os.environ.setdefault("LIFECYCLE_FRAMEWORK", "generic")

    # Configure default log level
    os.environ.setdefault("APP_LOG_LEVEL", DEFAULT_LOG_LEVEL)

    # Configure default environment
    os.environ.setdefault("ENVIRONMENT", DEFAULT_ENVIRONMENT)


# Auto-configure on import
auto_configure()


# Quick start functions for common use cases
def quick_start(config_path: str = None, components: list = None) -> "LifecycleManager":
    """
    Quick start function for simple applications.

    Args:
        config_path: Path to configuration file
        components: List of components to initialize

    Returns:
        LifecycleManager: Configured and initialized lifecycle manager
    """
    manager = get_global_lifecycle_manager()
    manager.initialize(config_path=config_path, components=components)
    return manager


async def async_quick_start(
    config_path: str = None, components: list = None
) -> "LifecycleManager":
    """
    Async quick start function for async applications.

    Args:
        config_path: Path to configuration file
        components: List of components to initialize

    Returns:
        LifecycleManager: Configured and initialized lifecycle manager
    """
    manager = get_global_lifecycle_manager()
    await manager.async_initialize(config_path=config_path, components=components)
    return manager


def quick_shutdown():
    """Quick shutdown function for simple applications."""
    manager = get_global_lifecycle_manager()
    manager.shutdown()


async def async_quick_shutdown():
    """Async quick shutdown function for async applications."""
    manager = get_global_lifecycle_manager()
    await manager.async_shutdown()


# Context manager for complete lifecycle management
class lifecycle_context:
    """
    Context manager for complete application lifecycle.

    This context manager handles initialization on entry and
    teardown on exit, providing a complete lifecycle wrapper.
    """

    def __init__(self, config_path: str = None, components: list = None):
        self.config_path = config_path
        self.components = components
        self.manager = None

    def __enter__(self):
        """Initialize the lifecycle on context entry."""
        self.manager = quick_start(self.config_path, self.components)
        return self.manager

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Teardown the lifecycle on context exit."""
        if self.manager:
            self.manager.shutdown()


class async_lifecycle_context:
    """
    Async context manager for complete application lifecycle.

    This async context manager handles initialization on entry and
    teardown on exit, providing a complete lifecycle wrapper for async apps.
    """

    def __init__(self, config_path: str = None, components: list = None):
        self.config_path = config_path
        self.components = components
        self.manager = None

    async def __aenter__(self):
        """Initialize the lifecycle on context entry."""
        self.manager = await async_quick_start(self.config_path, self.components)
        return self.manager

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Teardown the lifecycle on context exit."""
        if self.manager:
            await self.manager.async_shutdown()


# Health check functionality
def health_check() -> dict:
    """
    Perform a health check on the lifecycle system.

    Returns:
        dict: Health check results with status and details
    """
    manager = get_global_lifecycle_manager()
    return manager.health_check()


# Add convenience exports
__all__.extend(
    [
        "quick_start",
        "async_quick_start",
        "quick_shutdown",
        "async_quick_shutdown",
        "lifecycle_context",
        "async_lifecycle_context",
        "health_check",
        "register_package_hook",
        "get_package_info",
        "auto_configure",
    ]
)

# Logging configuration check
try:
    from loguru import logger

    logger.debug(f"Framework lifecycle package loaded successfully")
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logging.getLogger(__name__).info(f"Framework lifecycle package loaded successfully")
