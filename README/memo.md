
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