"""
FKS Trading Systems configuration manager.

This module provides a comprehensive configuration management system with support
for multiple file formats, environment variable overlays, and path management.
"""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from .models import Config, PathConfig
from .providers import EnvironmentProvider, provider_registry


class PathManager:
    """Manages application paths and directory creation."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.legacy_ml_base_path = Path("/app/src/plugins/strategies/bitcoin")
        self.legacy_ml_results_path = self.legacy_ml_base_path / "ml_results"
        self.legacy_ml_models_path = self.legacy_ml_results_path / "models"

    def create_path_config(self, paths_config: Dict[str, str]) -> PathConfig:
        """Create a PathConfig object from configuration."""
        # Get base output directory
        base_output_dir = self._resolve_path(
            paths_config.get("base_output_dir", "outputs")
        )

        # Create path configuration
        path_config = PathConfig(
            base_dir=self.base_dir,
            outputs_dir=base_output_dir,
            data_dir=self._resolve_config_path(
                paths_config, "data_dir", base_output_dir / "data"
            ),
            ml_dir=self._resolve_config_path(
                paths_config, "ml_dir", base_output_dir / "ml"
            ),
            models_dir=self._resolve_config_path(
                paths_config, "models_dir", base_output_dir / "ml" / "models"
            ),
            logs_dir=self._resolve_config_path(
                paths_config, "logs_dir", base_output_dir / "logs"
            ),
            backtest_dir=self._resolve_config_path(
                paths_config, "backtest_dir", base_output_dir / "backtest_reports"
            ),
            evaluation_dir=self._resolve_config_path(
                paths_config, "evaluation_dir", base_output_dir / "evaluation"
            ),
            training_dir=self._resolve_config_path(
                paths_config, "training_dir", base_output_dir / "training"
            ),
            cache_dir=self._resolve_config_path(
                paths_config, "cache_dir", base_output_dir / "data" / "cache"
            ),
        )

        return path_config

    def _resolve_path(self, path: Union[str, Path]) -> Path:
        """Resolve a path relative to base directory if not absolute."""
        path = Path(path)
        if not path.is_absolute():
            return self.base_dir / path
        return path

    def _resolve_config_path(
        self, paths_config: Dict[str, str], key: str, default: Path
    ) -> Path:
        """Resolve a path from configuration or use default."""
        if key in paths_config:
            return self._resolve_path(paths_config[key])
        return default

    def create_directories(self, path_config: PathConfig) -> None:
        """Create all required directories."""
        directories = [
            path_config.outputs_dir,
            path_config.data_dir,
            path_config.ml_dir,
            path_config.models_dir,
            path_config.logs_dir,
            path_config.backtest_dir,
            path_config.evaluation_dir,
            path_config.training_dir,
            path_config.cache_dir,
        ]

        for directory in directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Ensured directory exists: {directory}")
            except Exception as e:
                logger.error(f"Failed to create directory {directory}: {e}")

        # Set permissions
        self._set_permissions(path_config.outputs_dir)

    def _set_permissions(self, directory: Path) -> None:
        """Set appropriate permissions for output directories."""
        try:
            os.chmod(directory, 0o755)
            logger.debug(f"Set permissions for directory: {directory}")
        except Exception as e:
            logger.warning(f"Could not set permissions for {directory}: {e}")

    def create_legacy_symlinks(self, path_config: PathConfig) -> None:
        """Create symbolic links for backward compatibility."""
        symlink_mappings = [
            (self.legacy_ml_results_path, path_config.ml_dir),
            (self.legacy_ml_models_path, path_config.models_dir),
        ]

        for legacy_path, target_path in symlink_mappings:
            self._create_symlink(legacy_path, target_path)

    def _create_symlink(self, symlink_path: Path, target_path: Path) -> None:
        """Create a symbolic link, removing existing files if necessary."""
        try:
            # Ensure parent directory exists
            symlink_path.parent.mkdir(parents=True, exist_ok=True)

            # Remove existing file/directory if not a symlink
            if symlink_path.exists() and not symlink_path.is_symlink():
                if symlink_path.is_dir():
                    shutil.rmtree(symlink_path)
                else:
                    symlink_path.unlink()

            # Create symlink if it doesn't exist
            if not symlink_path.exists():
                symlink_path.symlink_to(target_path)
                logger.info(f"Created symbolic link: {symlink_path} -> {target_path}")

        except Exception as e:
            logger.error(
                f"Failed to create symbolic link {symlink_path} -> {target_path}: {e}"
            )


class ConfigProcessor:
    """Processes and updates configuration with paths and defaults."""

    def __init__(self, path_config: PathConfig):
        self.path_config = path_config

    def process_config(self, config: Config) -> None:
        """Process configuration with path updates and defaults."""
        self._update_ml_paths(config)
        self._update_data_paths(config)
        self._update_training_paths(config)
        self._update_evaluation_paths(config)
        self._update_backtesting_paths(config)
        self._update_app_paths(config)
        self._update_web_config(config)

    def _update_ml_paths(self, config: Config) -> None:
        """Update ML-related paths in configuration."""
        config.set("ml.paths.base", str(self.path_config.ml_dir))
        config.set("ml.paths.results", str(self.path_config.ml_dir))
        config.set("ml.paths.models", str(self.path_config.models_dir))

        # Legacy paths for compatibility
        config.set(
            "ml.legacy_paths.base", str(Path("/app/src/plugins/strategies/bitcoin"))
        )
        config.set(
            "ml.legacy_paths.results",
            str(Path("/app/src/plugins/strategies/bitcoin/ml_results")),
        )
        config.set(
            "ml.legacy_paths.models",
            str(Path("/app/src/plugins/strategies/bitcoin/ml_results/models")),
        )

    def _update_data_paths(self, config: Config) -> None:
        """Update data-related paths in configuration."""
        data_paths = {
            "data.train_path": self.path_config.data_dir / "train.parquet",
            "data.val_path": self.path_config.data_dir / "val.parquet",
            "data.test_path": self.path_config.data_dir / "test.parquet",
            "data.backtest_path": self.path_config.data_dir / "test.parquet",
            "data.download_output": (
                self.path_config.data_dir / "bitcoin_dataset.parquet"
            ),
            "data.cache_dir": self.path_config.cache_dir,
            "preprocessing.preprocess_train_output": (
                self.path_config.data_dir / "train.parquet"
            ),
            "preprocessing.preprocess_val_output": (
                self.path_config.data_dir / "val.parquet"
            ),
            "preprocessing.preprocess_test_output": (
                self.path_config.data_dir / "test.parquet"
            ),
        }

        for key, path in data_paths.items():
            config.set(key, str(path))

    def _update_training_paths(self, config: Config) -> None:
        """Update training-related paths in configuration."""
        config.set(
            "training.output_dir",
            str(self.path_config.training_dir / "lightning_outputs"),
        )
        config.set(
            "training.train_output_dir", str(self.path_config.training_dir / "outputs")
        )

    def _update_evaluation_paths(self, config: Config) -> None:
        """Update evaluation-related paths in configuration."""
        config.set("evaluation.output_dir", str(self.path_config.evaluation_dir))
        config.set("evaluation.eval_output_dir", str(self.path_config.evaluation_dir))

    def _update_backtesting_paths(self, config: Config) -> None:
        """Update backtesting-related paths in configuration."""
        config.set("backtesting.output_dir", str(self.path_config.backtest_dir))
        config.set(
            "backtesting.backtest_output_dir", str(self.path_config.backtest_dir)
        )
        config.set("backtesting.data", str(self.path_config.data_dir / "test.parquet"))

    def _update_app_paths(self, config: Config) -> None:
        """Update application-related paths in configuration."""
        config.set("app.base_dir", str(self.path_config.base_dir))
        config.set("app.outputs_dir", str(self.path_config.outputs_dir))
        config.set("app.model_dir", str(self.path_config.models_dir))
        config.set(
            "app.logging.file", str(self.path_config.logs_dir / "trading_app.log")
        )

        # Set app metadata if constants are available
        try:
            from .constants import APP_ENV, APP_NAME, APP_VERSION

            config.set("app.name", APP_NAME)
            config.set("app.version", APP_VERSION)
            config.set(
                "app.environment",
                APP_ENV.value if hasattr(APP_ENV, "value") else str(APP_ENV),
            )
        except ImportError:
            logger.debug("App constants not available")

    def _update_web_config(self, config: Config) -> None:
        """Update web-related configuration."""
        # Ensure web config exists
        if not config.get("web"):
            config.set("web", {})

        # Extract and move UI settings if they exist in yaml_config
        yaml_config = config.get("yaml_config", {})
        if "ui" in yaml_config:
            config.set("web.ui", yaml_config["ui"])

        if "server" in yaml_config:
            current_web = config.get("web", {})
            current_web.update(yaml_config["server"])
            config.set("web", current_web)

        # Clean up temporary yaml_config
        if config.get("yaml_config"):
            config.data.pop("yaml_config", None)


class FKSConfigManager:
    """
    FKS Trading Systems Configuration Manager.

    Provides comprehensive configuration management with support for multiple
    file formats, environment overlays, and automatic path management.
    """

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        watch_for_changes: bool = True,
        env_prefix: str = "FKS_",
    ):
        """
        Initialize the FKS configuration manager.

        Args:
            config_path: Path to main configuration file
            watch_for_changes: Whether to watch for file changes (not implemented)
            env_prefix: Prefix for environment variables
        """
        # Set up base directory and default paths
        self.base_dir = Path(__file__).parent.parent.parent.parent.resolve()
        self.default_config_path = self.base_dir / "config" / "default.yaml"

        # Initialize path manager
        self.path_manager = PathManager(self.base_dir)

        # Configuration settings
        self.config_path = (
            Path(config_path) if config_path else self.default_config_path
        )
        self.env_prefix = env_prefix
        self.watch_for_changes = watch_for_changes

        # Load configuration
        self._config = self._load_config()

        # Initialize processor and setup paths
        self.processor = ConfigProcessor(self._config.paths)
        self.processor.process_config(self._config)

    def _load_config(self) -> Config:
        """Load and process the complete configuration."""
        # Load base configuration using provider registry
        base_config = provider_registry.load(self.config_path)

        # Apply environment variable overlays
        env_provider = EnvironmentProvider(prefix=self.env_prefix)
        env_config = env_provider.load()

        # Create config object
        config = Config(data=base_config)
        config.update(env_config)

        # Set up paths
        paths_config = config.get("paths", {})
        path_config = self.path_manager.create_path_config(paths_config)
        config.paths = path_config

        # Create directories and symlinks
        self.path_manager.create_directories(path_config)
        self.path_manager.create_legacy_symlinks(path_config)

        return config

    def load_with_overlays(self, overlays: List[Union[str, Path]]) -> Config:
        """
        Load configuration with additional overlay files.

        Args:
            overlays: List of overlay configuration files

        Returns:
            Merged configuration
        """
        # Prepare all sources including base config
        all_sources = [self.config_path] + overlays

        # Load merged configuration using provider registry
        merged_data = provider_registry.load_multiple(all_sources)

        # Apply environment variables
        env_provider = EnvironmentProvider(prefix=self.env_prefix)
        env_config = env_provider.load()

        # Create config object
        config = Config(data=merged_data)
        config.update(env_config)

        return config

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value."""
        self._config.set(key, value)

    def get_output_path(self, *parts: str) -> Path:
        """Get a path within the outputs directory."""
        path = self._config.paths.outputs_dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_ml_path(self, *parts: str) -> Path:
        """Get a path within the ML directory."""
        path = self._config.paths.ml_dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_models_path(self, *parts: str) -> Path:
        """Get a path within the models directory."""
        path = self._config.paths.models_dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def reload(self) -> None:
        """Reload configuration from files."""
        self._config = self._load_config()
        self.processor = ConfigProcessor(self._config.paths)
        self.processor.process_config(self._config)

    @property
    def config(self) -> Config:
        """Get the current configuration."""
        return self._config

    @property
    def paths(self) -> PathConfig:
        """Get the path configuration."""
        return self._config.paths


# Convenience alias for backward compatibility
ConfigManager = FKSConfigManager
