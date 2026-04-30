#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyActionClient, ProxyPublisher
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint

class PiperMoveItGripperBaseState(EventState):
    '''
    MoveIt経由でPiperのグリッパ(joint7)を制御する基底ステート。
    直接は使用せず、Open/Closeステートで使用します。

    -- group_name    string  MoveItのグループ名 (default: 'gripper')
    -- joint_name    string  グリッパのジョイント名 (default: 'joint7')
    -- tolerance     float   許容誤差 (rad/m) (default: 0.01)
    -- action_topic  string  MoveGroupのアクション名 (default: 'move_action')

    <= reached       目標に到達した
    <= failed        移動失敗
    '''

    def __init__(self, target_position, group_name='gripper', joint_name='joint7', tolerance=0.01, action_topic='move_action'):
        super().__init__(outcomes=['reached', 'failed'])
        self._group_name = group_name
        self._joint_name = joint_name
        self._target_position = target_position
        self._tolerance = tolerance
        self._topic = action_topic
        
        # ProxyActionClientのノード設定（FlexBEの仕様対策）
        if ProxyActionClient._node is None:
            if ProxyPublisher._node is not None:
                ProxyActionClient._node = ProxyPublisher._node
            else:
                Logger.logerr('ProxyActionClient: No node available!')

        self._client = ProxyActionClient({self._topic: MoveGroup})
        self._error = False

    def on_enter(self, userdata):
        self._error = False
        
        # Action Serverの確認
        if not self._client.is_available(self._topic):
            Logger.logerr(f'Action Server {self._topic} not available. Check move_group node.')
            self._error = True
            return

        # ゴール作成
        goal = MoveGroup.Goal()
        goal.request.group_name = self._group_name
        goal.request.allowed_planning_time = 2.0 # グリッパなので短めでOK
        goal.request.max_velocity_scaling_factor = 1.0
        goal.request.max_acceleration_scaling_factor = 1.0
        
        # ジョイント制約の作成 (joint7を動かす)
        constraints = Constraints()
        jc = JointConstraint()
        jc.joint_name = self._joint_name
        jc.position = float(self._target_position)
        jc.tolerance_above = self._tolerance
        jc.tolerance_below = self._tolerance
        jc.weight = 1.0
        constraints.joint_constraints.append(jc)
            
        goal.request.goal_constraints.append(constraints)

        # 送信
        try:
            self._client.send_goal(self._topic, goal)
            Logger.loginfo(f'MoveIt: Moving {self._joint_name} to {self._target_position}...')
        except Exception as e:
            Logger.logerr(f'Failed to send MoveIt goal: {e}')
            self._error = True

    def execute(self, userdata):
        if self._error:
            return 'failed'

        if self._client.has_result(self._topic):
            result = self._client.get_result(self._topic)
            if result.error_code.val == 1: # SUCCESS
                Logger.loginfo('MoveIt: Gripper goal reached.')
                return 'reached'
            else:
                Logger.logwarn(f'MoveIt failed with error code: {result.error_code.val}')
                return 'failed'


class PiperMoveItOpenState(PiperMoveItGripperBaseState):
    '''
    MoveItを使用してPiperのグリッパを「開く」ステート。
    デフォルト値は piper_macro.xacro の limit (upper) を参考に設定してください。

    -- group_name    string  MoveItのグループ名 (default: 'gripper')
    -- open_value    float   開いた状態の値 [m] (default: 0.07) ※モデルに合わせて調整
    -- joint_name    string  グリッパのジョイント名 (default: 'joint7')

    <= reached       目標に到達した
    <= failed        移動失敗
    '''
    def __init__(self, group_name='gripper', open_value=0.07, joint_name='joint7'):
        # 親クラスの初期化
        super().__init__(target_position=open_value, group_name=group_name, joint_name=joint_name)


class PiperMoveItCloseState(PiperMoveItGripperBaseState):
    '''
    MoveItを使用してPiperのグリッパを「閉じる」ステート。

    -- group_name    string  MoveItのグループ名 (default: 'gripper')
    -- close_value   float   閉じた状態の値 [m] (default: 0.0)
    -- joint_name    string  グリッパのジョイント名 (default: 'joint7')

    <= reached       目標に到達した
    <= failed        移動失敗
    '''
    def __init__(self, group_name='gripper', close_value=0.0, joint_name='joint7'):
        # 親クラスの初期化
        super().__init__(target_position=close_value, group_name=group_name, joint_name=joint_name)