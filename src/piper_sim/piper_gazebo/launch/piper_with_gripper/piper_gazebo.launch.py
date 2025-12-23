import os
from launch import LaunchDescription
from launch.actions import ExecuteProcess, RegisterEventHandler
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

from launch.event_handlers import OnProcessExit

import xacro

import re
def remove_comments(text):
    pattern = r'<!--(.*?)-->'
    return re.sub(pattern, '', text, flags=re.DOTALL)

def generate_launch_description():
    robot_name_in_model = 'piper'
    package_name = 'piper_description'
    urdf_name = "piper_description_gazebo.xacro"

    pkg_share = FindPackageShare(package=package_name).find(package_name) 
    urdf_model_path = os.path.join(pkg_share, f'urdf/{urdf_name}')

    # Ensure GAZEBO_MODEL_PATH includes the install/share directory
    install_dir = os.path.join(os.getcwd(), 'install')
    piper_description_share = os.path.join(install_dir, 'piper_description', 'share')
    
    if 'GAZEBO_MODEL_PATH' in os.environ:
        model_path =  os.environ['GAZEBO_MODEL_PATH'] + ':' + install_dir + '/share' + ':' + piper_description_share
    else:
        model_path =  install_dir + '/share' + ':' + piper_description_share

    # Start Gazebo server
    start_gazebo_cmd =  ExecuteProcess(
        cmd=['gazebo', '--verbose','-s', 'libgazebo_ros_init.so', '-s', 'libgazebo_ros_factory.so'],
        output='screen',
        additional_env={'GAZEBO_MODEL_PATH': model_path,
                        'GAZEBO_MODEL_DATABASE_URI': ''})


    # URDFファイルに $(find ...) のような記述があるため、xacroでコンパイルする必要があります
    # urdfファイルに$(find mybot)があるため、xacroでコンパイルする必要がある
    xacro_file = urdf_model_path
    doc = xacro.parse(open(xacro_file))
    xacro.process_doc(doc)
    params = {'robot_description': remove_comments(doc.toxml())}

    # robot_state_publisherノードは、URDFモデルの内容を 'robot_description' トピックとして配信します。
    # また、'/joint_states' トピックを購読して関節データを取得し、
    # 各リンクの座標変換情報(TF)を 'tf' および 'tf_static' トピックとして配信します。
    node_robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{'use_sim_time': True}, params, {"publish_frequency":15.0}],
        output='screen'
    )

    # 'robot_description' トピックからモデル内容を取得して、Gazebo内にロボットモデルを生成（スポーン）します
    spawn_entity_cmd = Node(
        package='gazebo_ros', 
        executable='spawn_entity.py',
        arguments=['-entity', robot_name_in_model,  '-topic', 'robot_description'], output='screen')

    # 関節状態ブロードキャスター
    # Gazebo内のロボットの関節状態を読み取り、/joint_statesトピックとして配信します。
    load_joint_state_controller = ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active',
             'joint_state_broadcaster'],
        output='screen'
    )

    # 腕の軌道実行コントローラー
    load_joint_trajectory_controller = ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active', 
             'arm_controller'],
        output='screen'
        )

    # グリッパーの軌道実行コントローラー (joint7)
    load_gripper_trajectory_controller = ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active', 
             'gripper_controller'],
        output='screen'
        )
    
    # グリッパーの軌道実行コントローラー (joint8)
    load_gripper8_trajectory_controller = ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active', 
             'gripper8_controller'],
        output='screen'
        )

    # spawn_entity_cmd（ロボットの生成）が完了したら、load_joint_state_controllerを起動します。
    close_evt1 =  RegisterEventHandler( 
            event_handler=OnProcessExit(
                target_action=spawn_entity_cmd,
                on_exit=[load_joint_state_controller],
            )
    )

    # load_joint_state_controllerが完了したら、腕とグリッパーのコントローラーを起動します。
    close_evt2 = RegisterEventHandler(
            event_handler=OnProcessExit(
                target_action=load_joint_state_controller,
                on_exit=[load_joint_trajectory_controller, 
                         load_gripper_trajectory_controller,
                         load_gripper8_trajectory_controller],
            )
    )

    # グリッパーの指(joint8)をもう片方の指(joint7)の動きに追従させるためのノード
    node_gripper_mirror_controller = Node(
        package='piper_gazebo',
        executable='joint8_ctrl.py',
        output='screen'
    )

    ld = LaunchDescription()

    ld.add_action(close_evt1)
    ld.add_action(close_evt2)
    ld.add_action(node_gripper_mirror_controller)
    ld.add_action(start_gazebo_cmd)
    ld.add_action(node_robot_state_publisher)
    ld.add_action(spawn_entity_cmd)

    return ld
