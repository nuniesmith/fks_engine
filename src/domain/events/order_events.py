"""Order-related event definitions (placeholder)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class OrderFilled:
	order_id: str
	symbol: str
	qty: float
	price: float
	ts: datetime


__all__ = ["OrderFilled"]

"""Order-related events"""
