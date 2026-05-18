
### moveitのmarkerを操作するとrvizが落ちるときの逃げ方
'''
ros2 launch piper_with_gripper_moveit demo.launch.py rviz:=false
'''

### enterキーを押してstr型のトピック'/record_joint_commandを出す
'''
ros2 run piper wait_enter_and_pub_msg
'''