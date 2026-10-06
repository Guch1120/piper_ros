#!/usr/bin/env python3
# -*-coding:utf8-*-
"""Launch a SECOND instance of piper_leader_follower_bridge.py, targeting the web sim's
standalone-Piper scene (a separate, independent Piper instance in the sim repo, distinct
from the Cotyaka mobile-base robot that piper_leader_follower_bridge.launch.py targets).

Both this node and the default-node-name instance started by
piper_leader_follower_bridge.launch.py are the SAME executable/package -- only the ROS 2
node name and the sim-side topic names differ (via launch arguments / parameters, no
source-code duplication). Both read from the SAME real /joint_states; one-directional
mode is safe to fan out to both. See the module docstring in
piper/piper_leader_follower_bridge.py ("MULTIPLE INSTANCES") and
docs/teleop_bridge.md ("複数インスタンス同時稼働時の安全上の注意") for the full
multi-instance contract, in particular:

  - The node name changes from `piper_leader_follower_bridge` (default instance) to
    `piper_leader_follower_bridge_standalone` here. Any `set_parameters` /
    `get_parameters` service call from the web sim (e.g. a bidirectional-mode checkbox)
    MUST address `/piper_leader_follower_bridge_standalone/set_parameters` for THIS
    instance, not `/piper_leader_follower_bridge/set_parameters`.
  - Bidirectional mode is DANGEROUS if enabled on more than one instance at the same
    time (both would independently command the same real arm). This node includes a
    best-effort runtime guard (shared `bidirectional_claim_topic`, left at its default
    here so it matches the other instance) that refuses a LIVE set_parameters toggle
    into bidirectional mode while a peer instance's claim is fresh -- but it can NOT
    catch two instances both launched with bidirectional_enabled:=true from the start.
    Operators remain responsible for ensuring only ONE instance ever has bidirectional
    mode enabled at a time.

Like piper_leader_follower_bridge.launch.py, this assumes the real driver
(piper_single_ctrl_node, e.g. via start_single_piper.launch.py) and
rosbridge_websocket.launch.py are already running elsewhere; it does not start either
of them itself.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    node_name_arg = DeclareLaunchArgument(
        'node_name',
        default_value='piper_leader_follower_bridge_standalone',
        description='ROS 2 node name for this instance. Changing it also changes the '
                     '`set_parameters`/`get_parameters` service path the web sim must '
                     'call (rosbridge exposes these automatically per node name).'
    )
    publish_rate_hz_arg = DeclareLaunchArgument(
        'publish_rate_hz',
        default_value='30.0',
        description='Downsample rate (Hz) for republishing real /joint_states (200Hz) onto '
                     'sim_joint_targets_topic.'
    )
    bidirectional_enabled_arg = DeclareLaunchArgument(
        'bidirectional_enabled',
        default_value='false',
        description='Opt-in, higher-risk test mode: also forward sim_joint_feedback_topic '
                     'to the real arm\'s joint_ctrl_single command topic, subject to the '
                     'enable_flag / heartbeat / per-step-clamp safety gates. OFF by default. '
                     'DANGEROUS if also enabled on another bridge instance -- see the module '
                     'docstring above and docs/teleop_bridge.md before setting this true, '
                     'here or on the default-name instance, at the same time as the other.'
    )
    heartbeat_timeout_ms_arg = DeclareLaunchArgument(
        'heartbeat_timeout_ms',
        default_value='500',
        description='If no feedback arrives on sim_joint_feedback_topic within this many ms, '
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
        description='Real driver joint-state input topic (200Hz, sensor_msgs/JointState). '
                     'Same real arm as the default-name instance -- deliberately NOT changed.'
    )
    sim_joint_targets_topic_arg = DeclareLaunchArgument(
        'sim_joint_targets_topic',
        default_value='/sim/piper_standalone/joint_targets',
        description='Output topic driving the web sim\'s standalone-Piper scene '
                     '(sensor_msgs/JointState). Distinct from Cotyaka\'s /sim/piper/* topics '
                     'so the two sim scenes never collide.'
    )
    sim_joint_feedback_topic_arg = DeclareLaunchArgument(
        'sim_joint_feedback_topic',
        default_value='/sim/piper_standalone/joint_state_feedback',
        description='Standalone-Piper sim-side current-state input topic '
                     '(sensor_msgs/JointState), used as both the bidirectional command '
                     'source and the heartbeat signal. NOTE: as of this task this topic is '
                     'presumed but not confirmed to exist on the web-sim side (separate repo) '
                     '-- verify before relying on bidirectional mode here.'
    )
    real_joint_ctrl_topic_arg = DeclareLaunchArgument(
        'real_joint_ctrl_topic',
        default_value='joint_ctrl_single',
        description='Real driver raw command topic (sensor_msgs/JointState). Same real arm as '
                     'the default-name instance -- deliberately NOT changed. Only written to in '
                     'bidirectional mode, and only after all safety gates pass.'
    )
    enable_flag_topic_arg = DeclareLaunchArgument(
        'enable_flag_topic',
        default_value='enable_flag',
        description='Topic used to track whether the real arm has been enabled. Same real arm '
                     'as the default-name instance -- deliberately NOT changed.'
    )
    bidirectional_claim_topic_arg = DeclareLaunchArgument(
        'bidirectional_claim_topic',
        default_value='/piper_leader_follower_bridge/coordination/bidirectional_claim',
        description='Cross-instance coordination topic used ONLY to best-effort detect '
                     'whether another piper_leader_follower_bridge instance already has '
                     'bidirectional mode enabled (see docs/teleop_bridge.md). MUST match the '
                     'default-name instance\'s value (left at the shared default here) for the '
                     'guard to see it -- do NOT override this per sim target.'
    )
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Logging level (debug, info, warn, error, fatal).'
    )

    bridge_node = Node(
        package='piper',
        executable='piper_leader_follower_bridge',
        name=LaunchConfiguration('node_name'),
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
            'bidirectional_claim_topic': LaunchConfiguration('bidirectional_claim_topic'),
        }],
    )

    return LaunchDescription([
        node_name_arg,
        publish_rate_hz_arg,
        bidirectional_enabled_arg,
        heartbeat_timeout_ms_arg,
        max_step_rad_arg,
        real_joint_states_topic_arg,
        sim_joint_targets_topic_arg,
        sim_joint_feedback_topic_arg,
        real_joint_ctrl_topic_arg,
        enable_flag_topic_arg,
        bidirectional_claim_topic_arg,
        log_level_arg,
        bridge_node,
    ])
