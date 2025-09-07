"""
FKS Trading Systems configuration providers.

This module contains configuration providers for loading from different sources.
"""

import json
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    yaml = None

try:
    import toml
except ImportError:
    toml = None

try:
    import boto3
except ImportError:
    boto3 = None

try:
    import consul
except ImportError:
    consul = None

from loguru import logger

from .models import ConfigFormat, ConfigSource, ValidationResult


class ConfigProvider(ABC):
    """Abstract base class for configuration providers."""

    @abstractmethod
    def load(self, source: Union[str, Path, ConfigSource]) -> Dict[str, Any]:
        """Load configuration from source."""
        pass

    @abstractmethod
    def supports(self, source: Union[str, Path, ConfigSource]) -> bool:
        """Check if provider supports the given source."""
        pass

    def validate_source(
        self, source: Union[str, Path, ConfigSource]
    ) -> ValidationResult:
        """Validate configuration source."""
        result = ValidationResult(is_valid=True)

        if isinstance(source, (str, Path)):
            path = Path(source)
            if not path.exists():
                result.add_error(f"Configuration file not found: {path}")

        return result


class FileProvider(ConfigProvider):
    """Provider for file-based configurations."""

    def __init__(self):
        self._loaders = {
            ConfigFormat.YAML: self._load_yaml,
            ConfigFormat.JSON: self._load_json,
            ConfigFormat.ENV: self._load_env,
            ConfigFormat.TOML: self._load_toml,
        }

    def supports(self, source: Union[str, Path, ConfigSource]) -> bool:
        """Check if provider supports the source."""
        if isinstance(source, ConfigSource):
            return source.format in self._loaders

        path = Path(source)
        suffix = path.suffix.lower()
        return suffix in [".yaml", ".yml", ".json", ".env", ".toml"]

    def load(self, source: Union[str, Path, ConfigSource]) -> Dict[str, Any]:
        """Load configuration from file."""
        if isinstance(source, ConfigSource):
            path = source.path
            format_type = source.format
        else:
            path = Path(source)
            format_type = self._detect_format(path)

        if not path or not path.exists():
            logger.warning(f"Configuration file not found: {path}")
            return {}

        if format_type not in self._loaders:
            raise ValueError(f"Unsupported configuration format: {format_type}")

        try:
            return self._loaders[format_type](path)
        except Exception as e:
            logger.error(f"Error loading configuration from {path}: {e}")
            return {}

    def _detect_format(self, path: Path) -> ConfigFormat:
        """Detect configuration format from file extension."""
        suffix = path.suffix.lower()
        format_mapping = {
            ".yaml": ConfigFormat.YAML,
            ".yml": ConfigFormat.YAML,
            ".json": ConfigFormat.JSON,
            ".env": ConfigFormat.ENV,
            ".toml": ConfigFormat.TOML,
        }

        format_type = format_mapping.get(suffix)
        if not format_type:
            raise ValueError(f"Unknown configuration file format: {suffix}")

        return format_type

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """Load YAML configuration file."""
        if not yaml:
            raise ImportError("PyYAML is required for YAML configuration files")

        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
            return content or {}

    def _load_json(self, path: Path) -> Dict[str, Any]:
        """Load JSON configuration file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_env(self, path: Path) -> Dict[str, Any]:
        """Load environment file (.env format)."""
        env_vars = {}

        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                # Parse key=value pairs
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

                    # Remove quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]

                    # Try to parse as JSON for complex values
                    try:
                        parsed_value = json.loads(value)
                    except json.JSONDecodeError:
                        parsed_value = value

                    env_vars[key] = parsed_value
                else:
                    logger.warning(f"Invalid line in {path}:{line_num}: {line}")

        return env_vars

    def _load_toml(self, path: Path) -> Dict[str, Any]:
        """Load TOML configuration file."""
        if not toml:
            raise ImportError("toml is required for TOML configuration files")

        with open(path, "r", encoding="utf-8") as f:
            return toml.load(f)


class EnvironmentProvider(ConfigProvider):
    """Provider for environment variable configurations."""

    def __init__(self, prefix: str = "", separator: str = "_"):
        self.prefix = prefix.upper()
        self.separator = separator

    def supports(self, source: Union[str, Path, ConfigSource]) -> bool:
        """Environment provider supports all sources (always available)."""
        return True

    def load(self, source: Union[str, Path, ConfigSource] = None) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        env_config = {}

        for key, value in os.environ.items():
            # Filter by prefix if specified
            if self.prefix and not key.startswith(self.prefix):
                continue

            # Remove prefix and convert to nested structure
            config_key = key[len(self.prefix) :] if self.prefix else key
            config_key = config_key.lower()

            # Convert separator to dots for nested keys
            if self.separator in config_key:
                config_key = config_key.replace(self.separator, ".")

            # Try to parse value as JSON for complex types
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError:
                # Try to parse as boolean
                if value.lower() in ("true", "false"):
                    parsed_value = value.lower() == "true"
                # Try to parse as number
                elif value.isdigit():
                    parsed_value = int(value)
                elif self._is_float(value):
                    parsed_value = float(value)
                else:
                    parsed_value = value

            # Set nested value
            self._set_nested_value(env_config, config_key, parsed_value)

        return env_config

    def _is_float(self, value: str) -> bool:
        """Check if string represents a float."""
        try:
            float(value)
            return "." in value
        except ValueError:
            return False

    def _set_nested_value(self, target: Dict[str, Any], key: str, value: Any) -> None:
        """Set a nested value in dictionary using dot notation."""
        keys = key.split(".")
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value


class AWSParameterStoreProvider(ConfigProvider):
    """Provider for AWS Systems Manager Parameter Store."""

    def __init__(self, region: str = "us-east-1", prefix: str = "/fks/"):
        if not boto3:
            raise ImportError("boto3 is required for AWS Parameter Store provider")

        self.client = boto3.client("ssm", region_name=region)
        self.prefix = prefix

    def supports(self, source: Union[str, Path, ConfigSource]) -> bool:
        """Check if source is AWS Parameter Store path."""
        if isinstance(source, str):
            return source.startswith("aws://") or source.startswith("/fks/")
        return False

    def load(self, source: Union[str, Path, ConfigSource]) -> Dict[str, Any]:
        """Load configuration from AWS Parameter Store."""
        if isinstance(source, str):
            if source.startswith("aws://"):
                # Parse aws://parameter-store/path/to/params
                parsed = urlparse(source)
                prefix = parsed.path
            else:
                prefix = source
        else:
            prefix = self.prefix

        try:
            response = self.client.get_parameters_by_path(
                Path=prefix, Recursive=True, WithDecryption=True
            )

            config = {}
            for param in response["Parameters"]:
                # Remove prefix and convert to nested structure
                key = param["Name"][len(prefix) :].lstrip("/")
                key = key.replace("/", ".")

                # Try to parse value as JSON
                try:
                    value = json.loads(param["Value"])
                except json.JSONDecodeError:
                    value = param["Value"]

                self._set_nested_value(config, key, value)

            return config

        except Exception as e:
            logger.error(f"Error loading from AWS Parameter Store: {e}")
            return {}

    def _set_nested_value(self, target: Dict[str, Any], key: str, value: Any) -> None:
        """Set nested value using dot notation."""
        keys = key.split(".")
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value


class ConsulProvider(ConfigProvider):
    """Provider for HashiCorp Consul KV store."""

    def __init__(self, host: str = "localhost", port: int = 8500, prefix: str = "fks/"):
        if not consul:
            raise ImportError("python-consul is required for Consul provider")

        self.client = consul.Consul(host=host, port=port)
        self.prefix = prefix

    def supports(self, source: Union[str, Path, ConfigSource]) -> bool:
        """Check if source is Consul KV path."""
        if isinstance(source, str):
            return source.startswith("consul://") or source.startswith("fks/")
        return False

    def load(self, source: Union[str, Path, ConfigSource]) -> Dict[str, Any]:
        """Load configuration from Consul KV store."""
        if isinstance(source, str):
            if source.startswith("consul://"):
                # Parse consul://host:port/path/to/keys
                parsed = urlparse(source)
                prefix = parsed.path.lstrip("/")
            else:
                prefix = source
        else:
            prefix = self.prefix

        try:
            _, data = self.client.kv.get(prefix, recurse=True)

            if not data:
                return {}

            config = {}
            for item in data:
                # Remove prefix and convert to nested structure
                key = item["Key"][len(prefix) :].lstrip("/")
                key = key.replace("/", ".")

                if item["Value"]:
                    value_str = item["Value"].decode("utf-8")

                    # Try to parse as JSON
                    try:
                        value = json.loads(value_str)
                    except json.JSONDecodeError:
                        value = value_str

                    self._set_nested_value(config, key, value)

            return config

        except Exception as e:
            logger.error(f"Error loading from Consul: {e}")
            return {}

    def _set_nested_value(self, target: Dict[str, Any], key: str, value: Any) -> None:
        """Set nested value using dot notation."""
        keys = key.split(".")
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value


class URLProvider(ConfigProvider):
    """Provider for loading configuration from URLs."""

    def supports(self, source: Union[str, Path, ConfigSource]) -> bool:
        """Check if source is a URL."""
        if isinstance(source, str):
            return source.startswith(("http://", "https://"))
        return False

    def load(self, source: Union[str, Path, ConfigSource]) -> Dict[str, Any]:
        """Load configuration from URL."""
        import urllib.request

        url = str(source)

        try:
            with urllib.request.urlopen(url) as response:
                content = response.read().decode("utf-8")

                # Detect format from URL or Content-Type header
                content_type = response.headers.get("content-type", "").lower()

                if "json" in content_type or url.endswith(".json"):
                    return json.loads(content)
                elif "yaml" in content_type or url.endswith((".yaml", ".yml")):
                    if not yaml:
                        raise ImportError("PyYAML is required for YAML URLs")
                    return yaml.safe_load(content) or {}
                else:
                    # Try JSON first, then YAML
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError:
                        if yaml:
                            return yaml.safe_load(content) or {}
                        raise ValueError("Unable to parse content as JSON or YAML")

        except Exception as e:
            logger.error(f"Error loading configuration from URL {url}: {e}")
            return {}


class ConfigProviderRegistry:
    """Registry for configuration providers."""

    def __init__(self):
        self._providers: List[ConfigProvider] = []
        self._register_default_providers()

    def _register_default_providers(self):
        """Register default configuration providers."""
        self.register(FileProvider())
        self.register(EnvironmentProvider())
        self.register(URLProvider())

        # Register cloud providers if available
        try:
            self.register(AWSParameterStoreProvider())
        except ImportError:
            pass

        try:
            self.register(ConsulProvider())
        except ImportError:
            pass

    def register(self, provider: ConfigProvider) -> None:
        """Register a configuration provider."""
        if not isinstance(provider, ConfigProvider):
            raise TypeError("Provider must inherit from ConfigProvider")

        self._providers.append(provider)
        logger.debug(
            f"Registered configuration provider: {provider.__class__.__name__}"
        )

    def get_provider(
        self, source: Union[str, Path, ConfigSource]
    ) -> Optional[ConfigProvider]:
        """Get appropriate provider for source."""
        for provider in self._providers:
            if provider.supports(source):
                return provider
        return None

    def load(self, source: Union[str, Path, ConfigSource]) -> Dict[str, Any]:
        """Load configuration using appropriate provider."""
        provider = self.get_provider(source)

        if not provider:
            raise ValueError(f"No provider found for source: {source}")

        # Validate source if possible
        validation = provider.validate_source(source)
        if not validation.is_valid:
            error_msg = "; ".join(validation.errors)
            raise ValueError(f"Invalid configuration source: {error_msg}")

        return provider.load(source)

    def load_multiple(
        self, sources: List[Union[str, Path, ConfigSource]]
    ) -> Dict[str, Any]:
        """Load configuration from multiple sources and merge."""
        merged_config = {}

        # Sort sources by priority if they're ConfigSource objects
        sorted_sources = sorted(
            sources, key=lambda s: s.priority if isinstance(s, ConfigSource) else 0
        )

        for source in sorted_sources:
            try:
                config = self.load(source)
                self._deep_merge(merged_config, config)
            except Exception as e:
                if isinstance(source, ConfigSource) and source.required:
                    raise
                logger.warning(
                    f"Failed to load optional configuration source {source}: {e}"
                )

        return merged_config

    def _deep_merge(self, base: Dict[str, Any], overlay: Dict[str, Any]) -> None:
        """Deep merge overlay into base dictionary."""
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value


# Global provider registry instance
provider_registry = ConfigProviderRegistry()
