#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flexbe_core import EventState, Logger


class PublishJoint(EventState):
    '''
    RecordJoint で保存した関節角度リストから、
    指定された index に対応する関節角度を userdata に出力するState。

    リストの最後まで出力済みなら complete、
    まだ残っているなら repeat を返す。

    ># joint_list   list    記録された関節角度リスト
                        形式:
                        [
                          [joint1, joint2, ..., joint7],
                          [joint1, joint2, ..., joint7],
                          ...
                        ]

    ># index  int  出力対象のインデックス

    #> joint_values  list    index に対応する関節角度
                        形式:
                        [joint1, joint2, ..., joint7]

    <= repeat           今回の index の関節角度を出力した。
                        まだ残りがある。

    <= complete         全ての関節角度を出力済み。
    '''

    def __init__(self):
        super().__init__(
            outcomes=['repeat', 'complete'],
            input_keys=['joint_list', 'index'],
            output_keys=['joint_values']
        )

    def execute(self, userdata):
        joint_list = userdata.joint_list
        index = userdata.index

        if joint_list is None:
            Logger.logwarn('PublishJoint: joint_list is None.')
            return 'complete'

        if len(joint_list) == 0:
            Logger.logwarn('PublishJoint: joint_list is empty.')
            return 'complete'

        if index >= len(joint_list):
            Logger.loginfo(
                'PublishJoint: All joint records have been published.'
            )
            return 'complete'

        userdata.joint_values = joint_list[index]

        Logger.loginfo(
            'PublishJoint: Published index {} / {}: {}'.format(
                index,
                len(joint_list) - 1,
                userdata.joint_values
            )
        )

        if index >= len(joint_list) - 1:
            return 'complete'

        return 'repeat'