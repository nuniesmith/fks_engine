"""
Log parsing and file monitoring functionality
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)


class LogParser:
    """Parser for NinjaTrader log entries"""

    def parse_line(self, line: str) -> Optional[Dict[str, Any]]:
        if not line:
            return {}

        # Parse different log entry types
        if "TRADE:" in line:
            return self._parse_trade_entry(line)
        elif "SIGNAL:" in line:
            return self._parse_signal_entry(line)
        elif "ERROR:" in line or "EXCEPTION:" in line:
            return self._parse_error_entry(line)

        return {}

    def _parse_trade_entry(self, line: str) -> Dict[str, Any]:
        # Example: "2023-12-25 10:30:00 TRADE: BUY EURUSD 0.1 @ 1.1050 PnL: +15.5"
        try:
            parts = line.split()
            return {
                "type": "trade",
                "data": {
                    "timestamp": f"{parts[0]} {parts[1]}",
                    "action": parts[3],
                    "symbol": parts[4],
                    "quantity": float(parts[5]),
                    "price": float(parts[7]),
                    "pnl": float(parts[9].replace("+", "")),
                },
            }
        except (IndexError, ValueError):
            return {}

    def _parse_signal_entry(self, line: str) -> Dict[str, Any]:
        # Example: "2023-12-25 10:30:00 SIGNAL: BUY EURUSD Confidence: 0.85"
        try:
            parts = line.split()
            return {
                "type": "signal",
                "data": {
                    "timestamp": f"{parts[0]} {parts[1]}",
                    "action": parts[3],
                    "symbol": parts[4],
                    "confidence": float(parts[6]),
                },
            }
        except (IndexError, ValueError):
            return {}

    def _parse_error_entry(self, line: str) -> Dict[str, Any]:
        return {
            "type": "error",
            "data": {"timestamp": datetime.now().isoformat(), "message": line},
        }


class LogFileHandler(FileSystemEventHandler):
    """Handler for monitoring NinjaTrader log files"""

    def __init__(self, metrics):
        self.metrics = metrics
        self.parser = LogParser()
        self.processed_lines = {}

    def on_modified(self, event):
        if event.is_directory:
            return

        if str(event.src_path).endswith(".log"):
            src_path = str(event.src_path)
            self._process_log_file(src_path)

    def _process_log_file(self, filepath: str):
        try:
            with open(filepath, "r") as f:
                lines = f.readlines()

            # Process only new lines
            last_processed = self.processed_lines.get(filepath, 0)
            new_lines = lines[last_processed:]

            for line in new_lines:
                parsed = self.parser.parse_line(line.strip())
                if parsed:
                    if parsed["type"] == "trade":
                        self.metrics.add_trade(parsed["data"])
                    elif parsed["type"] == "signal":
                        self.metrics.add_signal(parsed["data"])
                    elif parsed["type"] == "error":
                        self.metrics.add_error(parsed["data"])

            self.processed_lines[filepath] = len(lines)

        except Exception as e:
            logger.error(f"Error processing log file {filepath}: {e}")
