"""
Service template for microservices with health endpoints and lifecycle management.

This module provides a robust template for creating microservices with:
- Health and info endpoints
- Graceful shutdown handling
- Configurable logging
- Error recovery and fallback modes
- Metrics collection
"""

import os
import signal
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from werkzeug.exceptions import HTTPException

__all__ = [
    "ServiceTemplate",
    "ServiceConfig",
    "HealthEndpoint",
    "start_template_service",
    "start",
]

# Configure logging - support both loguru and standard logging
try:
    from loguru import logger as loguru_logger

    HAS_LOGURU = True

    def configure_loguru_logging(level: str = "INFO") -> None:
        """Configure loguru logger with the specified level."""
        loguru_logger.remove()  # Remove default handler
        loguru_logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
            level=level.upper(),
        )

except ImportError:
    import logging

    HAS_LOGURU = False
    loguru_logger = None

    def configure_standard_logging(level: str = "INFO") -> None:
        """Configure standard logging with the specified level."""
        logging.basicConfig(
            level=level.upper(),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    class LoggerAdapter:
        """Adapter to make standard logging work like loguru."""

        def __init__(self, name: str):
            self.logger = logging.getLogger(name)

        def info(self, msg: str, *args, **kwargs) -> None:
            self.logger.info(msg, *args, **kwargs)

        def warning(self, msg: str, *args, **kwargs) -> None:
            self.logger.warning(msg, *args, **kwargs)

        def error(self, msg: str, *args, **kwargs) -> None:
            self.logger.error(msg, *args, **kwargs)

        def debug(self, msg: str, *args, **kwargs) -> None:
            self.logger.debug(msg, *args, **kwargs)

        def exception(self, msg: str, *args, **kwargs) -> None:
            self.logger.exception(msg, *args, **kwargs)

        def success(self, msg: str, *args, **kwargs) -> None:
            # Standard logging doesn't have success, map to info
            self.logger.info(f"SUCCESS: {msg}", *args, **kwargs)


@dataclass
class ServiceConfig:
    """Configuration for service template."""

    name: str = "service"
    port: int = 8080
    host: str = "0.0.0.0"
    environment: str = "development"
    version: str = "1.0.0"
    log_level: str = "INFO"
    health_check_interval: int = 60  # seconds
    fallback_port: int = 8080
    shutdown_timeout: int = 30  # seconds
    enable_metrics: bool = False
    custom_endpoints: Dict[str, Callable] = field(default_factory=dict)


class HealthEndpoint:
    """Manages health and info endpoints for the service."""

    def __init__(self, config: ServiceConfig):
        self.config = config
        self.start_time = datetime.now()
        self.metrics = {"requests_total": 0, "health_checks": 0, "errors": 0}
        self.app = None
        self.server_thread = None
        self.logger = self._create_logger()

    def _create_logger(self):
        """Create appropriate logger instance."""
        if HAS_LOGURU:
            return loguru_logger
        else:
            return LoggerAdapter(f"{self.config.name}.health")

    def get_service_info(self) -> Dict[str, Any]:
        """Get comprehensive service information."""
        uptime = datetime.now() - self.start_time
        days, remainder = divmod(uptime.total_seconds(), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"

        info = {
            "service": self.config.name,
            "status": "healthy",
            "version": self.config.version,
            "environment": self.config.environment,
            "uptime": uptime_str,
            "uptime_seconds": uptime.total_seconds(),
            "start_time": self.start_time.isoformat(),
            "current_time": datetime.now().isoformat(),
            "python_version": sys.version,
            "host": self.config.host,
            "port": self.config.port,
        }

        if self.config.enable_metrics:
            info["metrics"] = self.metrics.copy()

        return info

    def start_server(self) -> bool:
        """Start the Flask server with health endpoints."""
        try:
            from flask import Flask, jsonify, request

            # Use __name__ instead of service name to avoid Flask root path issues
            self.app = Flask(__name__)

            # Health endpoint
            @self.app.route("/health")
            def health():
                self.metrics["health_checks"] += 1
                self.metrics["requests_total"] += 1
                return jsonify(self.get_service_info())

            # Info endpoint
            @self.app.route("/info")
            def info():
                self.metrics["requests_total"] += 1
                return jsonify(self.get_service_info())

            # Readiness endpoint (for Kubernetes)
            @self.app.route("/ready")
            def ready():
                self.metrics["requests_total"] += 1
                return jsonify(
                    {
                        "status": "ready",
                        "service": self.config.name,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            # Liveness endpoint (for Kubernetes)
            @self.app.route("/live")
            def live():
                self.metrics["requests_total"] += 1
                return jsonify(
                    {
                        "status": "alive",
                        "service": self.config.name,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            # Metrics endpoint (if enabled)
            if self.config.enable_metrics:

                @self.app.route("/metrics")
                def metrics():
                    self.metrics["requests_total"] += 1
                    return jsonify(self.metrics)

            # Add custom endpoints (supports multiple formats):
            # - path: callable
            # - path: (callable, [methods])
            # - path: {"handler": callable, "methods": [..]}
            for path, spec in self.config.custom_endpoints.items():
                endpoint_name = path.replace("/", "_") or "root"
                view_func = None
                methods = None

                if callable(spec):
                    view_func = spec
                    methods = None  # default Flask methods
                elif isinstance(spec, (tuple, list)) and len(spec) >= 1:
                    view_func = spec[0]
                    if len(spec) >= 2:
                        methods = spec[1]
                elif isinstance(spec, dict):
                    view_func = spec.get("handler")
                    methods = spec.get("methods")

                if not callable(view_func):
                    self.logger.warning(
                        f"Skipping custom endpoint for '{path}': invalid handler spec"
                    )
                    continue

                if methods:
                    self.app.add_url_rule(
                        path, endpoint=endpoint_name, view_func=view_func, methods=methods
                    )
                else:
                    self.app.add_url_rule(
                        path, endpoint=endpoint_name, view_func=view_func
                    )
            if self.config.custom_endpoints:
                try:
                    ep_list = ", ".join(sorted(self.config.custom_endpoints.keys()))
                except Exception:
                    ep_list = str(list(self.config.custom_endpoints.keys()))
                self.logger.info(f"🔌 Registered custom endpoints: {ep_list}")

            # Error handler
            @self.app.errorhandler(Exception)
            def handle_error(e):
                self.metrics["errors"] += 1
                # Preserve HTTP exceptions (e.g., 404) with their original status code
                if isinstance(e, HTTPException):
                    return (
                        jsonify(
                            {
                                "error": e.description,
                                "service": self.config.name,
                                "timestamp": datetime.now().isoformat(),
                                "status": e.code,
                            }
                        ),
                        e.code,
                    )

                self.logger.error(f"Endpoint error: {str(e)}")
                return (
                    jsonify(
                        {
                            "error": str(e),
                            "service": self.config.name,
                            "timestamp": datetime.now().isoformat(),
                        }
                    ),
                    500,
                )

            # Start Flask in a daemon thread
            self.server_thread = threading.Thread(
                target=lambda: self.app.run(
                    host=self.config.host,
                    port=self.config.port,
                    debug=False,
                    use_reloader=False,
                ),
                daemon=True,
            )
            self.server_thread.start()

            self.logger.info(
                f"Health endpoints started on {self.config.host}:{self.config.port}"
            )
            self.logger.info(
                f"  Health: http://{self.config.host}:{self.config.port}/health"
            )
            self.logger.info(
                f"  Info: http://{self.config.host}:{self.config.port}/info"
            )
            self.logger.info(
                f"  Ready: http://{self.config.host}:{self.config.port}/ready"
            )
            self.logger.info(
                f"  Live: http://{self.config.host}:{self.config.port}/live"
            )

            if self.config.enable_metrics:
                self.logger.info(
                    f"  Metrics: http://{self.config.host}:{self.config.port}/metrics"
                )

            return True

        except ImportError:
            self.logger.warning("Flask not available, running without health endpoints")
            self.logger.info(
                "Consider installing Flask for health checks: pip install flask"
            )
            return False

        except Exception as e:
            self.logger.error(f"Error setting up health endpoints: {e}")
            self.logger.debug(traceback.format_exc())
            return False

    def stop_server(self) -> None:
        """Stop the health endpoint server."""
        if self.server_thread and self.server_thread.is_alive():
            self.logger.info("Stopping health endpoint server")
            # Note: Flask's development server doesn't have a clean shutdown method
            # In production, you'd use a proper WSGI server like gunicorn


class ServiceTemplate:
    """
    Enhanced service template with lifecycle management and health endpoints.
    """

    def __init__(self, config: Optional[ServiceConfig] = None):
        self.config = config or ServiceConfig()
        self.health_endpoint = HealthEndpoint(self.config)
        self.logger = self._create_logger()
        self.shutdown_handlers: List[Callable] = []
        self.startup_handlers: List[Callable] = []
        self._shutdown_requested = False
        self._setup_logging()

    def _create_logger(self):
        """Create appropriate logger instance."""
        if HAS_LOGURU:
            return loguru_logger
        else:
            return LoggerAdapter(self.config.name)

    def _setup_logging(self) -> None:
        """Setup logging configuration."""
        if HAS_LOGURU:
            configure_loguru_logging(self.config.log_level)
        else:
            configure_standard_logging(self.config.log_level)

    def add_startup_handler(self, handler: Callable) -> None:
        """Add a handler to be called during startup."""
        self.startup_handlers.append(handler)

    def add_shutdown_handler(self, handler: Callable) -> None:
        """Add a handler to be called during shutdown."""
        self.shutdown_handlers.append(handler)

    def handle_shutdown(self, signum: int, frame) -> None:
        """Handle shutdown signals for graceful termination."""
        self.logger.info(
            f"Received shutdown signal ({signum}), shutting down {self.config.name} service"
        )
        self._shutdown_requested = True

    def register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)

    def run_startup_handlers(self) -> None:
        """Execute all registered startup handlers."""
        for handler in self.startup_handlers:
            try:
                self.logger.debug(f"Running startup handler: {handler.__name__}")
                handler()
            except Exception as e:
                self.logger.error(f"Error in startup handler {handler.__name__}: {e}")
                raise

    def run_shutdown_handlers(self) -> None:
        """Execute all registered shutdown handlers."""
        for handler in reversed(self.shutdown_handlers):  # Reverse order
            try:
                self.logger.debug(f"Running shutdown handler: {handler.__name__}")
                handler()
            except Exception as e:
                self.logger.error(f"Error in shutdown handler {handler.__name__}: {e}")

    def run_fallback_mode(self) -> None:
        """Run in fallback mode to keep container alive."""
        self.logger.warning(f"Running {self.config.name} service in FALLBACK mode")

        # Try to start health endpoint on fallback port
        fallback_config = ServiceConfig(
            name=f"{self.config.name}-fallback",
            port=self.config.fallback_port,
            host=self.config.host,
            environment=self.config.environment,
            version=self.config.version,
        )
        fallback_health = HealthEndpoint(fallback_config)
        fallback_health.start_server()

        # Keep the process alive
        iteration = 0
        while not self._shutdown_requested:
            iteration += 1
            if iteration % 5 == 0:  # Log more frequently in fallback mode
                self.logger.warning(
                    f"⚠️ {self.config.name} service in FALLBACK mode (iteration {iteration})"
                )
            time.sleep(60)

    def run(self, main_loop: Optional[Callable] = None) -> None:
        """
        Run the service with lifecycle management.

        Args:
            main_loop: Optional main application loop function
        """
        self.register_signal_handlers()

        try:
            self.logger.info(f"Starting {self.config.name} service")
            self.logger.info(f"Environment: {self.config.environment}")
            self.logger.info(f"Version: {self.config.version}")
            self.logger.info(f"Log level: {self.config.log_level}")

            # Run startup handlers
            self.run_startup_handlers()

            # Start health endpoints
            self.health_endpoint.start_server()

            self.logger.info(f"✅ {self.config.name} service is now running")

            # Main service loop
            if main_loop:
                main_loop()
            else:
                self._default_main_loop()

        except KeyboardInterrupt:
            self.logger.info(f"{self.config.name} service terminated by user")
        except Exception as e:
            self.logger.error(f"Error in {self.config.name} service: {e}")
            self.logger.debug(traceback.format_exc())
            # Run in fallback mode to keep container alive
            self.run_fallback_mode()
        finally:
            # Cleanup
            self.run_shutdown_handlers()
            self.health_endpoint.stop_server()
            self.logger.info(f"{self.config.name} service shutting down")

    def _default_main_loop(self) -> None:
        """Default main loop that just keeps the service alive."""
        iteration = 0

        while not self._shutdown_requested:
            iteration += 1

            # Log periodically to show the service is alive
            if iteration % self.config.health_check_interval == 0:
                uptime = (
                    datetime.now() - self.health_endpoint.start_time
                ).total_seconds()
                days, remainder = divmod(uptime, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                uptime_str = (
                    f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"
                )

                self.logger.info(
                    f"✅ {self.config.name} service running (iteration {iteration}, uptime {uptime_str})"
                )

            time.sleep(1)  # Check shutdown status frequently

    @contextmanager
    def lifecycle_context(self):
        """Context manager for service lifecycle."""
        try:
            self.run_startup_handlers()
            self.health_endpoint.start_server()
            yield self
        finally:
            self.run_shutdown_handlers()
            self.health_endpoint.stop_server()


def start_template_service(
    service_name: Optional[str] = None, service_port: Optional[int] = None, **kwargs
) -> None:
    """
    Start a service using the template with the specified configuration.

    Args:
        service_name: Name of the service
        service_port: Port to run on
        **kwargs: Additional configuration options
    """
    # Build configuration from environment and parameters
    config = ServiceConfig(
        name=service_name or os.environ.get("SERVICE_NAME", "service"),
        port=service_port or int(os.environ.get("SERVICE_PORT", "8080")),
        environment=os.environ.get("APP_ENV", "development"),
        version=os.environ.get("APP_VERSION", "1.0.0"),
        log_level=os.environ.get("APP_LOG_LEVEL", "INFO"),
        **kwargs,
    )

    # Create and run service
    service = ServiceTemplate(config)
    service.run()


def start(
    service_name: Optional[str] = None, service_port: Optional[int] = None
) -> None:
    """
    Convenience function for starting a service template.

    Args:
        service_name: Name of the service
        service_port: Port to run on
    """
    start_template_service(service_name, service_port)


# Allow direct execution
if __name__ == "__main__":
    try:
        # Parse command line arguments
        svc_name = sys.argv[1] if len(sys.argv) > 1 else None
        svc_port = int(sys.argv[2]) if len(sys.argv) > 2 else None
        start_template_service(svc_name, svc_port)
    except Exception as e:
        # Create basic logger for critical errors
        if HAS_LOGURU:
            logger = loguru_logger
        else:
            logger = LoggerAdapter("service-template")

        logger.error(f"Unhandled exception: {e}")
        logger.debug(traceback.format_exc())

        # Run basic fallback
        config = ServiceConfig(name="emergency-service")
        service = ServiceTemplate(config)
        service.run_fallback_mode()
