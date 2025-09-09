"""Market-related event definitions (placeholder)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PriceTick:
	symbol: str
	price: float
	ts: datetime


__all__ = ["PriceTick"]

"""Market-related events"""
