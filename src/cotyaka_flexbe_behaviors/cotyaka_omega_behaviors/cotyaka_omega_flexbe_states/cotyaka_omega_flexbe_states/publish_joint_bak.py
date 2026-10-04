#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from flexbe_core import EventState, Logger


class PublishJointListFromFile(EventState):
    """
    ファイルに保存された教示関節角度リストを読み込み、joint_list として出力する。

    -- load_file_path          string    教示姿勢を読み込むファイルパス
    -- expected_joint_count    int       1行あたりの関節数

    #> joint_list              list      読み込んだ関節角度リスト

    <= done                              読み込み成功
    <= failed                            読み込み失敗
    """

    def __init__(self,load_file_path='/ros2_ws/src/cotyaka_flexbe_behaviors/cotyaka_omega_behaviors/cotyaka_omega_flexbe_states/cotyaka_omega_flexbe_states/direct_teaching_list.txt',expected_joint_count=6):
        super().__init__(outcomes=['done', 'failed'],output_keys=['joint_list'])
        self._load_file_path = os.path.abspath(os.path.expanduser(load_file_path))
        self._expected_joint_count = expected_joint_count
        self._joint_list = []

    def on_enter(self, userdata):
        """
        ステート進入時にファイルを読み込む。
        """

        self._joint_list = []
        if not os.path.isfile(self._load_file_path):
            Logger.logerr('PublishJointListFromFile: File does not exist: {}'.format(self._load_file_path))
            userdata.joint_list = []
            return

        try:
            with open(self._load_file_path, 'r') as file:
                lines = file.readlines()

            for line_number, line in enumerate(lines, start=1):
                line = line.strip()

                # 空行は無視
                if not line:
                    continue

                # コメント行を使いたくなった場合のため
                if line.startswith('#'):
                    continue

                values_text = line.split(',')

                if len(values_text) != self._expected_joint_count:
                    Logger.logerr('PublishJointListFromFile: Invalid joint count at line {}. ''Expected {}, but got {}: {}'.format(line_number,self._expected_joint_count,len(values_text),line))
                    userdata.joint_list = []
                    return

                try:
                    joint_values = [float(value) for value in values_text]
                except ValueError:
                    Logger.logerr('PublishJointListFromFile: Failed to parse float at line {}: {}'.format(line_number,line))
                    userdata.joint_list = []
                    return

                self._joint_list.append(joint_values)

            if len(self._joint_list) == 0:
                Logger.logerr('PublishJointListFromFile: No valid joint values were loaded from file: {}'.format(self._load_file_path))
                userdata.joint_list = []
                return

            userdata.joint_list = self._joint_list
            Logger.loginfo('PublishJointListFromFile: Loaded {} joint poses from {}'.format(len(self._joint_list),self._load_file_path))

        except OSError as error:
            Logger.logerr('PublishJointListFromFile: Failed to read file "{}": {}'.format(self._load_file_path,error))
            userdata.joint_list = []

    def execute(self, userdata):
        """
        on_enter() で読み込み済みなので、成功していれば done を返す。
        """

        userdata.joint_list = self._joint_list
        if len(self._joint_list) == 0:
            return 'failed'

        return 'done'