#!/usr/bin/env python3
# -*-coding:utf8-*-
"""Launch piper_leader_follower_bridge.py, the real-Piper <-> web-sim teleop bridge.

This is fully separate from, and does not affect, start_single_piper.launch.py or any
MoveIt launch file. It assumes the real driver (piper_single_ctrl_node, e.g. via
start_single_piper.launch.py) and rosbridge_websocket.launch.py are already running
elsewhere; it does not start either of them itself.

One-directional (real -> sim) is always active while this node runs. Bidirectional
(sim -> real) test mode defaults OFF and must be explicitly enabled -- either here via
the `bidirectional_enabled` launch argument, or later at runtime via the standard
`set_parameters` service (what the web GUI's checkbox calls through rosbridge). See
docs/teleop_bridge.md for the full safety rationale and topic contract.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    publish_rate_hz_arg = DeclareLaunchArgument(
        'publish_rate_hz',
        default_value='30.0',
        description='Downsample rate (Hz) for republishing real /joint_states (200Hz) onto '
                     '/sim/piper/joint_targets.'
    )
    bidirectional_enabled_arg = DeclareLaunchArgument(
        'bidirectional_enabled',
        default_value='false',
        description='Opt-in, higher-risk test mode: also forward /sim/piper/joint_state_feedback '
                     'to the real arm\'s joint_ctrl_single command topic, subject to the '
                     'enable_flag / heartbeat / per-step-clamp safety gates. OFF by default. '
                     'Maps to the web GUI\'s bidirectional-mode checkbox.'
    )
    heartbeat_timeout_ms_arg = DeclareLaunchArgument(
        'heartbeat_timeout_ms',
        default_value='500',
        description='If no /sim/piper/joint_state_feedback arrives within this many ms, '
                     'bidirectional forwarding stops immediately (only relevant when '
                     'bidirectional_enabled is true).'
    )
    max_step_rad_arg = DeclareLaunchArgument(
        'max_step_rad',
        default_value='0.05',
        description='Maximum per-message joint delta (rad) forwarded to the real arm, clamped '
                     'against the real arm\'s actual current position (only relevant when '
                     'bidirectional_enabled is true).'
    )
    real_joint_states_topic_arg = DeclareLaunchArgument(
        'real_joint_states_topic',
        default_value='/joint_states',
        description='Real driver joint-state input topic (200Hz, sensor_msgs/JointState).'
    )
    sim_joint_targets_topic_arg = DeclareLaunchArgument(
        'sim_joint_targets_topic',
        default_value='/sim/piper/joint_targets',
        description='Output topic driving the web sim\'s arm (sensor_msgs/JointState). '
                     'Deliberately NOT /joint_states -- the sim publishes its own state there.'
    )
    sim_joint_feedback_topic_arg = DeclareLaunchArgument(
        'sim_joint_feedback_topic',
        default_value='/sim/piper/joint_state_feedback',
        description='Sim-side current-state input topic (sensor_msgs/JointState), used as both '
                     'the bidirectional command source and the heartbeat signal.'
    )
    real_joint_ctrl_topic_arg = DeclareLaunchArgument(
        'real_joint_ctrl_topic',
        default_value='joint_ctrl_single',
        description='Real driver raw command topic (sensor_msgs/JointState). Only written to in '
                     'bidirectional mode, and only after all safety gates pass.'
    )
    enable_flag_topic_arg = DeclareLaunchArgument(
        'enable_flag_topic',
        default_value='enable_flag',
        description='Topic used to track whether the real arm has been enabled.'
    )
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Logging level (debug, info, warn, error, fatal).'
    )

    bridge_node = Node(
        package='piper',
        executable='piper_leader_follower_bridge',
        name='piper_leader_follower_bridge',
        output='screen',
        ros_arguments=['--log-level', LaunchConfiguration('log_level')],
        parameters=[{
            'publish_rate_hz': LaunchConfiguration('publish_rate_hz'),
            'bidirectional_enabled': LaunchConfiguration('bidirectional_enabled'),
            'heartbeat_timeout_ms': LaunchConfiguration('heartbeat_timeout_ms'),
            'max_step_rad': LaunchConfiguration('max_step_rad'),
            'real_joint_states_topic': LaunchConfiguration('real_joint_states_topic'),
            'sim_joint_targets_topic': LaunchConfiguration('sim_joint_targets_topic'),
            'sim_joint_feedback_topic': LaunchConfiguration('sim_joint_feedback_topic'),
            'real_joint_ctrl_topic': LaunchConfiguration('real_joint_ctrl_topic'),
            'enable_flag_topic': LaunchConfiguration('enable_flag_topic'),
        }],
    )

    return LaunchDescription([
        publish_rate_hz_arg,
        bidirectional_enabled_arg,
        heartbeat_timeout_ms_arg,
        max_step_rad_arg,
        real_joint_states_topic_arg,
        sim_joint_targets_topic_arg,
        sim_joint_feedback_topic_arg,
        real_joint_ctrl_topic_arg,
        enable_flag_topic_arg,
        log_level_arg,
        bridge_node,
    ])
