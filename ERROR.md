実行コマンド
```
ros2 launch piper start_single_piper.launch.py
```
エラー
```
root@robo25-Alienware-m15-R3:/workspace/ros2_ws# ros2 launch piper start_single_piper.launch.py
[INFO] [launch]: All log files can be found below /root/.ros/log/2025-11-07-21-42-33-424098-robo25-Alienware-m15-R3-94
[INFO] [launch]: Default logging verbosity is set to INFO
[INFO] [piper_single_ctrl-1]: process started with pid [95]
[piper_single_ctrl-1] [INFO] [1762519353.698281132] [piper_ctrl_single_node]: can_port is can0
[piper_single_ctrl-1] [INFO] [1762519353.698646117] [piper_ctrl_single_node]: auto_enable is True
[piper_single_ctrl-1] [INFO] [1762519353.699120544] [piper_ctrl_single_node]: gripper_exist is True
[piper_single_ctrl-1] [INFO] [1762519353.699478228] [piper_ctrl_single_node]: gripper_val_mutiple is 1
[piper_single_ctrl-1] [INFO] [1762519353.713801301] [piper_ctrl_single_node]: --------------------
[piper_single_ctrl-1] [INFO] [1762519353.715043997] [piper_ctrl_single_node]: Enable status:False
[piper_single_ctrl-1] [INFO] [1762519353.715825661] [piper_ctrl_single_node]: --------------------
[piper_single_ctrl-1] [INFO] [1762519354.717496902] [piper_ctrl_single_node]: --------------------
[piper_single_ctrl-1] [INFO] [1762519354.717920250] [piper_ctrl_single_node]: Enable status:True
[piper_single_ctrl-1] [INFO] [1762519354.718489894] [piper_ctrl_single_node]: --------------------
[piper_single_ctrl-1] [INFO] [1762520044.000938158] [piper_ctrl_single_node]: Received enable flag:
[piper_single_ctrl-1] [INFO] [1762520044.001268966] [piper_ctrl_single_node]: enable_flag: False
[piper_single_ctrl-1] [INFO] [1762520062.390508145] [piper_ctrl_single_node]: Received enable flag:
[piper_single_ctrl-1] [INFO] [1762520062.391034929] [piper_ctrl_single_node]: enable_flag: True
[piper_single_ctrl-1] [INFO] [1762520073.624658958] [piper_ctrl_single_node]: Received enable flag:
[piper_single_ctrl-1] [INFO] [1762520073.625101347] [piper_ctrl_single_node]: enable_flag: False

```
状況 ```ros2 topic echo /arm_status```によると
```
---
ctrl_mode: 0
arm_status: 0
mode_feedback: 0
teach_status: 0
motion_status: 0
trajectory_num: 0
err_code: 0
joint_1_angle_limit: false
joint_2_angle_limit: false
joint_3_angle_limit: false
joint_4_angle_limit: false
joint_5_angle_limit: false
joint_6_angle_limit: false
communication_status_joint_1: false
communication_status_joint_2: false
communication_status_joint_3: false
communication_status_joint_4: false
communication_status_joint_5: false
communication_status_joint_6: false
---

```
これはスタンバイモードであってコントロールモードではない，