#!/usr/bin/env python3
# -*-coding:utf8-*-
"""piper_leader_follower_bridge

Leader/follower teleop bridge between the REAL Piper arm ("leader") and the
web-based MuJoCo simulator ("follower"), connected to this ROS 2 graph over
rosbridge_websocket (see rosbridge_websocket.launch.py).

This is a NEW, SEPARATE, fully opt-in node. It does not import, modify, or in any
way affect piper_single_ctrl_node.py or moveit_bridge.py. If this node is never
launched, nothing about existing behavior changes.

--------------------------------------------------------------------------------
MODE 1: one-directional (real -> sim), ALWAYS ACTIVE whenever this node runs
--------------------------------------------------------------------------------
  Subscribes:  /joint_states            (sensor_msgs/JointState, ~200 Hz, published by
                                          piper_single_ctrl_node.py from CAN via piper_sdk)
  Publishes:   /sim/piper/joint_targets (sensor_msgs/JointState, downsampled to
                                          `publish_rate_hz`, default 30 Hz)

  This direction carries ZERO risk to the hardware: it only reads state and writes to
  a topic the real driver never subscribes to. It never touches the real arm.

  NOTE: we deliberately do NOT republish onto a topic literally named /joint_states on
  the sim side -- the web sim already publishes its OWN /joint_states for its own
  simulated state, and colliding with that would corrupt the sim's self-reporting.
  /sim/piper/joint_targets is the sim's dedicated "drive my arm to this pose" topic.

--------------------------------------------------------------------------------
MODE 2: bidirectional test mode (sim -> real), OPT-IN, OFF BY DEFAULT
--------------------------------------------------------------------------------
  Enabled via ROS 2 parameter `bidirectional_enabled` (bool, default False), settable
  live via the standard `set_parameters` service -- this is exactly what a web GUI
  checkbox calls through rosbridge's call_service (rosbridge exposes
  /piper_leader_follower_bridge/set_parameters automatically for any ROS 2 node; no
  extra service needs to be written here).

  When enabled, ADDITIONALLY:
  Subscribes:  /sim/piper/joint_state_feedback (sensor_msgs/JointState, the sim's
                                                 current simulated arm state; also
                                                 doubles as the heartbeat -- see below)
  Publishes:   joint_ctrl_single              (sensor_msgs/JointState, the REAL driver's
                                                 raw command topic -- piper_single_ctrl_node's
                                                 joint_callback converts this directly to SDK
                                                 units and calls piper.JointCtrl()/GripperCtrl()
                                                 over CAN with NO rate limiting or smoothing of
                                                 its own beyond the enable_flag gate)

  Because joint_ctrl_single is a raw, unprotected pass-through straight to CAN, this
  bridge is the ONLY safety layer standing between "whatever the browser sends" and the
  physical motors. A message is forwarded to the real arm ONLY when ALL of the
  following hold, checked fresh on every incoming feedback message:

    (a) enabled:   the real arm has been enabled (tracked via the `enable_flag` topic,
                    the same topic piper_single_ctrl_node.py's own enable_callback
                    listens to -- see _on_enable_flag() below for the important caveat
                    that this is a best-effort *locally tracked* flag, not a live
                    hardware ACK read back from the arm).
    (b) heartbeat: a /sim/piper/joint_state_feedback message has been received within
                    the last `heartbeat_timeout_ms` (default 500 ms). Because forwarding
                    only ever happens synchronously inside the feedback callback itself,
                    "no recent message -> no forwarding" holds by construction; a
                    background watchdog timer additionally logs loss/recovery
                    transitions so operators get a clear warning even if nothing is
                    actively being commanded at that instant.
    (c) clamped:   every joint's commanded position is clamped to within
                    `max_step_rad` (default 0.05 rad) of the REAL arm's most recently
                    observed ACTUAL position (from /joint_states) -- not of the previous
                    *command*. Clamping against ground truth means a stale or
                    wildly-different sim pose (e.g. right after a heartbeat gap, or if
                    the sim and real arm have drifted apart) can only ever nudge the
                    real arm by a bounded amount per message, however large the jump in
                    the sim actually was. This mirrors the "configurable safety limits to
                    cap per-step joint movement" pattern used by the LeRobot
                    `lerobot_robot_piper` leader/follower integration for this exact arm.

  Design rationale (why a software bridge, and why these specific gates) is written up
  in docs/teleop_bridge.md under "設計根拠"; it references AgileX's own CAN-level
  MasterSlaveConfig (physical dual-arm only, not applicable to a simulator), the
  LeRobot Piper integration's per-step clamp pattern, and AgileX's own Quest-3-VR-teleop
  reference architecture ("external controller -> Python bridge -> piper_sdk -> CAN",
  ~50 Hz sampling, start conservative and ramp up). This node's topic-based interface
  intentionally matches that same shape, so a future VR-driven client could plug into
  the same /sim/piper/joint_targets and /sim/piper/joint_state_feedback topics without
  any changes here.

  Fail-safe joint-name handling: if the incoming feedback message is missing any of the
  6 arm joint names, forwarding for that message is skipped entirely and a throttled
  warning is logged. We do NOT fall back to piper_single_ctrl_node's own dict-based
  `.get(name, 0)` defaulting, because that would silently command a missing joint to 0
  -- exactly the kind of surprise motion this bridge exists to prevent.

--------------------------------------------------------------------------------
MULTIPLE INSTANCES (multiple sim targets against the SAME real arm)
--------------------------------------------------------------------------------
  All topic names (real- and sim-side) are ROS 2 parameters (see the declare_parameter
  calls below), so more than one instance of this SAME node can be launched under
  DISTINCT node names, each pointed at a different sim target's topics (e.g. Cotyaka's
  /sim/piper/* vs a standalone-Piper scene's /sim/piper_standalone/*), while all reading
  the SAME real /joint_states. One-directional mode fans out safely to any number of
  instances -- it never writes to the real arm.

  Bidirectional mode is a different story: if TWO instances both had it enabled, BOTH
  would independently forward their own sim's feedback straight to the same real
  joint_ctrl_single topic, fighting each other. This node includes a best-effort,
  NOT-a-hardware-interlock guard against that (see the "Cross-instance bidirectional-
  mode coordination" methods below and `bidirectional_claim_topic`): live set_parameters
  toggles are refused if a peer instance's claim was heard recently. This guard cannot
  catch two instances that both start up with bidirectional_enabled=true already set in
  launch args (see the startup warning below) -- operators remain responsible for never
  enabling bidirectional mode on more than one instance at a time. See
  docs/teleop_bridge.md "複数インスタンス同時稼働時の安全上の注意" for full detail.
"""
import time
from typing import Dict, List, Optional

import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import SetParametersResult
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool, String


# Cross-instance bidirectional-mode coordination. This topic name is intentionally
# NOT sim-target-specific (i.e. NOT parameterized alongside sim_joint_targets_topic /
# sim_joint_feedback_topic) -- every bridge instance that could possibly command the
# SAME real arm must publish/subscribe the SAME claim topic for the guard below to see
# every peer, regardless of which sim target (Cotyaka, standalone-Piper, ...) each
# instance talks to. It IS still exposed as a parameter so a deployment can rename it
# if needed, but both launch files ship with the identical default on purpose. See
# docs/teleop_bridge.md "複数インスタンス同時稼働時の安全上の注意" for the full
# rationale and its known limitation (best-effort, not a hardware interlock).
DEFAULT_BIDIRECTIONAL_CLAIM_TOPIC: str = '/piper_leader_follower_bridge/coordination/bidirectional_claim'
BIDIRECTIONAL_CLAIM_PERIOD_S: float = 1.0
BIDIRECTIONAL_CLAIM_STALE_S: float = 3.0 * BIDIRECTIONAL_CLAIM_PERIOD_S


# ---------------------------------------------------------------------------------
# TODO(sim-side joint name mapping):
# piper_single_ctrl_node.py publishes/expects these exact names (see its
# PublishArmJointAndGripper() / joint_callback()): 'joint1'..'joint6', 'gripper'.
#
# The web sim's expected names/order for /sim/piper/joint_targets and
# /sim/piper/joint_state_feedback are determined by armJointIndex() in
# sirius-mujoco-sim/src/robots/cotyaka/runtime/Runtime.ts (a DIFFERENT repo, not
# available here to verify directly). Related evidence from that repo's own docs
# (cotyaka/docs/ros_interface.md): its MoveIt/trajectory bridge applies incoming
# trajectories "joint1〜joint8ヘ名前で適用" (by name, joint1..joint8), suggesting the
# gripper may be split across two named joints (e.g. joint7/joint8) rather than a
# single 'gripper' entry -- this is NOT confirmed and must be checked against the
# actual Runtime.ts before relying on it.
#
# This map is intentionally an IDENTITY mapping by default (real driver names pass
# through unchanged). Adjust the VALUES ONLY (never the keys, which must keep matching
# piper_single_ctrl_node.py) once the real sim-side names are confirmed. Both
# directions use this same table (REVERSE_JOINT_NAME_MAP below is derived from it).
# ---------------------------------------------------------------------------------
JOINT_NAME_MAP: Dict[str, str] = {
    'joint1': 'joint1',
    'joint2': 'joint2',
    'joint3': 'joint3',
    'joint4': 'joint4',
    'joint5': 'joint5',
    'joint6': 'joint6',
    'gripper': 'gripper',
}
REVERSE_JOINT_NAME_MAP: Dict[str, str] = {v: k for k, v in JOINT_NAME_MAP.items()}
REAL_ARM_JOINT_NAMES: List[str] = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6']
REAL_GRIPPER_JOINT_NAME: str = 'gripper'


class PiperLeaderFollowerBridge(Node):
    """See module docstring for the full one-directional / bidirectional contract."""

    def __init__(self) -> None:
        super().__init__('piper_leader_follower_bridge')

        # --- parameters ------------------------------------------------------------
        self.declare_parameter('publish_rate_hz', 30.0)
        self.declare_parameter('bidirectional_enabled', False)
        self.declare_parameter('heartbeat_timeout_ms', 500)
        self.declare_parameter('max_step_rad', 0.05)
        self.declare_parameter('real_joint_states_topic', '/joint_states')
        self.declare_parameter('sim_joint_targets_topic', '/sim/piper/joint_targets')
        self.declare_parameter('sim_joint_feedback_topic', '/sim/piper/joint_state_feedback')
        self.declare_parameter('real_joint_ctrl_topic', 'joint_ctrl_single')
        self.declare_parameter('enable_flag_topic', 'enable_flag')
        self.declare_parameter('bidirectional_claim_topic', DEFAULT_BIDIRECTIONAL_CLAIM_TOPIC)

        self.publish_rate_hz: float = float(self.get_parameter('publish_rate_hz').value)
        self.bidirectional_enabled: bool = bool(self.get_parameter('bidirectional_enabled').value)
        self.heartbeat_timeout_ms: int = int(self.get_parameter('heartbeat_timeout_ms').value)
        self.max_step_rad: float = float(self.get_parameter('max_step_rad').value)

        real_joint_states_topic = self.get_parameter('real_joint_states_topic').value
        sim_joint_targets_topic = self.get_parameter('sim_joint_targets_topic').value
        sim_joint_feedback_topic = self.get_parameter('sim_joint_feedback_topic').value
        real_joint_ctrl_topic = self.get_parameter('real_joint_ctrl_topic').value
        enable_flag_topic = self.get_parameter('enable_flag_topic').value
        bidirectional_claim_topic = self.get_parameter('bidirectional_claim_topic').value

        self.get_logger().info(
            f"{self.get_name()} starting: publish_rate_hz={self.publish_rate_hz}, "
            f"bidirectional_enabled={self.bidirectional_enabled} (OFF unless explicitly set), "
            f"heartbeat_timeout_ms={self.heartbeat_timeout_ms}, max_step_rad={self.max_step_rad}, "
            f"sim_joint_targets_topic={sim_joint_targets_topic}, "
            f"sim_joint_feedback_topic={sim_joint_feedback_topic}, "
            f"bidirectional_claim_topic={bidirectional_claim_topic}"
        )
        if self.bidirectional_enabled:
            self.get_logger().warn(
                "bidirectional_enabled=True at startup: this node will forward sim feedback "
                "to the REAL arm's command topic once enable_flag/heartbeat/clamp conditions "
                "are met. Double check this is intentional. NOTE: the multi-instance "
                "bidirectional guard (see docs/teleop_bridge.md) only protects live "
                "set_parameters toggles -- it CANNOT catch two instances both starting up "
                "with bidirectional_enabled=true already set in their launch args, since "
                "neither has had time to announce itself yet. Never launch more than one "
                "instance with bidirectional_enabled:=true from the start."
            )

        # --- runtime state -----------------------------------------------------------
        self._latest_real_joint_state: Optional[JointState] = None
        self._latest_real_positions_by_name: Dict[str, float] = {}
        self._real_arm_enabled: bool = False
        self._last_feedback_monotonic: Optional[float] = None
        self._heartbeat_ok: bool = False  # cached watchdog result; only log on transition
        # node_name -> monotonic time of last-seen bidirectional-active claim from a
        # PEER instance (never includes our own claims -- see _on_bidirectional_claim).
        self._remote_bidirectional_claims: Dict[str, float] = {}

        # --- publishers --------------------------------------------------------------
        self.sim_target_pub = self.create_publisher(JointState, sim_joint_targets_topic, 10)
        self.real_ctrl_pub = self.create_publisher(JointState, real_joint_ctrl_topic, 10)
        # Cross-instance coordination (see BIDIRECTIONAL_CLAIM_* constants above and
        # docs/teleop_bridge.md): every instance publishes AND subscribes the same
        # claim topic so each can see whether a PEER instance currently has
        # bidirectional mode active, regardless of which sim target it drives.
        self._claim_pub = self.create_publisher(String, bidirectional_claim_topic, 10)

        # --- subscriptions -------------------------------------------------------------
        self.create_subscription(JointState, real_joint_states_topic, self._on_real_joint_state, 10)
        self.create_subscription(Bool, enable_flag_topic, self._on_enable_flag, 10)
        self.create_subscription(JointState, sim_joint_feedback_topic, self._on_sim_feedback, 10)
        self.create_subscription(String, bidirectional_claim_topic, self._on_bidirectional_claim, 10)

        # --- timers --------------------------------------------------------------------
        # Downsample timer for MODE 1: latch-and-republish the most recent /joint_states
        # sample at publish_rate_hz instead of blasting the sim at the driver's 200 Hz.
        self._downsample_period_s = self._safe_period(self.publish_rate_hz, default_hz=30.0)
        self._downsample_timer = self.create_timer(self._downsample_period_s, self._on_downsample_tick)

        # Watchdog timer for MODE 2: polls faster than the heartbeat timeout so loss is
        # detected and logged promptly even between feedback messages.
        watchdog_period_s = max(0.05, (self.heartbeat_timeout_ms / 1000.0) / 2.0)
        self._watchdog_timer = self.create_timer(watchdog_period_s, self._on_watchdog_tick)

        # Cross-instance coordination: while OUR bidirectional mode is active, announce
        # it periodically so any PEER instance's guard (see _other_active_peer() /
        # _on_set_parameters) can see us. Runs independently of bidirectional_enabled's
        # value at any given tick -- the tick handler itself checks the current value.
        self._claim_timer = self.create_timer(BIDIRECTIONAL_CLAIM_PERIOD_S, self._on_claim_tick)

        # Allow `bidirectional_enabled` (and the other safety parameters) to be toggled
        # live via the standard set_parameters service -- this is what the web GUI's
        # "bidirectional test mode" checkbox calls through rosbridge's call_service.
        self.add_on_set_parameters_callback(self._on_set_parameters)

    # ------------------------------------------------------------------------------
    # MODE 1: real -> sim (always active)
    # ------------------------------------------------------------------------------
    def _on_real_joint_state(self, msg: JointState) -> None:
        # Just cache the latest sample; the actual (rate-limited) publish happens on
        # the downsample timer tick below. This is a simple "keep latest" low-pass,
        # not a smoothing filter -- sufficient here since the source is already a
        # clean, jitter-free CAN-sourced joint state at a fixed 200 Hz.
        self._latest_real_joint_state = msg
        self._latest_real_positions_by_name = dict(zip(msg.name, msg.position))

    def _on_downsample_tick(self) -> None:
        msg = self._latest_real_joint_state
        if msg is None:
            return
        out = JointState()
        out.header = msg.header
        out.name = [JOINT_NAME_MAP.get(n, n) for n in msg.name]
        out.position = list(msg.position)
        out.velocity = list(msg.velocity)
        out.effort = list(msg.effort)
        self.sim_target_pub.publish(out)

    # ------------------------------------------------------------------------------
    # Shared safety state
    # ------------------------------------------------------------------------------
    def _on_enable_flag(self, msg: Bool) -> None:
        # NOTE (important caveat): this only tracks the last message seen on
        # enable_flag -- the SAME fire-and-forget topic piper_single_ctrl_node.py's
        # own enable_callback() listens to. It is a best-effort local mirror of
        # "someone last commanded enable=True", not a live hardware ACK read back
        # from the arm's actual FOC driver-enable status (which piper_sdk exposes via
        # GetArmLowSpdInfoMsgs().motor_N.foc_status.driver_enable_status, not
        # currently republished on any topic this bridge can subscribe to). If a
        # future revision adds a real readback topic, prefer that here instead.
        was_enabled = self._real_arm_enabled
        self._real_arm_enabled = bool(msg.data)
        if was_enabled and not self._real_arm_enabled and self.bidirectional_enabled:
            self.get_logger().warn(
                "enable_flag went False: bidirectional forwarding will stop until re-enabled."
            )

    def _on_watchdog_tick(self) -> None:
        if not self.bidirectional_enabled:
            return
        if self._last_feedback_monotonic is None:
            return  # never received a feedback message yet; nothing to age out
        elapsed_ms = (time.monotonic() - self._last_feedback_monotonic) * 1000.0
        stale = elapsed_ms > self.heartbeat_timeout_ms
        if stale and self._heartbeat_ok:
            self.get_logger().warn(
                f"bidirectional: heartbeat LOST ({elapsed_ms:.0f} ms since last "
                f"/sim/piper/joint_state_feedback, timeout={self.heartbeat_timeout_ms} ms) "
                f"-- forwarding to the real arm is suspended until it resumes."
            )
            self._heartbeat_ok = False
        elif not stale and not self._heartbeat_ok:
            self.get_logger().info("bidirectional: heartbeat restored, forwarding resumed.")
            self._heartbeat_ok = True

    # ------------------------------------------------------------------------------
    # Cross-instance bidirectional-mode coordination (best-effort, NOT a hardware
    # interlock -- see docs/teleop_bridge.md "複数インスタンス同時稼働時の安全上の
    # 注意"). Only meaningful when more than one piper_leader_follower_bridge
    # instance is running against the SAME real arm (e.g. one per sim target).
    # ------------------------------------------------------------------------------
    def _on_claim_tick(self) -> None:
        if not self.bidirectional_enabled:
            return
        self._claim_pub.publish(String(data=self.get_name()))

    def _on_bidirectional_claim(self, msg: String) -> None:
        if msg.data == self.get_name():
            return  # our own claim, looped back over the shared topic -- ignore
        self._remote_bidirectional_claims[msg.data] = time.monotonic()

    def _other_active_peer(self) -> Optional[str]:
        """Return a peer node name whose bidirectional-mode claim is still fresh, or
        None. Best-effort only: relies on that peer already having published at least
        one claim (i.e. having been in bidirectional mode for up to
        BIDIRECTIONAL_CLAIM_PERIOD_S already) and on both instances sharing the same
        `bidirectional_claim_topic`. Does NOT protect against two instances enabling
        bidirectional mode within the same short window before either has announced
        itself -- see docs for the operator responsibility this leaves in place.
        """
        now = time.monotonic()
        fresh = [
            name for name, last_seen in self._remote_bidirectional_claims.items()
            if (now - last_seen) <= BIDIRECTIONAL_CLAIM_STALE_S
        ]
        return fresh[0] if fresh else None

    # ------------------------------------------------------------------------------
    # MODE 2: sim -> real (opt-in, safety-gated)
    # ------------------------------------------------------------------------------
    def _on_sim_feedback(self, msg: JointState) -> None:
        # This message doubles as the heartbeat regardless of mode, so the watchdog
        # always has fresh data to evaluate once bidirectional mode is turned on.
        self._last_feedback_monotonic = time.monotonic()
        self._heartbeat_ok = True

        if not self.bidirectional_enabled:
            return  # one-directional mode: never forward to the real arm, ever.

        # --- gate (a): real arm must be enabled -----------------------------------
        if not self._real_arm_enabled:
            self.get_logger().warn(
                "bidirectional: dropping sim feedback, real arm not enabled (enable_flag=False).",
                throttle_duration_sec=2.0,
            )
            return

        # --- gate (b): heartbeat freshness -----------------------------------------
        # Forwarding only ever happens synchronously inside this callback, so arrival
        # of this very message already satisfies "received within heartbeat_timeout_ms".
        # This check remains here defensively in case forwarding logic is ever moved
        # off the message-arrival path (e.g. a future timer-based resend of the last
        # target) -- do not remove it if that happens.
        if self._last_feedback_monotonic is None:
            return

        # --- build the outgoing command, requiring all 6 arm joint names ------------
        real_named_positions: Dict[str, float] = {}
        for sim_name, position in zip(msg.name, msg.position):
            real_name = REVERSE_JOINT_NAME_MAP.get(sim_name, sim_name)
            real_named_positions[real_name] = position

        missing = [n for n in REAL_ARM_JOINT_NAMES if n not in real_named_positions]
        if missing:
            self.get_logger().warn(
                f"bidirectional: dropping sim feedback, missing joint(s) {missing} in "
                f"/sim/piper/joint_state_feedback (names present: {list(msg.name)}). "
                f"Refusing to guess a missing joint as 0.",
                throttle_duration_sec=2.0,
            )
            return

        # --- gate (c): clamp each joint's step against the REAL arm's actual, most
        # recently observed position (ground truth from /joint_states) -- not against
        # the previous *command*. This bounds any single forwarded message to at most
        # max_step_rad away from where the arm truly is right now, regardless of how
        # far the sim pose itself has drifted (e.g. after a heartbeat gap). -----------
        out_names = list(REAL_ARM_JOINT_NAMES)
        out_positions: List[float] = []
        for name in REAL_ARM_JOINT_NAMES:
            target = real_named_positions[name]
            actual = self._latest_real_positions_by_name.get(name)
            if actual is None:
                # We have never seen a /joint_states sample for this joint -- refuse to
                # forward an unclamped, unbounded value. Skip this joint's motion this
                # cycle rather than guess.
                self.get_logger().warn(
                    f"bidirectional: no known actual position for '{name}' yet "
                    f"(no /joint_states sample received) -- skipping this feedback message.",
                    throttle_duration_sec=2.0,
                )
                return
            delta = target - actual
            clamped_delta = max(-self.max_step_rad, min(self.max_step_rad, delta))
            out_positions.append(actual + clamped_delta)

        out = JointState()
        out.header = msg.header
        out.name = out_names
        out.position = out_positions
        # Deliberately empty: piper_single_ctrl_node.joint_callback() treats an empty
        # velocity list as "use default speed 100" via MotionCtrl_2(0x01, 0x01, 100).
        # Forwarding the sim's raw velocity would risk it being misread as a speed
        # percentage (see joint_callback's velocity[6]-as-speed convention) rather than
        # an actual joint velocity -- safer to omit it and rely on the driver's default.
        out.velocity = []

        gripper_real_name = REAL_GRIPPER_JOINT_NAME
        if gripper_real_name in real_named_positions:
            # piper_single_ctrl_node.joint_callback() reads the gripper target from
            # position[6] specifically (index-based, not name-based) and only acts on
            # it when len(position) >= 7, so the gripper entry MUST be the 7th element.
            out.name.append(gripper_real_name)
            out.position.append(real_named_positions[gripper_real_name])
            # No per-step clamp is applied to the gripper (max_step_rad is an arm-joint
            # angular clamp; the gripper's position units are already a small,
            # bounded-range opening value per piper_single_ctrl_node's own /1e6 scaling).

        self.real_ctrl_pub.publish(out)

    # ------------------------------------------------------------------------------
    # Live parameter updates (this is what the web GUI's bidirectional checkbox,
    # calling the standard `set_parameters` service through rosbridge, triggers)
    # ------------------------------------------------------------------------------
    def _on_set_parameters(self, params) -> SetParametersResult:
        for param in params:
            if param.name == 'bidirectional_enabled':
                new_value = bool(param.value)
                if new_value and not self.bidirectional_enabled:
                    peer = self._other_active_peer()
                    if peer is not None:
                        self.get_logger().error(
                            f"REFUSING to enable bidirectional_enabled: peer instance "
                            f"'{peer}' already claims bidirectional mode active (heard "
                            f"within the last {BIDIRECTIONAL_CLAIM_STALE_S:.0f}s on "
                            f"'{self._claim_pub.topic_name}'). Only ONE bridge instance's "
                            f"bidirectional mode may be enabled at a time -- see "
                            f"docs/teleop_bridge.md. Disable it on '{peer}' first."
                        )
                        return SetParametersResult(
                            successful=False,
                            reason=(
                                f"another piper_leader_follower_bridge instance ('{peer}') "
                                f"already has bidirectional_enabled=true"
                            ),
                        )
                if new_value != self.bidirectional_enabled:
                    self.get_logger().warn(
                        f"bidirectional_enabled changed: {self.bidirectional_enabled} -> {new_value}"
                    )
                self.bidirectional_enabled = new_value
            elif param.name == 'heartbeat_timeout_ms':
                self.heartbeat_timeout_ms = int(param.value)
                self.get_logger().info(f"heartbeat_timeout_ms updated to {self.heartbeat_timeout_ms}")
            elif param.name == 'max_step_rad':
                self.max_step_rad = float(param.value)
                self.get_logger().info(f"max_step_rad updated to {self.max_step_rad}")
            elif param.name == 'publish_rate_hz':
                new_hz = float(param.value)
                if new_hz != self.publish_rate_hz:
                    self.publish_rate_hz = new_hz
                    self._downsample_period_s = self._safe_period(self.publish_rate_hz, default_hz=30.0)
                    self._downsample_timer.cancel()
                    self._downsample_timer = self.create_timer(
                        self._downsample_period_s, self._on_downsample_tick
                    )
                    self.get_logger().info(f"publish_rate_hz updated to {self.publish_rate_hz}")
        return SetParametersResult(successful=True)

    @staticmethod
    def _safe_period(rate_hz: float, default_hz: float) -> float:
        if rate_hz is None or rate_hz <= 0.0:
            return 1.0 / default_hz
        return 1.0 / rate_hz


def main(args=None):
    rclpy.init(args=args)
    node = PiperLeaderFollowerBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
