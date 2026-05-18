#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxySubscriberCached

from sensor_msgs.msg import JointState


class RecordJoint(EventState):
    """
    Record current joint angles from JointState.

    -- joint_state_topic       string    JointState topic name.
    -- joint_names             list      Target joint names.

    #> joint_list              list      Recorded joint angle list.

    <= done                              Joint angles recorded.
    """

    def __init__(self,
                 joint_state_topic='/joint_states',
                 joint_names=None):

        super().__init__(
            outcomes=['done'],
            output_keys=['joint_list']
        )

        self._joint_state_topic = joint_state_topic

        if joint_names is None:
            self._joint_names = [
                'joint1',
                'joint2',
                'joint3',
                'joint4',
                'joint5',
                'joint6',
                'joint7'
            ]
        else:
            self._joint_names = joint_names

        self._sub = ProxySubscriberCached({
            self._joint_state_topic: JointState
        })

        self._recorded_joint_list = []

    def on_enter(self, userdata):
        joint_values = self._get_current_joint_values()

        if joint_values is None:
            Logger.logwarn(
                'RecordJoint: JointState has not been received yet, or required joints are missing.'
            )
            return

        self._recorded_joint_list.append(joint_values)
        userdata.joint_list = self._recorded_joint_list

        Logger.loginfo(
            'RecordJoint: Recorded {}: {}'.format(
                len(self._recorded_joint_list),
                joint_values
            )
        )

    def execute(self, userdata):
        # on_enterで記録済みなので即done
        userdata.joint_list = self._recorded_joint_list
        return 'done'

    def _get_current_joint_values(self):
        if not self._sub.has_msg(self._joint_state_topic):
            return None

        msg = self._sub.get_last_msg(self._joint_state_topic)

        name_to_position = dict(zip(msg.name, msg.position))

        joint_values = []

        for joint_name in self._joint_names:
            if joint_name not in name_to_position:
                Logger.logwarn(
                    'RecordJoint: Required joint "{}" is not in JointState.'.format(
                        joint_name
                    )
                )
                return None

            joint_values.append(name_to_position[joint_name])

        return joint_values