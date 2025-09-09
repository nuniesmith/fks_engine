# FKS Engine Service

Backtesting & orchestration layer coordinating data + transformer services.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install .
python -m fks_engine.main
```

## Endpoints

(Provided by template framework + custom: /backtest, /signals, /forecast)

## Next Steps

- Replace simple MA strategy with pluggable strategy registry
- Add persistent caching for fetched data
- Integrate tracing & metrics
