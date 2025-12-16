#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyActionClient, ProxyPublisher
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint

class PiperMoveItCloseState(EventState):
    '''
    MoveItを使用してPiperのグリッパを指定した幅まで閉じるステート。

    -- target_value  float   閉じる幅 [m] (default: 0.0)
                             ※完全に閉じる場合は0.0、物体を掴む場合はその幅を指定
    -- joint_name    string  グリッパのジョイント名 (default: 'joint7')
    -- group_name    string  MoveItのグループ名 (default: 'gripper')
    -- tolerance     float   許容誤差 (default: 0.01)
    -- action_topic  string  MoveGroupのアクション名 (default: 'move_action')

    <= reached       目標に到達した
    <= failed        移動失敗
    '''

    def __init__(self, target_value=0.0, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'):
        # FlexBEのエディタで設定可能なパラメータを定義
        super(PiperMoveItCloseState, self).__init__(outcomes=['reached', 'failed'])
        
        self._target_value = target_value
        self._joint_name = joint_name
        self._group_name = group_name
        self._tolerance = tolerance
        self._topic = action_topic
        
        # ProxyActionClientのノード設定（FlexBEの仕様対策）
        if ProxyActionClient._node is None:
            if ProxyPublisher._node is not None:
                ProxyActionClient._node = ProxyPublisher._node
            else:
                Logger.logwarn('ProxyActionClient: Node not ready yet. Will retry later.')

        # Action Clientの作成
        self._client = ProxyActionClient({self._topic: MoveGroup})
        self._error = False

    def on_enter(self, userdata):
        self._error = False
        
        # Action Serverの接続確認
        if not self._client.is_available(self._topic):
            Logger.logerr(f'Action Server {self._topic} not available. Check move_group node.')
            self._error = True
            return

        # ゴールメッセージの作成
        goal = MoveGroup.Goal()
        goal.request.group_name = self._group_name
        goal.request.allowed_planning_time = 2.0
        goal.request.max_velocity_scaling_factor = 1.0
        goal.request.max_acceleration_scaling_factor = 1.0
        
        # ジョイント制約の作成 (グリッパーを閉じる)
        constraints = Constraints()
        jc = JointConstraint()
        jc.joint_name = self._joint_name
        jc.position = float(self._target_value)  # パラメータで指定された値を使用
        jc.tolerance_above = self._tolerance
        jc.tolerance_below = self._tolerance
        jc.weight = 1.0
        constraints.joint_constraints.append(jc)
            
        goal.request.goal_constraints.append(constraints)

        # ゴールの送信
        try:
            self._client.send_goal(self._topic, goal)
            Logger.loginfo(f'MoveIt: Closing gripper ({self._joint_name}) to {self._target_value}...')
        except Exception as e:
            Logger.logerr(f'Failed to send MoveIt goal: {e}')
            self._error = True

    def execute(self, userdata):
        # 送信時にエラーがあった場合
        if self._error:
            return 'failed'

        # 結果の確認
        if self._client.has_result(self._topic):
            result = self._client.get_result(self._topic)
            
            # MoveItのエラーコード1はSUCCESS
            if result.error_code.val == 1:
                Logger.loginfo('Gripper CLOSED successfully!')
                return 'reached'
            else:
                Logger.logwarn(f'MoveIt failed with error code: {result.error_code.val}')
                return 'failed'
        
        # まだ結果が出ていない場合は待機継続
        return None

    def on_exit(self, userdata):
        # ステートを抜ける際（Preempt時など）に実行中のゴールをキャンセル
        if self._client.is_active(self._topic) and not self._client.has_result(self._topic):
            try:
                self._client.cancel(self._topic)
                Logger.loginfo('MoveIt goal cancelled due to state exit.')
            except Exception as e:
                Logger.logwarn(f'Failed to cancel MoveIt goal: {e}')