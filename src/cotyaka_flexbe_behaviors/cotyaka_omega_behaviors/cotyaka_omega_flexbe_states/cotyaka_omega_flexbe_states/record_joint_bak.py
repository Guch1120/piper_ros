#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxySubscriberCached

from sensor_msgs.msg import JointState


class RecordJointBak(EventState):
    """
    JointState から現在の関節角度を記録し、ファイルへ保存する。

    -- joint_state_topic       string    JointState トピック名
    -- joint_names             list      対象とする関節名のリスト
    -- save_file_path          string    教示姿勢を保存するファイルパス

    ># index                   int       記録番号
                                         0 の場合、新規教示開始として
                                         保存ファイルと内部リストを初期化する

    #> joint_list              list      記録した関節角度のリスト

    <= done                              関節角度の記録完了
    """

    def __init__(self,
                 joint_state_topic='/joint_states',
                 joint_names=['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6'],
                 save_file_path='/ros2_ws/src/cotyaka_flexbe_behaviors/cotyaka_omega_behaviors/cotyaka_omega_flexbe_states/cotyaka_omega_flexbe_states/direct_teaching_list.txt'):

        super().__init__(
            outcomes=['done'],
            input_keys=['index'],
            output_keys=['joint_list']
        )

        self._joint_state_topic = joint_state_topic
        self._save_file_path = os.path.abspath(os.path.expanduser(save_file_path))
        self._sub = ProxySubscriberCached({self._joint_state_topic: JointState})
        self._recorded_joint_list = []
        self._joint_names = joint_names

    def on_enter(self, userdata):
        """
        ステート進入時に現在の関節角度を1回記録する。
        """

        index = userdata.index
        if index == 0: # index == 0 の場合は、新規動作教示の開始として初期化する
            self._recorded_joint_list = []
            if not self._initialize_save_file():
                userdata.joint_list = self._recorded_joint_list
                return

        joint_values = self._get_current_joint_values()

        if joint_values is None:
            Logger.logwarn('RecordJointBak: JointState has not been received yet, ''or required joints are missing.')
            userdata.joint_list = self._recorded_joint_list
            return

        self._recorded_joint_list.append(joint_values)
        userdata.joint_list = self._recorded_joint_list

        if not self._append_joint_values_to_file(joint_values):
            Logger.logwarn('RecordJointBak: Joint values were added to userdata, ''but could not be saved to file.')
        Logger.loginfo('RecordJointBak: Recorded index {}: {}'.format(index, joint_values))

    def execute(self, userdata):
        """
        on_enter() で記録済みなので、即座に done を返す。
        """
        userdata.joint_list = self._recorded_joint_list
        userdata.index = index + 1
        return 'done'

    def _get_current_joint_values(self):
        """
        最新の JointState から、指定した関節名の位置情報のみを取得する。

        Returns:
            list: 関節角度のリスト
            None: JointState 未受信、または必要な関節名が存在しない場合
        """

        if not self._sub.has_msg(self._joint_state_topic):
            return None

        msg = self._sub.get_last_msg(self._joint_state_topic)
        name_to_position = dict(zip(msg.name, msg.position))

        joint_values = []

        for joint_name in self._joint_names:
            if joint_name not in name_to_position:
                Logger.logwarn(
                    'RecordJointBak: Required joint "{}" is not in JointState.'
                    .format(joint_name)
                )
                return None

            joint_values.append(name_to_position[joint_name])

        return joint_values

    def _initialize_save_file(self):
        """
        保存ファイルの中身を空にする。
        index == 0、すなわち新規動作教示開始時に呼び出す。

        Returns:
            bool: 初期化に成功した場合 True
        """

        try:
            save_directory = os.path.dirname(self._save_file_path)

            if save_directory:
                os.makedirs(save_directory, exist_ok=True)
            with open(self._save_file_path, 'w') as file:
                file.write('')
            Logger.loginfo('RecordJointBak: Initialized save file: {}'.format(self._save_file_path))
            return True

        except OSError as error:
            Logger.logerr('RecordJointBak: Failed to initialize save file "{}": {}'.format(self._save_file_path, error))
            return False

    def _append_joint_values_to_file(self, joint_values):
        """
        記録した関節角度を保存ファイルへ1行追記する。

        保存形式:
            joint1,joint2,joint3,joint4,joint5,joint6
        Returns:
            bool: 保存に成功した場合 True
        """

        try:
            save_directory = os.path.dirname(self._save_file_path)

            if save_directory:
                os.makedirs(save_directory, exist_ok=True)

            line = ','.join(
                '{:.10f}'.format(value) for value in joint_values
            )

            with open(self._save_file_path, 'a') as file:
                file.write(line + '\n')

            Logger.loginfo('RecordJoint: Saved joint values to file: {}'.format(self._save_file_path))
            return True

        except OSError as error:
            Logger.logerr('RecordJoint: Failed to append joint values to file "{}": {}'.format(self._save_file_path, error))
            return False