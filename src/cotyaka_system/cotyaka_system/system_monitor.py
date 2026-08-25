import json
import time

import rclpy
from lifecycle_msgs.msg import State
from nav_msgs.msg import Odometry
from rclpy.executors import MultiThreadedExecutor
from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import String


class SystemMonitor(LifecycleNode):
    """Monitor robot-core readiness independently from robot-core processes."""

    def __init__(self):
        super().__init__('system_monitor', namespace='/cotyaka')

        self.declare_parameter('expect_piper', False)
        self.declare_parameter('expect_kobuki', False)
        self.declare_parameter('joint_states_topic', '/joint_states')
        self.declare_parameter('odom_topic', '/odom')
        self.declare_parameter(
            'piper_required_nodes',
            ['/piper_ctrl_single_node', '/move_group', '/piper_moveit_bridge'],
        )
        self.declare_parameter('kobuki_required_nodes', [])
        self.declare_parameter('heartbeat_timeout_sec', 3.0)
        self.declare_parameter('startup_grace_sec', 15.0)

        state_qos = QoSProfile(depth=1)
        state_qos.reliability = ReliabilityPolicy.RELIABLE
        state_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._state_pub = self.create_lifecycle_publisher(String, 'system_state', state_qos)
        self._mp3_pub = self.create_publisher(String, '/cotyaka/audio/play_mp3', 10)
        self._tts_pub = self.create_publisher(String, '/cotyaka/audio/speak', 10)

        self._joint_sub = None
        self._odom_sub = None
        self._timer = None
        self._activated_at = None
        self._last_joint = None
        self._last_odom = None
        self._last_state = None
        self._announcement_sent = False

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        joint_topic = self.get_parameter('joint_states_topic').value
        odom_topic = self.get_parameter('odom_topic').value
        self._joint_sub = self.create_subscription(
            JointState, joint_topic, self._on_joint_state, 10)
        self._odom_sub = self.create_subscription(
            Odometry, odom_topic, self._on_odom, 10)
        self.get_logger().info(
            'Configured monitor: expect_piper=%s expect_kobuki=%s'
            % (self._expect_piper(), self._expect_kobuki())
        )
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        super().on_activate(state)
        self._activated_at = time.monotonic()
        self._timer = self.create_timer(0.5, self._evaluate)
        self._publish_state('STARTING', [], self._expected_components())
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        if self._timer is not None:
            self.destroy_timer(self._timer)
            self._timer = None
        super().on_deactivate(state)
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        if self._joint_sub is not None:
            self.destroy_subscription(self._joint_sub)
            self._joint_sub = None
        if self._odom_sub is not None:
            self.destroy_subscription(self._odom_sub)
            self._odom_sub = None
        self._last_joint = None
        self._last_odom = None
        self._announcement_sent = False
        return TransitionCallbackReturn.SUCCESS

    def _expect_piper(self) -> bool:
        return bool(self.get_parameter('expect_piper').value)

    def _expect_kobuki(self) -> bool:
        return bool(self.get_parameter('expect_kobuki').value)

    def _expected_components(self):
        result = []
        if self._expect_piper():
            result.append('piper')
        if self._expect_kobuki():
            result.append('kobuki')
        return result

    def _on_joint_state(self, _msg: JointState) -> None:
        self._last_joint = time.monotonic()

    def _on_odom(self, _msg: Odometry) -> None:
        self._last_odom = time.monotonic()

    def _graph_nodes(self):
        return {
            f'{ns.rstrip("/")}/{name}' if ns != '/' else f'/{name}'
            for name, ns in self.get_node_names_and_namespaces()
        }

    def _evaluate(self) -> None:
        now = time.monotonic()
        timeout = float(self.get_parameter('heartbeat_timeout_sec').value)
        grace = float(self.get_parameter('startup_grace_sec').value)
        graph_nodes = self._graph_nodes()

        ready = []
        missing = []

        if self._expect_piper():
            required = set(self.get_parameter('piper_required_nodes').value)
            joint_ok = self._last_joint is not None and now - self._last_joint <= timeout
            nodes_ok = required.issubset(graph_nodes)
            if joint_ok and nodes_ok:
                ready.append('piper')
            else:
                missing.append('piper')

        if self._expect_kobuki():
            required = set(self.get_parameter('kobuki_required_nodes').value)
            odom_ok = self._last_odom is not None and now - self._last_odom <= timeout
            nodes_ok = required.issubset(graph_nodes)
            if odom_ok and nodes_ok:
                ready.append('kobuki')
            else:
                missing.append('kobuki')

        expected = self._expected_components()
        elapsed = now - self._activated_at if self._activated_at is not None else 0.0

        if not expected:
            state = 'NO_ROBOT'
        elif not missing:
            if expected == ['piper']:
                state = 'READY_PIPER_ONLY'
            elif expected == ['kobuki']:
                state = 'READY_KOBUKI_ONLY'
            else:
                state = 'READY_FULL'
        elif elapsed <= grace:
            state = 'STARTING'
        else:
            state = 'DEGRADED'

        self._publish_state(state, ready, missing)
        self._announce_once(state)

    def _publish_state(self, state: str, ready, missing) -> None:
        payload = {
            'state': state,
            'expected_components': self._expected_components(),
            'ready_components': ready,
            'missing_components': missing,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if encoded == self._last_state:
            return
        msg = String()
        msg.data = encoded
        self._state_pub.publish(msg)
        self.get_logger().info(f'System state -> {encoded}')
        self._last_state = encoded

    def _announce_once(self, state: str) -> None:
        if self._announcement_sent:
            return

        key = None
        fallback = None
        if state == 'READY_FULL':
            key = 'startup_full'
            fallback = 'PiperとKobukiの接続を確認しました。すべてのロボットコアを起動しました。'
        elif state == 'READY_PIPER_ONLY':
            key = 'startup_piper_only'
            fallback = 'Kobukiの接続を確認できませんでした。Piperのみで起動しています。'
        elif state == 'READY_KOBUKI_ONLY':
            key = 'startup_kobuki_only'
            fallback = 'Piperの接続を確認できませんでした。Kobukiのみで起動しています。'
        elif state == 'NO_ROBOT':
            key = 'startup_no_robot'
            fallback = 'PiperとKobukiの接続を確認できませんでした。監視機能のみ起動しています。'

        if key is None:
            return

        # Compose starts Monitor and Audio concurrently. Do not consume the
        # one-shot startup announcement until DDS has discovered AudioNode.
        if self._mp3_pub.get_subscription_count() == 0:
            return

        msg = String()
        msg.data = f'{key}|{fallback}'
        self._mp3_pub.publish(msg)
        self._announcement_sent = True


def main(args=None):
    rclpy.init(args=args)
    node = SystemMonitor()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
