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
Define wooooo.

Created on Wed Dec 24 2025
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_states.moveit_griper_close import PiperMoveItCloseState
from cotyaka_omega_flexbe_states.moveit_griper_open import PiperMoveItOpenState
from cotyaka_omega_flexbe_states.moveit_param_client_joint import MoveItJointClientParamState

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class woooooSM(Behavior):
    """
    Define wooooo.

    playground and test
    """

    def __init__(self, node):
        super().__init__()
        self.name = 'wooooo'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)
        MoveItJointClientParamState.initialize_ros(node)
        PiperMoveItCloseState.initialize_ros(node)
        PiperMoveItOpenState.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:586 y:269, x:263 y:292
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:65 y:67
            OperatableStateMachine.add('1',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.0,0.0,0.0,0.0,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': '2', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:318 y:67
            OperatableStateMachine.add('2',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.44,-1.0,0.0,0.58,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': '1', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:332 y:416
            OperatableStateMachine.add('close',
                                       PiperMoveItCloseState(target_value=0.0, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'close', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:56 y:413
            OperatableStateMachine.add('open',
                                       PiperMoveItOpenState(target_value=0.098, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'open', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
