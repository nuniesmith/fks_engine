"""
Service Registry for application lifecycle management.

Provides centralized registration and management of application services,
handling proper startup and shutdown sequencing with dependency management.
"""

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Set,
    Type,
    Union,
)

__all__ = [
    "ServiceRegistry",
    "StrategyRegistry",
    "get_service_registry",
    "get_strategy_registry",
    "ServiceStatus",
    "ServiceInfo",
    "StrategyInfo",
]

_logger = logging.getLogger(__name__)

# Singleton instances
_REGISTRY_INSTANCE: Optional["ServiceRegistry"] = None
_STRATEGY_REGISTRY_INSTANCE: Optional["StrategyRegistry"] = None


class ServiceStatus(Enum):
    """Service status enumeration."""

    REGISTERED = "registered"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class ServiceInfo:
    """Information about a registered service."""

    name: str
    instance: Any
    priority: int
    status: ServiceStatus = ServiceStatus.REGISTERED
    dependencies: Set[str] = field(default_factory=set)
    health_check: Optional[Callable[[], Awaitable[bool]]] = None
    start_time: Optional[datetime] = None
    stop_time: Optional[datetime] = None
    error_message: Optional[str] = None
    restart_count: int = 0


@dataclass
class StrategyInfo:
    """Information about a registered strategy."""

    name: str
    strategy_class: Type
    metadata: Dict[str, Any] = field(default_factory=dict)
    description: Optional[str] = None
    version: str = "1.0.0"
    tags: Set[str] = field(default_factory=set)


class ServiceProtocol(Protocol):
    """Protocol defining the interface for managed services."""

    async def start(self) -> None:
        """Start the service."""
        ...

    async def stop(self) -> None:
        """Stop the service."""
        ...

    async def health_check(self) -> bool:
        """Check if the service is healthy."""
        ...


class ServiceRegistry:
    """
    Enhanced Service Registry for managing application services with dependency resolution.
    """

    def __init__(self):
        self._services: Dict[str, ServiceInfo] = {}
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._shutdown_timeout = 30.0  # seconds
        self._startup_timeout = 60.0  # seconds
        self._health_check_interval = 30.0  # seconds
        self._health_check_task: Optional[asyncio.Task] = None

    def register(
        self,
        name: str,
        service: Any,
        startup_priority: int = 100,
        dependencies: Optional[Set[str]] = None,
        health_check: Optional[Callable[[], Awaitable[bool]]] = None,
    ) -> None:
        """
        Register a service with the registry.

        Args:
            name: Unique identifier for the service
            service: Service instance to register
            startup_priority: Priority for startup sequencing (lower starts earlier)
            dependencies: Set of service names this service depends on
            health_check: Optional health check function
        """
        if name in self._services:
            self._logger.warning(f"Service {name} already registered, will be replaced")

        self._services[name] = ServiceInfo(
            name=name,
            instance=service,
            priority=startup_priority,
            dependencies=dependencies or set(),
            health_check=health_check,
        )

        self._logger.info(f"Registered service: {name} (priority: {startup_priority})")

    def get(self, name: str) -> Optional[Any]:
        """
        Get a service instance by name.

        Args:
            name: Service identifier

        Returns:
            Service instance or None if not found
        """
        service_info = self._services.get(name)
        return service_info.instance if service_info else None

    def get_service_info(self, name: str) -> Optional[ServiceInfo]:
        """
        Get detailed service information by name.

        Args:
            name: Service identifier

        Returns:
            ServiceInfo object or None if not found
        """
        return self._services.get(name)

    def list_services(self) -> List[str]:
        """
        List all registered services.

        Returns:
            List of service names
        """
        return list(self._services.keys())

    def get_services_by_status(self, status: ServiceStatus) -> List[str]:
        """
        Get services filtered by status.

        Args:
            status: Status to filter by

        Returns:
            List of service names with the specified status
        """
        return [name for name, info in self._services.items() if info.status == status]

    def _resolve_startup_order(self) -> List[str]:
        """
        Resolve service startup order considering dependencies and priorities.

        Returns:
            List of service names in startup order

        Raises:
            ValueError: If circular dependencies are detected
        """
        # Topological sort with priority ordering
        in_degree = {name: 0 for name in self._services}
        graph = {name: [] for name in self._services}

        # Build dependency graph
        for name, info in self._services.items():
            for dep in info.dependencies:
                if dep not in self._services:
                    raise ValueError(
                        f"Service {name} depends on unregistered service {dep}"
                    )
                graph[dep].append(name)
                in_degree[name] += 1

        # Kahn's algorithm for topological sort
        queue = [
            (info.priority, name)
            for name, info in self._services.items()
            if in_degree[name] == 0
        ]
        queue.sort()  # Sort by priority
        result = []

        while queue:
            _, current = queue.pop(0)
            result.append(current)

            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    priority = self._services[neighbor].priority
                    queue.append((priority, neighbor))
                    queue.sort()  # Maintain priority order

        if len(result) != len(self._services):
            raise ValueError("Circular dependency detected in service dependencies")

        return result

    async def start_all(self, enable_health_checks: bool = True) -> None:
        """
        Start all registered services in dependency-resolved order.

        Args:
            enable_health_checks: Whether to enable periodic health checking
        """
        self._logger.info("Starting all services")
        startup_order = self._resolve_startup_order()

        started_count = 0
        for name in startup_order:
            if await self._start_service(name):
                started_count += 1
            else:
                self._logger.error(f"Failed to start service {name}, aborting startup")
                await self.stop_all()
                raise RuntimeError(f"Service startup failed at {name}")

        self._logger.info(f"Started {started_count} services")

        if enable_health_checks:
            await self._start_health_monitoring()

    async def _start_service(self, name: str) -> bool:
        """
        Start a single service by name.

        Args:
            name: Service identifier

        Returns:
            True if service was started successfully, False otherwise
        """
        service_info = self._services.get(name)
        if not service_info:
            self._logger.error(f"Cannot start unknown service: {name}")
            return False

        if service_info.status == ServiceStatus.RUNNING:
            self._logger.debug(f"Service {name} is already running")
            return True

        # Check dependencies are running
        for dep in service_info.dependencies:
            dep_info = self._services.get(dep)
            if not dep_info or dep_info.status != ServiceStatus.RUNNING:
                self._logger.error(
                    f"Cannot start {name}: dependency {dep} is not running"
                )
                return False

        service_info.status = ServiceStatus.STARTING
        service = service_info.instance
        self._logger.debug(f"Starting service: {name}")

        try:
            # Try different methods of starting the service
            start_coro = None
            if hasattr(service, "start_async") and inspect.iscoroutinefunction(
                service.start_async
            ):
                start_coro = service.start_async()
            elif hasattr(service, "start_async"):
                start_coro = asyncio.to_thread(service.start_async)
            elif hasattr(service, "start") and inspect.iscoroutinefunction(
                service.start
            ):
                start_coro = service.start()
            elif hasattr(service, "start"):
                start_coro = asyncio.to_thread(service.start)
            else:
                self._logger.warning(f"Service {name} has no start/start_async method")
                service_info.status = ServiceStatus.RUNNING
                service_info.start_time = datetime.now()
                return True

            # Start with timeout
            await asyncio.wait_for(start_coro, timeout=self._startup_timeout)

            service_info.status = ServiceStatus.RUNNING
            service_info.start_time = datetime.now()
            service_info.error_message = None
            self._logger.info(f"Started service: {name}")
            return True

        except asyncio.TimeoutError:
            self._logger.error(f"Timeout starting service {name}")
            service_info.status = ServiceStatus.ERROR
            service_info.error_message = "Startup timeout"
            return False
        except Exception as e:
            self._logger.error(
                f"Error starting service {name}: {str(e)}", exc_info=True
            )
            service_info.status = ServiceStatus.ERROR
            service_info.error_message = str(e)
            return False

    async def stop_all(self) -> None:
        """
        Stop all running services in reverse startup order.
        """
        self._logger.info("Stopping all services")

        # Stop health monitoring
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

        # Get reverse startup order
        try:
            startup_order = self._resolve_startup_order()
            stop_order = list(reversed(startup_order))
        except ValueError:
            # If we can't resolve order due to circular deps, just stop in registration order
            stop_order = list(self._services.keys())

        # Stop services
        for name in stop_order:
            service_info = self._services.get(name)
            if service_info and service_info.status == ServiceStatus.RUNNING:
                await self._stop_service(name)

        self._logger.info("All services stopped")

    async def _stop_service(self, name: str) -> bool:
        """
        Stop a single service by name.

        Args:
            name: Service identifier

        Returns:
            True if service was stopped successfully, False otherwise
        """
        service_info = self._services.get(name)
        if not service_info:
            self._logger.error(f"Cannot stop unknown service: {name}")
            return False

        if service_info.status != ServiceStatus.RUNNING:
            self._logger.debug(f"Service {name} is not running")
            return True

        service_info.status = ServiceStatus.STOPPING
        service = service_info.instance
        self._logger.debug(f"Stopping service: {name}")

        try:
            # Try different methods of stopping the service
            stop_coro = None
            if hasattr(service, "stop_async") and inspect.iscoroutinefunction(
                service.stop_async
            ):
                stop_coro = service.stop_async()
            elif hasattr(service, "stop_async"):
                stop_coro = asyncio.to_thread(service.stop_async)
            elif hasattr(service, "stop") and inspect.iscoroutinefunction(service.stop):
                stop_coro = service.stop()
            elif hasattr(service, "stop"):
                stop_coro = asyncio.to_thread(service.stop)
            elif hasattr(service, "shutdown") and inspect.iscoroutinefunction(
                service.shutdown
            ):
                stop_coro = service.shutdown()
            elif hasattr(service, "shutdown"):
                stop_coro = asyncio.to_thread(service.shutdown)
            else:
                self._logger.warning(
                    f"Service {name} has no stop/stop_async/shutdown method"
                )
                service_info.status = ServiceStatus.STOPPED
                service_info.stop_time = datetime.now()
                return True

            # Stop with timeout
            await asyncio.wait_for(stop_coro, timeout=self._shutdown_timeout)

            service_info.status = ServiceStatus.STOPPED
            service_info.stop_time = datetime.now()
            self._logger.info(f"Stopped service: {name}")
            return True

        except asyncio.TimeoutError:
            self._logger.error(f"Timeout stopping service {name}")
            service_info.status = ServiceStatus.ERROR
            service_info.error_message = "Shutdown timeout"
            return False
        except Exception as e:
            self._logger.error(
                f"Error stopping service {name}: {str(e)}", exc_info=True
            )
            service_info.status = (
                ServiceStatus.STOPPED
            )  # Consider it stopped even with error
            service_info.stop_time = datetime.now()
            service_info.error_message = str(e)
            return False

    def is_service_running(self, name: str) -> bool:
        """
        Check if a service is currently running.

        Args:
            name: Service identifier

        Returns:
            True if the service is running, False otherwise
        """
        service_info = self._services.get(name)
        return service_info.status == ServiceStatus.RUNNING if service_info else False

    async def _start_health_monitoring(self) -> None:
        """Start periodic health monitoring for services with health checks."""
        if self._health_check_task:
            return

        self._health_check_task = asyncio.create_task(self._health_monitor_loop())
        self._logger.info("Started health monitoring")

    async def _health_monitor_loop(self) -> None:
        """Main health monitoring loop."""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._check_all_services_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error in health monitoring: {e}", exc_info=True)

    async def _check_all_services_health(self) -> None:
        """Check health of all running services."""
        for name, service_info in self._services.items():
            if (
                service_info.status == ServiceStatus.RUNNING
                and service_info.health_check
            ):
                try:
                    is_healthy = await service_info.health_check()
                    if not is_healthy:
                        self._logger.warning(f"Service {name} failed health check")
                        service_info.status = ServiceStatus.ERROR
                        service_info.error_message = "Health check failed"
                except Exception as e:
                    self._logger.error(f"Health check error for {name}: {e}")
                    service_info.status = ServiceStatus.ERROR
                    service_info.error_message = f"Health check exception: {str(e)}"

    @asynccontextmanager
    async def lifecycle(self):
        """
        Context manager for service lifecycle management.

        Usage:
            async with registry.lifecycle():
                # Services are started
                await do_work()
                # Services are stopped automatically
        """
        try:
            await self.start_all()
            yield self
        finally:
            await self.stop_all()


class StrategyRegistry:
    """
    Enhanced registry for trading strategies with metadata and filtering capabilities.
    """

    def __init__(self):
        """Initialize the strategy registry."""
        self._strategies: Dict[str, StrategyInfo] = {}
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def register(
        self,
        name: str,
        strategy_class: Type,
        metadata: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        version: str = "1.0.0",
        tags: Optional[Set[str]] = None,
    ) -> None:
        """
        Register a strategy with the registry.

        Args:
            name: Unique identifier for the strategy
            strategy_class: The strategy class implementation
            metadata: Additional metadata about the strategy
            description: Human-readable description
            version: Strategy version
            tags: Set of tags for categorization
        """
        if name in self._strategies:
            self._logger.warning(
                f"Strategy {name} already registered, will be replaced"
            )

        self._strategies[name] = StrategyInfo(
            name=name,
            strategy_class=strategy_class,
            metadata=metadata or {},
            description=description,
            version=version,
            tags=tags or set(),
        )
        self._logger.info(f"Registered strategy: {name} (version: {version})")

    def get_strategy_class(self, name: str) -> Optional[Type]:
        """
        Get a strategy class by name.

        Args:
            name: Strategy identifier

        Returns:
            Strategy class or None if not found
        """
        strategy_info = self._strategies.get(name)
        return strategy_info.strategy_class if strategy_info else None

    def get_strategy_info(self, name: str) -> Optional[StrategyInfo]:
        """
        Get complete strategy information by name.

        Args:
            name: Strategy identifier

        Returns:
            StrategyInfo object or None if not found
        """
        return self._strategies.get(name)

    def create_strategy_instance(self, name: str, **kwargs) -> Optional[Any]:
        """
        Create a new instance of a registered strategy.

        Args:
            name: Strategy identifier
            **kwargs: Arguments to pass to the strategy constructor

        Returns:
            Strategy instance or None if strategy not found
        """
        strategy_class = self.get_strategy_class(name)
        if not strategy_class:
            self._logger.error(f"Strategy {name} not found in registry")
            return None

        try:
            return strategy_class(**kwargs)
        except Exception as e:
            self._logger.error(f"Error creating strategy {name}: {str(e)}")
            return None

    def list_strategies(self) -> List[Dict[str, Any]]:
        """
        List all registered strategies with their information.

        Returns:
            List of dictionaries with strategy information
        """
        return [
            {
                "name": info.name,
                "description": info.description,
                "version": info.version,
                "tags": list(info.tags),
                "metadata": info.metadata,
            }
            for info in self._strategies.values()
        ]

    def filter_strategies(self, **filters) -> List[str]:
        """
        Filter strategies based on metadata criteria.

        Args:
            **filters: Key-value pairs to match against strategy metadata

        Returns:
            List of strategy names that match the filters
        """
        result = []

        for name, info in self._strategies.items():
            matches = True

            for key, value in filters.items():
                if key == "tags":
                    # Special handling for tags - check if any of the provided tags match
                    if isinstance(value, (list, set)):
                        if not any(tag in info.tags for tag in value):
                            matches = False
                            break
                    elif value not in info.tags:
                        matches = False
                        break
                elif key in info.metadata:
                    if info.metadata[key] != value:
                        matches = False
                        break
                else:
                    # Check if the attribute exists on the StrategyInfo object
                    if hasattr(info, key):
                        if getattr(info, key) != value:
                            matches = False
                            break
                    else:
                        matches = False
                        break

            if matches:
                result.append(name)

        return result

    def get_strategies_by_tag(self, tag: str) -> List[str]:
        """
        Get strategies that have a specific tag.

        Args:
            tag: Tag to search for

        Returns:
            List of strategy names with the specified tag
        """
        return [name for name, info in self._strategies.items() if tag in info.tags]


def get_service_registry() -> ServiceRegistry:
    """
    Get the singleton service registry instance.

    Returns:
        The service registry instance
    """
    global _REGISTRY_INSTANCE

    if _REGISTRY_INSTANCE is None:
        _REGISTRY_INSTANCE = ServiceRegistry()

    return _REGISTRY_INSTANCE


def get_strategy_registry() -> StrategyRegistry:
    """
    Get the singleton strategy registry instance.

    Returns:
        The strategy registry instance
    """
    global _STRATEGY_REGISTRY_INSTANCE

    if _STRATEGY_REGISTRY_INSTANCE is None:
        _STRATEGY_REGISTRY_INSTANCE = StrategyRegistry()

    return _STRATEGY_REGISTRY_INSTANCE
