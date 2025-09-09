"""
Enhanced FKS Python-NinjaTrader Bridge
Provides real-time data streaming, ML model serving, and performance analytics
"""

import asyncio
import json
import logging

import numpy as np
import pandas as pd
import redis
import uvicorn
import zmq.asyncio
from fastapi import FastAPI, WebSocket

logger = logging.getLogger(__name__)


class FKSBridge:
    def __init__(self, config_path: str = "bridge-config.json"):
        self.config = self.load_config(config_path)
        self.app = FastAPI(title="FKS Trading Bridge")
        self.zmq_context = zmq.asyncio.Context()
        self.redis_client = None
        self.market_data_sub = None
        self.signals_sub = None
        self.setup_routes()

    def load_config(self, path: str) -> dict:
        try:
            with open(path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return self.default_config()

    def default_config(self) -> dict:
        return {
            "redis_host": "localhost",
            "redis_port": 6379,
            "zmq_market_port": 5555,
            "zmq_signals_port": 5556,
            "host": "0.0.0.0",
            "port": 8002,
        }

    async def setup_connections(self):
        # Setup Redis
        self.redis_client = redis.from_url(
            f"redis://{self.config['redis_host']}:{self.config['redis_port']}"
        )

        # Setup ZMQ subscribers
        self.market_data_sub = self.zmq_context.socket(zmq.SUB)
        self.market_data_sub.connect(
            f"tcp://localhost:{self.config['zmq_market_port']}"
        )
        self.market_data_sub.subscribe(b"")

    def setup_routes(self):
        @self.app.get("/")
        async def read_root():
            return {"status": "FKS Bridge Active", "version": "2.0"}

        @self.app.websocket("/ws/market")
        async def market_websocket(websocket: WebSocket):
            await websocket.accept()
            try:
                # Ensure connections are setup
                if self.market_data_sub is None:
                    await self.setup_connections()

                # Verify connection was established
                if self.market_data_sub is None:
                    await websocket.send_json(
                        {"error": "Failed to establish connection"}
                    )
                    return

                while True:
                    data = await self.market_data_sub.recv_json()
                    await websocket.send_json(data)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            finally:
                await websocket.close()

        @self.app.get("/api/performance")
        async def get_performance():
            # Ensure redis_client is initialized
            if self.redis_client is None:
                await self.setup_connections()

            # Verify redis_client was established
            if self.redis_client is None:
                return {"error": "Redis connection failed"}

            # Get performance metrics from Redis
            metrics = self.redis_client.hgetall("fks:performance")
            if not metrics:
                return {}
            return metrics

    async def process_market_data(self):
        # Ensure connections are setup
        if self.market_data_sub is None:
            await self.setup_connections()

        # Verify connections were established
        if self.market_data_sub is None or self.redis_client is None:
            logger.error("Failed to establish required connections")
            return

        while True:
            try:
                data = await self.market_data_sub.recv_json()
                # Process and store in Redis
                self.redis_client.hset(
                    f"fks:market:{data['symbol']}", data["timestamp"], json.dumps(data)
                )
                # Calculate indicators
                await self.calculate_indicators(data)
            except Exception as e:
                logger.error(f"Market data processing error: {e}")

    async def calculate_indicators(self, data: dict):
        # Example: Calculate custom indicators
        symbol = data["symbol"]

        # Ensure redis_client is initialized
        if self.redis_client is None:
            await self.setup_connections()

        # Verify redis_client was established
        if self.redis_client is None:
            logger.error("Redis connection failed in calculate_indicators")
            return

        # Get recent data from Redis
        recent_data = self.redis_client.hgetall(f"fks:market:{symbol}")
        if len(recent_data) > 20:
            df = pd.DataFrame(
                [
                    json.loads(v.decode() if isinstance(v, bytes) else v)
                    for v in recent_data.values()
                ]
            )
            df["sma_20"] = df["close"].rolling(20).mean()
            df["rsi"] = self.calculate_rsi(df["close"])

            # Store calculated indicators
            self.redis_client.hset(
                f"fks:indicators:{symbol}",
                data["timestamp"],
                json.dumps(
                    {"sma_20": df["sma_20"].iloc[-1], "rsi": df["rsi"].iloc[-1]}
                ),
            )

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        prices = pd.to_numeric(prices, errors="coerce")
        prices = prices.astype(float)
        delta = prices.diff()
        gain = delta.copy().astype(float)
        gain[gain < 0] = 0
        loss = delta.copy().astype(float)
        loss[loss > 0] = 0
        loss = -loss
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    async def run(self):
        await self.setup_connections()

        # Start background tasks
        asyncio.create_task(self.process_market_data())

        # Run FastAPI
        config = uvicorn.Config(
            app=self.app,
            host=self.config.get("host", "0.0.0.0"),
            port=self.config.get("port", 8002),
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()
