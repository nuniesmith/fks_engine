"""System-related event definitions (placeholder)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Heartbeat:
	ts: datetime


__all__ = ["Heartbeat"]

"""System events"""
