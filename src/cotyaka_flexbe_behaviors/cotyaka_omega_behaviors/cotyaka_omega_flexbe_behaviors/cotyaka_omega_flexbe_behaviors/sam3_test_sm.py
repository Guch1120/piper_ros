#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2025 Yamaguchi Takuma
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

###########################################################
#               WARNING: Generated code!                  #
#              **************************                 #
# Manual changes may get lost if file is generated again. #
# Only code inside the [MANUAL] tags will be kept.        #
###########################################################

"""
Define sam3_test.

Created on Thu Dec 25 2025
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_states.broadcast_tf_from_vison import BroadcastTFfromVision
from cotyaka_omega_flexbe_states.moveit_param_client_joint import MoveItJointClientParamState
from cotyaka_omega_flexbe_states.sam3_detect_object import DetectObjectWithSAM3State

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class sam3_testSM(Behavior):
    """
    Define sam3_test.

    test

    """

    def __init__(self, node):
        super().__init__()
        self.name = 'sam3_test'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)
        BroadcastTFfromVision.initialize_ros(node)
        DetectObjectWithSAM3State.initialize_ros(node)
        MoveItJointClientParamState.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:606 y:239, x:500 y:244
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:69 y:31
            OperatableStateMachine.add('detect',
                                       DetectObjectWithSAM3State(object_name="apple"),
                                       transitions={'succeeded': 'tf', 'failed': 'Pose for init', 'timeout': 'failed'},
                                       autonomy={'succeeded': Autonomy.Off, 'failed': Autonomy.Off, 'timeout': Autonomy.Off},
                                       remapping={'u': 'u', 'v': 'v', 'z': 'z'})

            # x:36 y:296
            OperatableStateMachine.add('pose of detect',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.15,1.29,-1.1,-0.18,0.66,0.25], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'detect', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:532 y:35
            OperatableStateMachine.add('tf',
                                       BroadcastTFfromVision(parent_frame="base_link", child_frame="target", camera_frame="camera_color_optical_frame", camera_info_topic='/camera/camera/aligned_depth_to_color/camera_info', wait_info_sec=0.5, tf_timeout_sec=2.0),
                                       transitions={'succeeded': 'finished', 'tf_not_found': 'failed', 'failed': 'failed'},
                                       autonomy={'succeeded': Autonomy.Off, 'tf_not_found': Autonomy.Off, 'failed': Autonomy.Off},
                                       remapping={'u': 'u', 'v': 'v', 'z': 'z'})

            # x:172 y:188
            OperatableStateMachine.add('Pose for init',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.0,0.0,0.0,0.0,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'pose of detect', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
