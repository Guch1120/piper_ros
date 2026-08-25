from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.event_handlers import OnProcessStart
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from launch_ros.parameter_descriptions import ParameterValue
from lifecycle_msgs.msg import Transition


def generate_launch_description():
    expect_piper_arg = DeclareLaunchArgument('expect_piper', default_value='false')
    expect_kobuki_arg = DeclareLaunchArgument('expect_kobuki', default_value='false')

    monitor = LifecycleNode(
        package='cotyaka_system',
        executable='system_monitor',
        name='system_monitor',
        namespace='/cotyaka',
        output='screen',
        parameters=[{
            'expect_piper': ParameterValue(
                LaunchConfiguration('expect_piper'), value_type=bool),
            'expect_kobuki': ParameterValue(
                LaunchConfiguration('expect_kobuki'), value_type=bool),
        }],
    )

    configure = RegisterEventHandler(
        OnProcessStart(
            target_action=monitor,
            on_start=[EmitEvent(event=ChangeState(
                lifecycle_node_matcher=lambda action: action == monitor,
                transition_id=Transition.TRANSITION_CONFIGURE,
            ))],
        )
    )

    activate = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=monitor,
            goal_state='inactive',
            entities=[EmitEvent(event=ChangeState(
                lifecycle_node_matcher=lambda action: action == monitor,
                transition_id=Transition.TRANSITION_ACTIVATE,
            ))],
        )
    )

    return LaunchDescription([
        expect_piper_arg,
        expect_kobuki_arg,
        monitor,
        configure,
        activate,
    ])
