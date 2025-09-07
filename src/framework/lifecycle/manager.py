"""
Lifecycle Manager - Central orchestrator for application lifecycle.

This module provides the main LifecycleManager class that coordinates
initialization, lifespan management, and teardown across the entire system.
It serves as the primary interface for managing application lifecycle.
"""

import asyncio
import threading
import time
import traceback
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger("framework.lifecycle.manager")

from .initialization import CORE_COMPONENTS
from .initialization import initialize as init_system
from .lifespan import ApplicationLifecycle, get_app_lifecycle
from .teardown import (
    emergency_shutdown,
    get_teardown_state,
)
from .teardown import teardown as teardown_system


class LifecyclePhase(Enum):
    """Lifecycle phases for the application."""

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    EMERGENCY_SHUTDOWN = "emergency_shutdown"


class LifecycleState(Enum):
    """Overall lifecycle state."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


@dataclass
class LifecycleContext:
    """Context information for the current lifecycle state."""

    phase: LifecyclePhase = LifecyclePhase.UNINITIALIZED
    state: LifecycleState = LifecycleState.HEALTHY
    start_time: Optional[datetime] = None
    last_state_change: Optional[datetime] = None
    initialization_context: Dict[str, Any] = field(default_factory=dict)
    components: Dict[str, Any] = field(default_factory=dict)
    services: List[Any] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def update_phase(self, new_phase: LifecyclePhase):
        """Update the current phase and timestamp."""
        self.phase = new_phase
        self.last_state_change = datetime.now()

    def update_state(self, new_state: LifecycleState):
        """Update the current state and timestamp."""
        self.state = new_state
        self.last_state_change = datetime.now()

    def add_error(self, error: str):
        """Add an error to the context."""
        self.errors.append(f"{datetime.now().isoformat()}: {error}")
        if self.state == LifecycleState.HEALTHY:
            self.update_state(LifecycleState.DEGRADED)

    def add_warning(self, warning: str):
        """Add a warning to the context."""
        self.warnings.append(f"{datetime.now().isoformat()}: {warning}")


class LifecycleEventType(Enum):
    """Types of lifecycle events."""

    BEFORE_INIT = "before_init"
    AFTER_INIT = "after_init"
    BEFORE_START = "before_start"
    AFTER_START = "after_start"
    BEFORE_STOP = "before_stop"
    AFTER_STOP = "after_stop"
    ON_ERROR = "on_error"
    ON_HEALTH_CHECK = "on_health_check"


@dataclass
class LifecycleEvent:
    """Lifecycle event data."""

    event_type: LifecycleEventType
    timestamp: datetime
    context: LifecycleContext
    data: Dict[str, Any] = field(default_factory=dict)


class LifecycleManager:
    """
    Central manager for application lifecycle.

    This class orchestrates the complete lifecycle of an application,
    from initialization through running to graceful shutdown.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        components: Optional[List[str]] = None,
        auto_recovery: bool = True,
        health_check_interval: float = 30.0,
    ):
        """
        Initialize the lifecycle manager.

        Args:
            config_path: Path to configuration file
            components: List of components to manage
            auto_recovery: Whether to attempt automatic recovery from errors
            health_check_interval: Interval for periodic health checks (seconds)
        """
        self.config_path = config_path
        self.components = components or CORE_COMPONENTS.copy()
        self.auto_recovery = auto_recovery
        self.health_check_interval = health_check_interval

        # Lifecycle context
        self.context = LifecycleContext()
        self.context.start_time = datetime.now()

        # Thread safety
        self._lock = threading.RLock()
        self._shutdown_event = threading.Event()

        # Event hooks
        self._event_handlers: Dict[LifecycleEventType, List[Callable]] = {
            event_type: [] for event_type in LifecycleEventType
        }

        # Application lifecycle integration
        self.app_lifecycle = get_app_lifecycle()

        # Background tasks
        self._health_check_task: Optional[asyncio.Task] = None
        self._background_tasks: Set[asyncio.Task] = set()

        # Recovery state
        self._recovery_attempts = 0
        self._max_recovery_attempts = 3

        logger.info("LifecycleManager initialized")

    def register_event_handler(
        self, event_type: LifecycleEventType, handler: Callable[[LifecycleEvent], None]
    ):
        """
        Register an event handler for lifecycle events.

        Args:
            event_type: Type of event to handle
            handler: Function to call when event occurs
        """
        with self._lock:
            self._event_handlers[event_type].append(handler)
            logger.debug(f"Registered handler for {event_type.value}")

    def _fire_event(self, event_type: LifecycleEventType, **event_data):
        """Fire a lifecycle event to all registered handlers."""
        event = LifecycleEvent(
            event_type=event_type,
            timestamp=datetime.now(),
            context=self.context,
            data=event_data,
        )

        for handler in self._event_handlers[event_type]:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler for {event_type.value} failed: {e}")

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the lifecycle manager.

        Returns:
            Dict containing current status information
        """
        with self._lock:
            uptime = (datetime.now() - self.context.start_time).total_seconds()

            return {
                "phase": self.context.phase.value,
                "state": self.context.state.value,
                "uptime_seconds": uptime,
                "last_state_change": (
                    self.context.last_state_change.isoformat()
                    if self.context.last_state_change
                    else None
                ),
                "components_count": len(self.context.components),
                "services_count": len(self.context.services),
                "errors_count": len(self.context.errors),
                "warnings_count": len(self.context.warnings),
                "recovery_attempts": self._recovery_attempts,
                "auto_recovery": self.auto_recovery,
                "is_healthy": (
                    self.context.state
                    in [LifecycleState.HEALTHY, LifecycleState.DEGRADED]
                ),
            }

    def initialize(
        self,
        config_path: Optional[str] = None,
        components: Optional[List[str]] = None,
        additional_config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Initialize the application synchronously.

        Args:
            config_path: Path to configuration file
            components: List of components to initialize
            additional_config: Additional configuration to merge

        Returns:
            bool: True if initialization successful
        """
        with self._lock:
            if self.context.phase != LifecyclePhase.UNINITIALIZED:
                logger.warning(
                    f"Cannot initialize from phase {self.context.phase.value}"
                )
                return False

            self.context.update_phase(LifecyclePhase.INITIALIZING)

        self._fire_event(LifecycleEventType.BEFORE_INIT)

        try:
            # Use provided parameters or fall back to instance defaults
            config_path = config_path or self.config_path
            components = components or self.components

            logger.info("Starting system initialization")

            # Initialize the system
            success, init_context = init_system(
                components=components,
                config_path=config_path,
                additional_config=additional_config,
            )

            with self._lock:
                if success:
                    self.context.update_phase(LifecyclePhase.INITIALIZED)
                    self.context.initialization_context = init_context
                    self.context.components = init_context.get("components", {})

                    # Register components with app lifecycle if they have start/stop methods
                    for name, component in self.context.components.items():
                        if (
                            component
                            and hasattr(component, "start")
                            or hasattr(component, "start_async")
                        ):
                            self.app_lifecycle.register_service(component)
                            self.context.services.append(component)

                    logger.info("Lifecycle initialization completed successfully")
                else:
                    self.context.update_phase(LifecyclePhase.ERROR)
                    self.context.update_state(LifecycleState.UNHEALTHY)

                    # Add errors from initialization
                    failed_components = init_context.get("failed_components", {})
                    for component, error in failed_components.items():
                        self.context.add_error(f"Component {component} failed: {error}")

                    logger.error("Lifecycle initialization failed")

            self._fire_event(
                LifecycleEventType.AFTER_INIT, success=success, context=init_context
            )
            return success

        except Exception as e:
            with self._lock:
                self.context.update_phase(LifecyclePhase.ERROR)
                self.context.update_state(LifecycleState.CRITICAL)
                self.context.add_error(f"Initialization exception: {str(e)}")

            logger.error(f"Lifecycle initialization failed with exception: {e}")
            self._fire_event(
                LifecycleEventType.ON_ERROR, error=str(e), phase="initialization"
            )
            return False

    async def async_initialize(
        self,
        config_path: Optional[str] = None,
        components: Optional[List[str]] = None,
        additional_config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Initialize the application asynchronously.

        Args:
            config_path: Path to configuration file
            components: List of components to initialize
            additional_config: Additional configuration to merge

        Returns:
            bool: True if initialization successful
        """
        # Run initialization in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.initialize, config_path, components, additional_config
        )

    async def start_async(self) -> bool:
        """
        Start the application services asynchronously.

        Returns:
            bool: True if startup successful
        """
        with self._lock:
            if self.context.phase != LifecyclePhase.INITIALIZED:
                logger.warning(f"Cannot start from phase {self.context.phase.value}")
                return False

            self.context.update_phase(LifecyclePhase.STARTING)

        self._fire_event(LifecycleEventType.BEFORE_START)

        try:
            logger.info("Starting application services")

            # Start all registered services
            await self.app_lifecycle.start_async()

            # Start background health checks if enabled
            if self.health_check_interval > 0:
                self._health_check_task = asyncio.create_task(
                    self._periodic_health_check()
                )
                self._background_tasks.add(self._health_check_task)

            with self._lock:
                self.context.update_phase(LifecyclePhase.RUNNING)

            logger.info("Application services started successfully")
            self._fire_event(LifecycleEventType.AFTER_START)
            return True

        except Exception as e:
            with self._lock:
                self.context.update_phase(LifecyclePhase.ERROR)
                self.context.update_state(LifecycleState.CRITICAL)
                self.context.add_error(f"Startup exception: {str(e)}")

            logger.error(f"Application startup failed: {e}")
            self._fire_event(LifecycleEventType.ON_ERROR, error=str(e), phase="startup")
            return False

    def start_sync(self) -> bool:
        """
        Start the application services synchronously.

        Returns:
            bool: True if startup successful
        """
        with self._lock:
            if self.context.phase != LifecyclePhase.INITIALIZED:
                logger.warning(f"Cannot start from phase {self.context.phase.value}")
                return False

            self.context.update_phase(LifecyclePhase.STARTING)

        self._fire_event(LifecycleEventType.BEFORE_START)

        try:
            logger.info("Starting application services (sync)")

            # Start all registered services
            self.app_lifecycle.start_sync()

            with self._lock:
                self.context.update_phase(LifecyclePhase.RUNNING)

            logger.info("Application services started successfully")
            self._fire_event(LifecycleEventType.AFTER_START)
            return True

        except Exception as e:
            with self._lock:
                self.context.update_phase(LifecyclePhase.ERROR)
                self.context.update_state(LifecycleState.CRITICAL)
                self.context.add_error(f"Startup exception: {str(e)}")

            logger.error(f"Application startup failed: {e}")
            self._fire_event(LifecycleEventType.ON_ERROR, error=str(e), phase="startup")
            return False

    async def stop_async(self) -> bool:
        """
        Stop the application services asynchronously.

        Returns:
            bool: True if shutdown successful
        """
        with self._lock:
            if self.context.phase not in [LifecyclePhase.RUNNING, LifecyclePhase.ERROR]:
                logger.warning(f"Cannot stop from phase {self.context.phase.value}")
                return False

            self.context.update_phase(LifecyclePhase.STOPPING)

        self._fire_event(LifecycleEventType.BEFORE_STOP)

        try:
            logger.info("Stopping application services")

            # Signal shutdown to background tasks
            self._shutdown_event.set()

            # Cancel background tasks
            for task in self._background_tasks:
                if not task.done():
                    task.cancel()

            # Wait for background tasks to complete
            if self._background_tasks:
                await asyncio.gather(*self._background_tasks, return_exceptions=True)

            # Stop all registered services
            await self.app_lifecycle.stop_async()

            with self._lock:
                self.context.update_phase(LifecyclePhase.STOPPED)

            logger.info("Application services stopped successfully")
            self._fire_event(LifecycleEventType.AFTER_STOP)
            return True

        except Exception as e:
            with self._lock:
                self.context.update_phase(LifecyclePhase.ERROR)
                self.context.add_error(f"Shutdown exception: {str(e)}")

            logger.error(f"Application shutdown failed: {e}")
            self._fire_event(
                LifecycleEventType.ON_ERROR, error=str(e), phase="shutdown"
            )
            return False

    def stop_sync(self) -> bool:
        """
        Stop the application services synchronously.

        Returns:
            bool: True if shutdown successful
        """
        with self._lock:
            if self.context.phase not in [LifecyclePhase.RUNNING, LifecyclePhase.ERROR]:
                logger.warning(f"Cannot stop from phase {self.context.phase.value}")
                return False

            self.context.update_phase(LifecyclePhase.STOPPING)

        self._fire_event(LifecycleEventType.BEFORE_STOP)

        try:
            logger.info("Stopping application services (sync)")

            # Signal shutdown to background tasks
            self._shutdown_event.set()

            # Stop all registered services
            self.app_lifecycle.stop_sync()

            with self._lock:
                self.context.update_phase(LifecyclePhase.STOPPED)

            logger.info("Application services stopped successfully")
            self._fire_event(LifecycleEventType.AFTER_STOP)
            return True

        except Exception as e:
            with self._lock:
                self.context.update_phase(LifecyclePhase.ERROR)
                self.context.add_error(f"Shutdown exception: {str(e)}")

            logger.error(f"Application shutdown failed: {e}")
            self._fire_event(
                LifecycleEventType.ON_ERROR, error=str(e), phase="shutdown"
            )
            return False

    def shutdown(self) -> bool:
        """
        Perform complete system shutdown including teardown.

        Returns:
            bool: True if shutdown successful
        """
        logger.info("Beginning complete system shutdown")

        try:
            # Stop services first
            if self.context.phase == LifecyclePhase.RUNNING:
                self.stop_sync()

            # Perform system teardown
            success = teardown_system(components=self.components)

            with self._lock:
                if success:
                    self.context.update_phase(LifecyclePhase.STOPPED)
                    logger.info("Complete system shutdown successful")
                else:
                    self.context.update_phase(LifecyclePhase.ERROR)
                    self.context.add_error("System teardown failed")
                    logger.error("System teardown failed")

            return success

        except Exception as e:
            with self._lock:
                self.context.update_phase(LifecyclePhase.ERROR)
                self.context.add_error(f"Shutdown exception: {str(e)}")

            logger.error(f"Complete system shutdown failed: {e}")
            return False

    async def async_shutdown(self) -> bool:
        """
        Perform complete system shutdown asynchronously.

        Returns:
            bool: True if shutdown successful
        """
        # Stop services first
        if self.context.phase == LifecyclePhase.RUNNING:
            await self.stop_async()

        # Run teardown in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.shutdown)

    def emergency_shutdown(self):
        """Perform emergency shutdown of the system."""
        logger.warning("Performing emergency shutdown")

        with self._lock:
            self.context.update_phase(LifecyclePhase.EMERGENCY_SHUTDOWN)
            self.context.update_state(LifecycleState.CRITICAL)

        emergency_shutdown()

    def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the system.

        Returns:
            Dict containing health check results
        """
        with self._lock:
            status = self.get_status()

            # Gather component health
            component_health = {}
            for name, component in self.context.components.items():
                if hasattr(component, "health_check"):
                    try:
                        component_health[name] = component.health_check()
                    except Exception as e:
                        component_health[name] = {"status": "error", "error": str(e)}
                else:
                    component_health[name] = {"status": "unknown"}

            # Get teardown state
            teardown_state = get_teardown_state()

            health_data = {
                "timestamp": datetime.now().isoformat(),
                "overall_status": status,
                "components": component_health,
                "teardown_state": teardown_state,
                "recent_errors": self.context.errors[-5:],  # Last 5 errors
                "recent_warnings": self.context.warnings[-5:],  # Last 5 warnings
            }

        self._fire_event(LifecycleEventType.ON_HEALTH_CHECK, health_data=health_data)
        return health_data

    async def _periodic_health_check(self):
        """Periodic health check background task."""
        logger.info(
            f"Starting periodic health checks every {self.health_check_interval}s"
        )

        while not self._shutdown_event.is_set():
            try:
                health_data = self.health_check()

                # Check for degraded health and attempt recovery if enabled
                if (
                    self.auto_recovery
                    and self.context.state
                    in [LifecycleState.DEGRADED, LifecycleState.UNHEALTHY]
                    and self._recovery_attempts < self._max_recovery_attempts
                ):

                    logger.warning("Attempting automatic recovery")
                    await self._attempt_recovery()

                # Wait for next check or shutdown signal
                await asyncio.wait_for(
                    asyncio.Event().wait(), timeout=self.health_check_interval
                )

            except asyncio.TimeoutError:
                # Expected timeout, continue loop
                continue
            except asyncio.CancelledError:
                logger.info("Health check task cancelled")
                break
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                with self._lock:
                    self.context.add_error(f"Health check failed: {str(e)}")

    async def _attempt_recovery(self):
        """Attempt to recover from degraded state."""
        self._recovery_attempts += 1
        logger.info(
            f"Recovery attempt {self._recovery_attempts}/{self._max_recovery_attempts}"
        )

        try:
            # Simple recovery: restart services if possible
            if self.context.phase == LifecyclePhase.RUNNING:
                logger.info("Attempting service restart for recovery")
                await self.stop_async()
                await asyncio.sleep(1)  # Brief pause
                success = await self.start_async()

                if success:
                    self._recovery_attempts = 0  # Reset on successful recovery
                    with self._lock:
                        self.context.update_state(LifecycleState.HEALTHY)
                    logger.info("Automatic recovery successful")
                else:
                    logger.warning("Automatic recovery failed")

        except Exception as e:
            logger.error(f"Recovery attempt failed: {e}")
            with self._lock:
                self.context.add_error(f"Recovery failed: {str(e)}")

    @asynccontextmanager
    async def lifespan_context(self):
        """
        Async context manager for complete lifecycle management.

        This can be used as a FastAPI lifespan manager.
        """
        try:
            # Initialize if not already done
            if self.context.phase == LifecyclePhase.UNINITIALIZED:
                await self.async_initialize()

            # Start services
            await self.start_async()

            yield

        finally:
            # Always attempt graceful shutdown
            await self.async_shutdown()

    @contextmanager
    def sync_lifespan_context(self):
        """
        Sync context manager for complete lifecycle management.
        """
        try:
            # Initialize if not already done
            if self.context.phase == LifecyclePhase.UNINITIALIZED:
                self.initialize()

            # Start services
            self.start_sync()

            yield

        finally:
            # Always attempt graceful shutdown
            self.shutdown()


# Factory functions
def create_lifecycle_manager(**kwargs) -> LifecycleManager:
    """
    Create a new lifecycle manager instance.

    Args:
        **kwargs: Arguments to pass to LifecycleManager constructor

    Returns:
        LifecycleManager: New lifecycle manager instance
    """
    return LifecycleManager(**kwargs)


def get_lifecycle_manager() -> LifecycleManager:
    """
    Get a global lifecycle manager instance.

    Returns:
        LifecycleManager: Global lifecycle manager instance
    """
    # This will be implemented in __init__.py to avoid circular imports
    from . import get_global_lifecycle_manager

    return get_global_lifecycle_manager()
