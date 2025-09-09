"""
Rithmic Adapter (scaffold)

This module is a placeholder for integrating R Protocol / Rithmic data and trading.
It provides a minimal interface contract to support:
  - authentication (demo/real)
  - fetching historical bars (OHLCV)
  - subscribing to realtime data
  - basic order placement/management (future work)

Until the SDK is fully wired, the adapter can run in mock mode controlled by env:
  - RITHMIC_MOCK=1

Environment variables expected for real connectivity:
  - RITHMIC_USERNAME
  - RITHMIC_PASSWORD
  - RITHMIC_APPKEY
  - RITHMIC_SYSTEM (optional; e.g., "Rithmic Paper Trading")

Once ready, this file should import and initialize the actual SDK provided under
`src/staging/RProtocolAPI.0.84.0.0` and use certificates from the attached package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
import os


@dataclass
class RithmicConfig:
    username: Optional[str] = None
    password: Optional[str] = None
    appkey: Optional[str] = None
    system: Optional[str] = None  # e.g., "Rithmic Paper Trading"
    mock: bool = False

    @classmethod
    def from_env(cls) -> "RithmicConfig":
        return cls(
            username=os.getenv("RITHMIC_USERNAME"),
            password=os.getenv("RITHMIC_PASSWORD"),
            appkey=os.getenv("RITHMIC_APPKEY"),
            system=os.getenv("RITHMIC_SYSTEM"),
            mock=str(os.getenv("RITHMIC_MOCK", "0")).lower() in ("1", "true", "yes"),
        )


class RithmicClient:
    """Minimal interface for future R Protocol connectivity."""

    def __init__(self, config: Optional[RithmicConfig] = None):
        self.config = config or RithmicConfig.from_env()
        self._connected = False

    def connect(self) -> bool:
        if self.config.mock:
            self._connected = True
            return True
        # TODO: Initialize R Protocol SDK session here
        # Validate presence of credentials first
        if not (self.config.username and self.config.password and self.config.appkey):
            return False
        # Placeholder for real implementation
        self._connected = False
        return False

    def is_connected(self) -> bool:
        return self._connected

    def get_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Return OHLCV records.
        In mock mode, this should be replaced by fallback data in the caller.
        """
        raise NotImplementedError("RithmicClient.get_ohlcv not implemented yet")

    def close(self) -> None:
        # TODO: Close SDK session
        self._connected = False
