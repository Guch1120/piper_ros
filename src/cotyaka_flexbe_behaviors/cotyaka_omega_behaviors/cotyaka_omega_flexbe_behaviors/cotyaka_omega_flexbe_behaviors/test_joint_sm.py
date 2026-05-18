#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2026 Yamaguchi Takuma
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
Define test_joint.

Created on Tue May 12 2026
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_states.moveit_client_tf import MoveItClientTF
from cotyaka_omega_flexbe_states.moveit_param_client_joint import MoveItJointClientParamState
from cotyaka_omega_flexbe_states.moveit_param_client_tf import MoveItTfClientParamState

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class test_jointSM(Behavior):
    """
    Define test_joint.

    test joint playground

    """

    def __init__(self, node):
        super().__init__()
        self.name = 'test_joint'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)
        MoveItClientTF.initialize_ros(node)
        MoveItJointClientParamState.initialize_ros(node)
        MoveItTfClientParamState.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:319 y:500, x:460 y:520
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])
        _state_machine.userdata.index = 0

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:28 y:117
            OperatableStateMachine.add('a',
                                       MoveItTfClientParamState(group_name='arm', end_effector_link='link6', reference_frame='base_link', target_frame='interactive_set', pos_tolerance=0.01, orient_tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'a', 'failed': 'a'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:26 y:199
            OperatableStateMachine.add('aa',
                                       MoveItClientTF(group_name='arm', end_effector_link='link6', reference_frame='base_link', pos_tolerance=0.01, orient_tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'aa', 'failed': 'aa'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off},
                                       remapping={'target_frame': 'target_frame'})

            # x:37 y:288
            OperatableStateMachine.add('aaa',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.0,0.0,0.0,0.0,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'aaa', 'failed': 'aaa'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
