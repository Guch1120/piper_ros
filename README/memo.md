
### moveitのmarkerを操作するとrvizが落ちるときの逃げ方
'''
ros2 launch piper_with_gripper_moveit demo.launch.py rviz:=false
'''

### enterキーを押してstr型のトピック'/record_joint_commandを出す
'''
ros2 run piper wait_enter_and_pub_msg
'''

<!-- マークダウン形式のトグル展開コピペ用 -->
 <!-- <details> <summarry>


 input key
 -<br>

 output key
 -<br>

 outcome
 -
 </summarry></details> -->

### flexbeステート
increment index

 <details><summarry>

 インデックスを管理するステート<br>
 input key 
 - index
 インデックス番号(int型)
 - target_list 
 対象とするリスト(list型)<br>
 
 output key
 - index(int型)<br>
 
 outcome
 - done
 インクリメントを行う
 - complete
 リスト全てインクリメントし終えた
 </summarry></details>


```python
 ros2 run your_package_name rpy_calibration_node \
  --ros-args \
  -p image_topic:=/camera/camera/color/image_raw \
  -p camera_info_topic:=/camera/camera/color/camera_info \
  -p base_frame:=base_link \
  -p parent_frame:=gripper_base \
  -p camera_link_frame:=camera_link \
  -p optical_frame:=camera_color_optical_frame \
  -p marker_id:=0 \
  -p marker_length:=0.17 \
  -p calibration_mode:=normal_only \
  -p samples:=50 \
  -p min_samples_to_print:=20 \
  -p print_every_n_frames:=10
```