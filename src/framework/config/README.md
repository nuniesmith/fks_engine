# FKS Trading Systems Configuration Package

A comprehensive, production-ready configuration management system for the FKS Trading Systems platform with support for multiple file formats, environment overlays, cloud providers, and advanced path management.

## 🚀 Quick Start

```python
from fks.config import create_config_manager

# Simple setup with auto-detection
config_manager = create_config_manager()

# Access configuration values
db_host = config_manager.get('database.host')
model_path = config_manager.get_models_path('my_model.pkl')
```

## 📁 Package Structure

```
fks/config/
├── __init__.py          # Package initialization and exports
├── config_manager.py    # Main configuration manager
├── models.py           # Data models and type definitions
├── providers.py        # Configuration source providers
└── constants.py        # Application constants and defaults
```

## 🔧 Core Components

### 1. **FKSConfigManager** - Main Configuration Manager
The central orchestrating class that manages configuration loading, path setup, and provides access to all configuration values.

```python
config_manager = FKSConfigManager(
    config_path='config/app.yaml',
    env_prefix='FKS_',
    watch_for_changes=True
)
```

### 2. **Config Models** - Type-Safe Configuration
Strongly typed configuration objects for different system components:

- **DatabaseConfig** - Database connection settings
- **APIConfig** - REST API server configuration
- **MLConfig** - Machine learning parameters
- **TradingConfig** - Trading strategy settings
- **SecurityConfig** - Authentication and security
- **LoggingConfig** - Logging setup and formatting

### 3. **Configuration Providers** - Multi-Source Loading
Support for loading configuration from various sources:

- **FileProvider** - YAML, JSON, TOML, ENV files
- **EnvironmentProvider** - Environment variables with nesting
- **URLProvider** - Remote configuration via HTTP/HTTPS
- **AWSParameterStoreProvider** - AWS Systems Manager
- **ConsulProvider** - HashiCorp Consul KV store

### 4. **Path Management** - Intelligent Directory Handling
Automatic creation and management of application directories with backward compatibility through symbolic links.

### 5. **Constants Module** - Centralized Defaults
Application-wide constants, default configurations, and utility functions for environment detection and feature flags.

## 🌟 Key Features

### **Multi-Format Support**
```python
# Supports YAML, JSON, TOML, and ENV files
config = load_config('config/app.yaml')
config = load_config('config/app.json')
config = load_config('config/app.toml')
```

### **Environment Variable Overlays**
```python
# Environment variables automatically override file settings
# FKS_DATABASE_HOST=prod-db overrides database.host
config_manager = create_config_manager(env_prefix='FKS_')
```

### **Configuration Overlays and Merging**
```python
# Load multiple configuration files with priority merging
config = load_config([
    'config/base.yaml',
    'config/production.yaml',
    'config/local-overrides.yaml'
])
```

### **Cloud Provider Integration**
```python
# AWS Parameter Store
config = load_config('aws://parameter-store/myapp/')

# HashiCorp Consul
config = load_config('consul://localhost:8500/myapp/')

# Remote HTTP configuration
config = load_config('https://config-server.com/app-config.json')
```

### **Type-Safe Access**
```python
# Strongly typed configuration access
db_config: DatabaseConfig = config_manager.config.database
api_config: APIConfig = config_manager.config.api

# Type-safe method calls
db_url = db_config.get_url()
api_base_url = api_config.get_base_url()
```

### **Intelligent Path Management**
```python
# Automatic directory creation and path resolution
model_path = config_manager.get_models_path('lstm_model.pkl')
data_path = config_manager.get_output_path('results', 'analysis.csv')
log_path = config_manager.paths.logs_dir / 'app.log'
```

### **Configuration Validation**
```python
# Built-in validation with detailed error reporting
from fks.config import validate_config

result = validate_config(config)
if result.has_errors():
    for error in result.errors:
        print(f"Error: {error}")
```

### **Feature Flags and Environment Detection**
```python
from fks.config import get_feature_flag, is_production

# Feature flags with environment overrides
if get_feature_flag('enable_ml_predictions'):
    # ML features enabled
    pass

# Environment-aware configuration
if is_production():
    config_manager = create_config_manager('config/production.yaml')
```

## 📝 Configuration File Examples

### Basic YAML Configuration
```yaml
# config/app.yaml
app:
  name: "FKS Trading Systems"
  version: "2.1.0"
  environment: "production"

database:
  host: "localhost"
  port: 5432
  database: "fks_trading"
  username: "postgres"

api:
  host: "0.0.0.0"
  port: 8000
  debug: false

ml:
  model_type: "lstm"
  sequence_length: 60
  batch_size: 32
  learning_rate: 0.001

trading:
  symbol: "BTCUSDT"
  initial_balance: 10000.0
  risk_per_trade: 0.02
  stop_loss_pct: 0.05

paths:
  base_output_dir: "outputs"
  data_dir: "data"
  models_dir: "models"
  logs_dir: "logs"
```

### Environment Variables Override
```bash
# Environment variables (highest priority)
export FKS_DATABASE_HOST=prod-db.company.com
export FKS_DATABASE_PASSWORD=secure_password
export FKS_API_PORT=80
export FKS_ML_LEARNING_RATE=0.0005
export FKS_FEATURE_ENABLE_REAL_TIME_TRADING=true
```

## 🔄 Usage Patterns

### 1. **Simple Application Setup**
```python
from fks.config import create_config_manager

config_manager = create_config_manager()
db_host = config_manager.get('database.host', 'localhost')
```

### 2. **Multi-Environment Deployment**
```python
from fks.config import create_config_manager, is_production

if is_production():
    config_manager = create_config_manager('config/production.yaml')
else:
    config_manager = create_config_manager('config/development.yaml')
```

### 3. **Configuration with Overlays**
```python
from fks.config import load_config

config = load_config([
    'config/base.yaml',         # Base configuration
    'config/production.yaml',   # Environment-specific
    'config/local.yaml'         # Local overrides
])
```

### 4. **Cloud-Native Configuration**
```python
from fks.config import load_config

# Load from multiple cloud sources
config = load_config([
    'config/base.yaml',
    'aws://parameter-store/fks-trading/',
    'consul://consul.service.consul:8500/fks/'
])
```

### 5. **Type-Safe Configuration Access**
```python
from fks.config import create_config_manager, DatabaseConfig

config_manager = create_config_manager()

# Type-safe access
db_config: DatabaseConfig = config_manager.config.database
connection_url = db_config.get_url()

# Path utilities
model_file = config_manager.get_models_path('best_model.pkl')
```

## 🛡️ Security Features

- **Environment variable masking** for sensitive values
- **JWT token configuration** with secure defaults
- **Password validation** with configurable requirements
- **Rate limiting** configuration for API endpoints
- **Security headers** management for web applications

## 🔍 Monitoring and Observability

- **Configuration validation** with detailed error reporting
- **Health check endpoints** configuration
- **Metrics collection** setup and thresholds
- **Logging configuration** with multiple output formats
- **Alert thresholds** for system monitoring

## 📊 Advanced Features

### **Dynamic Configuration Updates**
```python
# Runtime configuration updates
config_manager.set('api.debug', True)
config_manager.reload()  # Reload from files
```

### **Configuration Templating**
```python
# Use default configuration as template
from fks.config import create_default_config

config = create_default_config()
config.set('database.host', 'my-custom-host')
```

### **Validation and Error Handling**
```python
from fks.config import validate_config

validation_result = validate_config(config)
if not validation_result.is_valid:
    print("Configuration errors:")
    for error in validation_result.errors:
        print(f"  - {error}")
```

## 🚀 Deployment Considerations

### **Production Checklist**
- ✅ Use environment variables for sensitive values
- ✅ Enable configuration validation
- ✅ Set up proper logging configuration
- ✅ Configure health check endpoints
- ✅ Set resource limits and monitoring thresholds
- ✅ Use encrypted configuration sources (AWS Parameter Store, etc.)

### **Docker Integration**
```dockerfile
# Environment variables in Docker
ENV FKS_ENVIRONMENT=production
ENV FKS_DATABASE_HOST=db.company.com
ENV FKS_API_PORT=8000
```

### **Kubernetes ConfigMaps**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fks-config
data:
  config.yaml: |
    database:
      host: "postgres-service"
      port: 5432
    api:
      host: "0.0.0.0"
      port: 8000
```

## 📚 API Reference

### **Main Classes**
- `FKSConfigManager` - Main configuration management class
- `Config` - Configuration container with dot-notation access
- `PathConfig` - Path configuration and management
- `ConfigProviderRegistry` - Provider registry and multi-source loading

### **Configuration Models**
- `DatabaseConfig` - Database connection configuration
- `APIConfig` - REST API server configuration
- `MLConfig` - Machine learning parameters
- `TradingConfig` - Trading strategy configuration
- `SecurityConfig` - Security and authentication settings

### **Factory Functions**
- `create_config_manager()` - Create configured manager instance
- `load_config()` - Load configuration from sources
- `create_default_config()` - Create configuration with defaults

### **Utility Functions**
- `validate_config()` - Validate configuration object
- `get_feature_flag()` - Get feature flag with overrides
- `is_production()` - Check if in production environment
- `setup_logging_from_config()` - Configure logging from config

## 🔧 Installation and Setup

```bash
# Install with basic dependencies
pip install fks-config

# Install with AWS support
pip install fks-config[aws]

# Install with Consul support  
pip install fks-config[consul]

# Install with all optional dependencies
pip install fks-config[all]
```

## 🤝 Contributing

The FKS configuration package is designed to be extensible and maintainable. Key areas for contribution:

- **New configuration providers** (e.g., etcd, Vault)
- **Additional validation rules** for configuration models
- **Enhanced path management** features
- **Performance optimizations** for large configuration files
- **Documentation and examples** for advanced use cases

## 📄 License

MIT License - see LICENSE file for details.