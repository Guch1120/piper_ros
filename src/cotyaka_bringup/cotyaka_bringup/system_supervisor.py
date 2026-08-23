import time

import rclpy
from lifecycle_msgs.msg import State
from nav_msgs.msg import Odometry
from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import String


class SystemSupervisor(LifecycleNode):
    """Lifecycle-managed readiness gate for the Cotyaka robot core."""

    def __init__(self):
        super().__init__('system_supervisor', namespace='/cotyaka')

        self.declare_parameter('joint_states_topic', '/joint_states')
        self.declare_parameter('odom_topic', '/odom')
        self.declare_parameter(
            'required_nodes',
            ['/piper_ctrl_single_node', '/move_group', '/piper_moveit_bridge'],
        )
        self.declare_parameter('heartbeat_timeout_sec', 3.0)
        self.declare_parameter('startup_grace_sec', 10.0)

        qos = QoSProfile(depth=1)
        qos.reliability = ReliabilityPolicy.RELIABLE
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._state_pub = self.create_lifecycle_publisher(String, 'system_state', qos)

        self._joint_sub = None
        self._odom_sub = None
        self._timer = None
        self._last_joint = None
        self._last_odom = None
        self._activated_at = None
        self._last_state = None
        self._last_missing_nodes = None

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        joint_topic = self.get_parameter('joint_states_topic').value
        odom_topic = self.get_parameter('odom_topic').value

        self._joint_sub = self.create_subscription(
            JointState, joint_topic, self._on_joint_state, 10)
        self._odom_sub = self.create_subscription(
            Odometry, odom_topic, self._on_odom, 10)

        self.get_logger().info(
            f'Configured. Waiting for joint_states={joint_topic}, odom={odom_topic}')
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        result = super().on_activate(state)
        self._activated_at = time.monotonic()
        self._timer = self.create_timer(0.5, self._evaluate)
        self._publish_state('BOOTING')
        self.get_logger().info('Supervisor activated')
        return result

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self._publish_state('INACTIVE')
        if self._timer is not None:
            self.destroy_timer(self._timer)
            self._timer = None
        return super().on_deactivate(state)

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        if self._joint_sub is not None:
            self.destroy_subscription(self._joint_sub)
            self._joint_sub = None
        if self._odom_sub is not None:
            self.destroy_subscription(self._odom_sub)
            self._odom_sub = None
        self._last_joint = None
        self._last_odom = None
        self._last_missing_nodes = None
        return TransitionCallbackReturn.SUCCESS

    def _on_joint_state(self, _msg: JointState) -> None:
        self._last_joint = time.monotonic()

    def _on_odom(self, _msg: Odometry) -> None:
        self._last_odom = time.monotonic()

    def _evaluate(self) -> None:
        now = time.monotonic()
        timeout = float(self.get_parameter('heartbeat_timeout_sec').value)
        grace = float(self.get_parameter('startup_grace_sec').value)
        required_nodes = set(self.get_parameter('required_nodes').value)

        graph_nodes = {
            f'{ns.rstrip("/")}/{name}' if ns != '/' else f'/{name}'
            for name, ns in self.get_node_names_and_namespaces()
        }
        missing_nodes = tuple(sorted(required_nodes - graph_nodes))

        if missing_nodes != self._last_missing_nodes:
            if missing_nodes:
                self.get_logger().warn(f'Missing required nodes: {list(missing_nodes)}')
            self._last_missing_nodes = missing_nodes

        joint_ok = self._last_joint is not None and now - self._last_joint <= timeout
        odom_ok = self._last_odom is not None and now - self._last_odom <= timeout

        if not joint_ok:
            system_state = 'WAITING_PIPER'
        elif not odom_ok:
            system_state = 'WAITING_KOBUKI'
        elif missing_nodes:
            system_state = 'WAITING_ROS_GRAPH'
        else:
            system_state = 'READY'

        if (
            self._activated_at is not None
            and now - self._activated_at > grace
            and system_state != 'READY'
        ):
            system_state = 'DEGRADED:' + system_state

        self._publish_state(system_state)

    def _publish_state(self, value: str) -> None:
        if value == self._last_state:
            return
        msg = String()
        msg.data = value
        self._state_pub.publish(msg)
        self.get_logger().info(f'System state -> {value}')
        self._last_state = value


def main(args=None):
    rclpy.init(args=args)
    node = SystemSupervisor()
    executor = rclpy.executors.MultiThreadedExecutor()
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
