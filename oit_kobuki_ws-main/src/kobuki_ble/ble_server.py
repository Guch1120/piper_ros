#!/usr/bin/env python3

import asyncio
import logging
import os
import signal
import struct
import sys
import time
from dataclasses import dataclass
from typing import Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node

try:
    from bless import (
        BlessServer,
        GATTAttributePermissions,
        GATTCharacteristicProperties,
    )
except ImportError as exc:
    print(f"Failed to import bless: {exc}", file=sys.stderr)
    raise


DEVICE_NAME = os.getenv("KOBUKI_BLE_DEVICE_NAME", "KobukiController")
SERVICE_UUID = os.getenv("KOBUKI_BLE_SERVICE_UUID", "12345678-1234-5678-1234-56789abcdef0")
COMMAND_UUID = os.getenv("KOBUKI_BLE_COMMAND_UUID", "12345678-1234-5678-1234-56789abcdef1")
STATUS_UUID = os.getenv("KOBUKI_BLE_STATUS_UUID", "12345678-1234-5678-1234-56789abcdef2")
CMD_VEL_TOPIC = os.getenv("KOBUKI_CMD_VEL_TOPIC", "/commands/velocity")

MAX_LINEAR_X = float(os.getenv("KOBUKI_MAX_LINEAR_SPEED", "0.15"))
MAX_ANGULAR_Z = float(os.getenv("KOBUKI_MAX_ANGULAR_SPEED", "0.40"))
COMMAND_TIMEOUT_SEC = float(os.getenv("KOBUKI_COMMAND_TIMEOUT_SEC", "5.0"))
SPIN_PERIOD_SEC = float(os.getenv("KOBUKI_SPIN_PERIOD_SEC", "0.05"))


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


@dataclass
class Command:
    linear_x: float
    angular_z: float

 
class CmdVelPublisher(Node):
    def __init__(self) -> None:
        super().__init__("kobuki_ble_server")
        self.publisher = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)
        self.last_command_time = 0.0
        self.last_command = Command(0.0, 0.0)
        self.zero_sent = True

    def publish_command(self, linear_x: float, angular_z: float, reason: str) -> None:
        linear_x = clamp(linear_x, -MAX_LINEAR_X, MAX_LINEAR_X)
        angular_z = clamp(angular_z, -MAX_ANGULAR_Z, MAX_ANGULAR_Z)

        msg = Twist()
        msg.linear.x = float(linear_x)
        msg.angular.z = float(angular_z)
        self.publisher.publish(msg)

        self.last_command_time = time.monotonic()
        self.last_command = Command(msg.linear.x, msg.angular.z)
        self.zero_sent = msg.linear.x == 0.0 and msg.angular.z == 0.0

        self.get_logger().info(
            f"Published {CMD_VEL_TOPIC} from {reason}: "
            f"linear.x={msg.linear.x:.3f} angular.z={msg.angular.z:.3f}"
        )

    def publish_stop(self, reason: str) -> None:
        if self.zero_sent:
            return
        self.publish_command(0.0, 0.0, reason)

    def enforce_timeout(self) -> None:
        if self.zero_sent:
            return
        if time.monotonic() - self.last_command_time >= COMMAND_TIMEOUT_SEC:
            self.publish_stop("command timeout")


class BleCommandServer:
    def __init__(self) -> None:
        self.logger = logging.getLogger("kobuki_ble_server")
        self.node = CmdVelPublisher()
        self.loop = asyncio.get_running_loop()
        self.server: Optional[BlessServer] = None
        self.shutdown_event = asyncio.Event()

    async def start(self) -> None:
        self.server = BlessServer(name=DEVICE_NAME)
        await self.server.add_new_service(SERVICE_UUID)
        await self.server.add_new_characteristic(
            SERVICE_UUID,
            COMMAND_UUID,
            GATTCharacteristicProperties.write,
            b"\x00" * 8,
            GATTAttributePermissions.writeable,
        )
        await self.server.add_new_characteristic(
            SERVICE_UUID,
            STATUS_UUID,
            GATTCharacteristicProperties.read | GATTCharacteristicProperties.notify,
            b"ready",
            GATTAttributePermissions.readable,
        )
        self.server.write_request_func = self._handle_write_request

        await self.server.start()
        self.logger.info("BLE advertising started as %s", DEVICE_NAME)

    async def stop(self) -> None:
        self.node.publish_stop("server shutdown")
        rclpy.spin_once(self.node, timeout_sec=0.0)

        if self.server is not None:
            await self.server.stop()
            self.logger.info("BLE server stopped")

        self.node.destroy_node()

    def _handle_write_request(self, characteristic, value, **kwargs) -> None:
        if not isinstance(value, (bytes, bytearray)):
            self.logger.warning("Ignoring non-bytes BLE payload: %r", type(value))
            return

        if len(value) != 8:
            self.logger.warning("Ignoring payload with invalid size: %d bytes", len(value))
            return

        try:
            linear_x, angular_z = struct.unpack("<ff", value)
        except struct.error as exc:
            self.logger.warning("Failed to unpack payload: %s", exc)
            return

        self.loop.call_soon_threadsafe(
            self.node.publish_command,
            linear_x,
            angular_z,
            "ble write",
        )

    async def spin(self) -> None:
        while not self.shutdown_event.is_set():
            rclpy.spin_once(self.node, timeout_sec=0.0)
            self.node.enforce_timeout()
            await asyncio.sleep(SPIN_PERIOD_SEC)

    def request_shutdown(self) -> None:
        self.shutdown_event.set()


async def async_main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    rclpy.init()
    server = BleCommandServer()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, server.request_shutdown)

    try:
        await server.start()
        await server.spin()
        return 0
    finally:
        await server.stop()
        rclpy.shutdown()


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
