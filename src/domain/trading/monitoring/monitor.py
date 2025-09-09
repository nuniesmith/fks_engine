"""
Main monitoring functionality with metrics collection
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import redis
from watchdog.observers import Observer

from .connectors import NinjaTraderConnector
from .log_parser import LogFileHandler

logger = logging.getLogger(__name__)


class FKSMetrics:
    """Metrics collector and analyzer for FKS trading system"""

    def __init__(self):
        self.trades = []
        self.signals = []
        self.errors = []
        self.start_time = datetime.now()
        self.performance_stats = {}

    def add_trade(self, trade_data: Dict[str, Any]):
        self.trades.append({**trade_data, "timestamp": datetime.now()})
        self._update_performance_stats()

    def add_signal(self, signal_data: Dict[str, Any]):
        self.signals.append({**signal_data, "timestamp": datetime.now()})

    def add_error(self, error_data: Dict[str, Any]):
        self.errors.append({**error_data, "timestamp": datetime.now()})

    def _update_performance_stats(self):
        if not self.trades:
            return

        df = pd.DataFrame(self.trades)
        if "pnl" in df.columns:
            total_pnl = df["pnl"].sum()
            win_rate = (df["pnl"] > 0).mean()
            avg_win = df[df["pnl"] > 0]["pnl"].mean() if (df["pnl"] > 0).any() else 0
            avg_loss = df[df["pnl"] < 0]["pnl"].mean() if (df["pnl"] < 0).any() else 0

            self.performance_stats = {
                "total_pnl": total_pnl,
                "total_trades": len(self.trades),
                "win_rate": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "profit_factor": abs(avg_win / avg_loss) if avg_loss != 0 else 0,
            }

    def _calculate_sharpe(
        self, returns: pd.Series, risk_free_rate: float = 0.02
    ) -> float:
        if len(returns) < 2:
            return 0.0
        excess_returns = returns - risk_free_rate / 252
        return excess_returns.mean() / excess_returns.std() * np.sqrt(252)

    def _calculate_max_drawdown(self, cumulative_returns: pd.Series) -> float:
        if len(cumulative_returns) < 2:
            return 0.0
        peak = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - peak) / peak
        return drawdown.min()

    def get_stats(self) -> Dict[str, Any]:
        stats = dict(self.performance_stats)
        stats.update(
            {
                "uptime": str(datetime.now() - self.start_time),
                "total_signals": len(self.signals),
                "total_errors": len(self.errors),
                "last_updated": datetime.now().isoformat(),
            }
        )
        return stats


class FKSMonitor:
    """Main monitoring application"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.metrics = FKSMetrics()
        self.connector = NinjaTraderConnector(config.get("zmq_port", 5555))
        self.observer = Observer()
        self.running = False

        # Redis connection (optional)
        self.redis_client = None
        if config.get("use_redis", False):
            try:
                self.redis_client = redis.Redis(
                    host="localhost", port=6379, decode_responses=True
                )
                self.redis_client.ping()
                logger.info("Connected to Redis")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")
                self.redis_client = None

    def start(self):
        """Start the monitoring system"""
        logger.info("Starting FKS Master...")
        self.running = True

        # Connect to NinjaTrader
        self.connector.connect()

        # Setup log file monitoring
        if self.config.get("monitor_logs", True):
            log_dir = self.config.get("log_dir", "./logs")
            if os.path.exists(log_dir):
                handler = LogFileHandler(self.metrics)
                self.observer.schedule(handler, log_dir, recursive=True)
                self.observer.start()
                logger.info(f"Monitoring log directory: {log_dir}")

        # Start main monitoring loop
        try:
            self._monitor_loop()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.stop()

    def stop(self):
        """Stop the monitoring system"""
        self.running = False
        self.observer.stop()
        self.observer.join()
        self.connector.disconnect()
        logger.info("FKS Master stopped")

    def _monitor_loop(self):
        """Main monitoring loop"""
        last_metrics_time = time.time()
        metrics_interval = self.config.get("metrics_interval", 60)

        while self.running:
            try:
                # Check for ZMQ data
                data = self.connector.receive_data()
                if data:
                    self._process_zmq_data(data)

                # Periodic metrics reporting
                current_time = time.time()
                if current_time - last_metrics_time >= metrics_interval:
                    self._report_metrics()
                    last_metrics_time = current_time

                time.sleep(0.1)  # Small delay to prevent busy waiting

            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                time.sleep(1)

    def _process_zmq_data(self, data: Dict[str, Any]):
        """Process data received from ZMQ"""
        try:
            if data.get("type") == "trade":
                self.metrics.add_trade(data)
            elif data.get("type") == "signal":
                self.metrics.add_signal(data)
            elif data.get("type") == "error":
                self.metrics.add_error(data)

            # Store in Redis if available
            if self.redis_client:
                key = f"fks:data:{datetime.now().strftime('%Y%m%d%H%M%S')}"
                self.redis_client.setex(key, 3600, json.dumps(data))  # 1 hour TTL

        except Exception as e:
            logger.error(f"Error processing ZMQ data: {e}")

    def _report_metrics(self):
        """Report current metrics"""
        stats = self.metrics.get_stats()
        logger.info(f"Performance Stats: {json.dumps(stats, indent=2)}")

        # Store metrics in Redis
        if self.redis_client:
            self.redis_client.hset("fks:performance", mapping=stats)
