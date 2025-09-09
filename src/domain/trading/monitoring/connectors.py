"""
NinjaTrader connector for ZMQ communication
"""

import json
import logging
from typing import Any, Dict, Optional

import zmq

logger = logging.getLogger(__name__)


class NinjaTraderConnector:
    """Connector for NinjaTrader integration via ZMQ"""

    def __init__(self, port: int = 5555):
        self.context = zmq.Context()
        self.socket = None
        self.port = port
        self.connected = False

    def connect(self):
        try:
            self.socket = self.context.socket(zmq.SUB)
            self.socket.connect(f"tcp://localhost:{self.port}")
            self.socket.setsockopt(zmq.SUBSCRIBE, b"")
            self.socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1 second timeout
            self.connected = True
            logger.info(f"Connected to NinjaTrader on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to NinjaTrader: {e}")
            self.connected = False

    def receive_data(self, timeout: int = 1000) -> Optional[Dict[str, Any]]:
        if not self.connected or not self.socket:
            return {}

        try:
            message = self.socket.recv_string(zmq.NOBLOCK)
            return json.loads(message)
        except zmq.Again:
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode message: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error receiving data: {e}")
            return None

    def disconnect(self):
        if self.socket:
            self.socket.close()
        self.context.term()
        self.connected = False
