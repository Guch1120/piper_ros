#!/usr/bin/env python3
# -*-coding:utf8-*-
"""Start rosbridge_websocket (+ rosapi) so an external WebSocket client (e.g. the
web-based MuJoCo sim used for leader/follower teleop, see piper_leader_follower_bridge.py
and docs/teleop_bridge.md) can talk to this ROS 2 graph over the rosbridge v2 JSON protocol.

This launch file only starts the generic rosbridge transport; it does NOT start
piper_leader_follower_bridge.py (launch that separately, see
piper_leader_follower_bridge.launch.py). Nothing in this file touches
piper_single_ctrl_node.py / moveit_bridge.py.

Requires ros-humble-rosbridge-suite (already apt-installed in docker/dockerfile.kobuki;
install it on bare-metal hosts too: `sudo apt install ros-humble-rosbridge-suite`).

Default is plain ws:// on the conventional rosbridge port 9090, suitable for LAN use
(matches the convention used by the web-sim side's own docs, e.g.
sirius-mujoco-sim/docs/ROS2_QUICKSTART.md, which also defaults to port 9090).

TLS / wss:// (for later, if the web sim is ever served over HTTPS and therefore
requires wss:// per browser mixed-content rules):
  rosbridge_websocket itself supports 'ssl:=true certfile:=... keyfile:=...' launch
  arguments (terminate TLS directly in rosbridge_websocket), OR terminate TLS in front
  of it with a reverse proxy / sidecar container that forwards to this plain ws:// port
  (this is the approach sirius-mujoco-sim documents as its 'rosbridge_tls' container on
  port 9091, self-signed cert generated on first boot). Neither is wired up here; add an
  'ssl' launch argument + certfile/keyfile parameters to the Node below, or add a
  reverse-proxy container, when wss:// is actually needed.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    port_arg = DeclareLaunchArgument(
        'port',
        default_value='9090',
        description='TCP port for rosbridge_websocket (plain ws://). Conventional default is 9090.'
    )
    address_arg = DeclareLaunchArgument(
        'address',
        default_value='',
        description='Bind address for the websocket server. Empty string = all interfaces (0.0.0.0), '
                     'matching rosbridge_websocket\'s own default. Restrict to a specific NIC on shared hosts.'
    )
    retry_startup_delay_arg = DeclareLaunchArgument(
        'retry_startup_delay',
        default_value='5.0',
        description='Seconds rosbridge_websocket waits before retrying if the port is busy on startup.'
    )
    call_services_in_new_thread_arg = DeclareLaunchArgument(
        'call_services_in_new_thread',
        default_value='true',
        description='Run rosbridge service calls in a separate thread so a slow/blocking service '
                     '(e.g. this package\'s enable_srv, which polls CAN status for up to 5s) does not '
                     'stall the websocket event loop for other clients/topics.'
    )

    rosbridge_websocket_node = Node(
        package='rosbridge_server',
        executable='rosbridge_websocket',
        name='rosbridge_websocket',
        output='screen',
        parameters=[{
            'port': LaunchConfiguration('port'),
            'address': LaunchConfiguration('address'),
            'retry_startup_delay': LaunchConfiguration('retry_startup_delay'),
            'call_services_in_new_thread': LaunchConfiguration('call_services_in_new_thread'),
        }],
    )

    # rosapi provides /rosapi/nodes, /rosapi/topics, /rosapi/node_details, etc.
    # The web-sim side's "ROS診断" (ROS diagnostics) tab already expects these
    # (see sirius-mujoco-sim/cotyaka/docs/ros_interface.md), so start it alongside
    # rosbridge_websocket by default.
    rosapi_node = Node(
        package='rosapi',
        executable='rosapi_node',
        name='rosapi',
        output='screen',
    )

    return LaunchDescription([
        port_arg,
        address_arg,
        retry_startup_delay_arg,
        call_services_in_new_thread_arg,
        rosbridge_websocket_node,
        rosapi_node,
    ])
