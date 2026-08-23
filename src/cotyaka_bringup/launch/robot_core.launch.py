from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import EmitEvent, IncludeLaunchDescription, RegisterEventHandler
from launch.event_handlers import OnProcessStart
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import LifecycleNode, Node
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description():
    piper_share = get_package_share_directory('piper')
    moveit_share = get_package_share_directory('piper_with_gripper_moveit')
    bringup_share = get_package_share_directory('cotyaka_bringup')

    piper_driver = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            [piper_share, '/launch/start_single_moveit_piper.launch.py']
        ),
        launch_arguments={
            'can_port': 'can0',
            'auto_enable': 'true',
            'gripper_exist': 'true',
        }.items(),
    )

    moveit_rsp = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([moveit_share, '/launch/rsp.launch.py'])
    )

    move_group = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([moveit_share, '/launch/move_group.launch.py'])
    )

    moveit_bridge = Node(
        package='piper',
        executable='piper_moveit_bridge',
        name='piper_moveit_bridge',
        output='screen',
    )

    supervisor = LifecycleNode(
        package='cotyaka_bringup',
        executable='system_supervisor',
        name='system_supervisor',
        namespace='/cotyaka',
        output='screen',
        parameters=[bringup_share + '/config/supervisor.yaml'],
    )

    configure_supervisor = RegisterEventHandler(
        OnProcessStart(
            target_action=supervisor,
            on_start=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=lambda action: action == supervisor,
                        transition_id=Transition.TRANSITION_CONFIGURE,
                    )
                )
            ],
        )
    )

    activate_supervisor = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=supervisor,
            goal_state='inactive',
            entities=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=lambda action: action == supervisor,
                        transition_id=Transition.TRANSITION_ACTIVATE,
                    )
                )
            ],
        )
    )

    return LaunchDescription([
        piper_driver,
        moveit_rsp,
        move_group,
        moveit_bridge,
        supervisor,
        configure_supervisor,
        activate_supervisor,
    ])
