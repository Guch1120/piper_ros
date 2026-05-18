#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyActionClient, ProxyPublisher

from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint


class MoveJointListInputKey(EventState):
    """
    userdata から取得した目標関節角度を用いて、MoveIt により関節を動かす

    -- group_name             string    MoveIt のプランニンググループ名
    -- joint_names            list      対象とする関節名のリスト
    -- tolerance              float     関節ゴール許容誤差
    -- action_topic           string    MoveGroup アクショントピック名
    -- allowed_planning_time  float     計画に許可する時間

    ># joint_values           list      userdata から取得する目標関節角度のリスト

    <= done                             MoveIt ゴールの送信／実行完了。
    """

    def __init__(self,group_name='arm',joint_names=None,tolerance=0.01,action_topic='move_action',allowed_planning_time=5.0):

        super().__init__(outcomes=['done'],input_keys=['joint_values'])
        self._group_name = group_name
        if joint_names is None:
            self._joint_names = ['joint1','joint2','joint3','joint4','joint5','joint6']
        else:
            self._joint_names = joint_names

        self._tolerance = tolerance
        self._topic = action_topic
        self._allowed_planning_time = allowed_planning_time

        # ProxyActionClient の node が None になる対策
        if ProxyActionClient._node is None:
            if ProxyPublisher._node is not None:
                ProxyActionClient._node = ProxyPublisher._node
                Logger.loginfo(
                    'ProxyActionClient._node was None. Fixed using ProxyPublisher._node.'
                )
            else:
                Logger.logwarn(
                    'Both ProxyActionClient and ProxyPublisher have no node yet.'
                )

        self._client = ProxyActionClient({
            self._topic: MoveGroup
        })

        self._target_joints = []
        self._done = False
        self._sent_goal = False

    def on_enter(self, userdata):
        self._done = False
        self._sent_goal = False
        self._target_joints = []

        # userdata の joint_values を直接読む
        try:
            self._target_joints = list(userdata.joint_values)
        except Exception as e:
            Logger.logerr(
                'MoveJointListInputKey: failed to read userdata.joint_values: {}'.format(e)
            )
            self._done = True
            return

        if self._target_joints is None:
            Logger.logerr(
                'MoveJointListInputKey: userdata.joint_values is None.'
            )
            self._done = True
            return

        # Action Server確認
        if not self._client.is_available(self._topic):
            Logger.logerr(
                'MoveJointListInputKey: Action Server "{}" is not available.'.format(
                    self._topic
                )
            )
            self._done = True
            return

        # パラメータチェック
        if len(self._target_joints) != len(self._joint_names):
            Logger.logerr(
                'MoveJointListInputKey: length mismatch: joint_values({}) vs joint_names({})'.format(
                    len(self._target_joints),
                    len(self._joint_names)
                )
            )
            Logger.logerr(
                'joint_values = {}'.format(self._target_joints)
            )
            Logger.logerr(
                'joint_names = {}'.format(self._joint_names)
            )
            self._done = True
            return

        goal = MoveGroup.Goal()
        goal.request.group_name = self._group_name
        goal.request.allowed_planning_time = float(self._allowed_planning_time)

        constraints = Constraints()

        for i, name in enumerate(self._joint_names):
            jc = JointConstraint()
            jc.joint_name = name
            jc.position = float(self._target_joints[i])
            jc.tolerance_above = float(self._tolerance)
            jc.tolerance_below = float(self._tolerance)
            jc.weight = 1.0
            constraints.joint_constraints.append(jc)

        goal.request.goal_constraints.append(constraints)

        try:
            self._client.send_goal(self._topic, goal)
            self._sent_goal = True

            Logger.loginfo(
                'MoveJointListInputKey: sent MoveGroup goal from userdata.joint_values: {}'.format(
                    self._target_joints
                )
            )

        except Exception as e:
            Logger.logerr(
                'MoveJointListInputKey: failed to send goal: {}'.format(e)
            )
            self._done = True

    def execute(self, userdata):
        if self._done:
            return 'done'

        if not self._sent_goal:
            return 'done'

        if self._client.has_result(self._topic):
            result = self._client.get_result(self._topic)

            if result.error_code.val == 1:
                Logger.loginfo(
                    'MoveJointListInputKey: MoveIt SUCCESS.'
                )
            else:
                Logger.logwarn(
                    'MoveJointListInputKey: MoveIt failed with error code: {}'.format(
                        result.error_code.val
                    )
                )

            return 'done'

        return None