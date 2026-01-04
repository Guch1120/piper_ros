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
Define Grasp_to_TF.

Created on Sun Jan 04 2026
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_states.moveit_client_tf import MoveItTfClientState
from cotyaka_omega_flexbe_states.moveit_griper_close import PiperMoveItCloseState
from cotyaka_omega_flexbe_states.moveit_griper_open import PiperMoveItOpenState
from cotyaka_omega_flexbe_states.moveit_param_client_joint import MoveItJointClientParamState

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class Grasp_to_TFSM(Behavior):
    """
    Define Grasp_to_TF.

    move zero position and grasp on TF
    """

    def __init__(self, node):
        super().__init__()
        self.name = 'Grasp_to_TF'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)
        MoveItJointClientParamState.initialize_ros(node)
        MoveItTfClientState.initialize_ros(node)
        PiperMoveItCloseState.initialize_ros(node)
        PiperMoveItOpenState.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:864 y:322, x:530 y:324
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])
        _state_machine.userdata.target_frame = ""

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:100 y:87
            OperatableStateMachine.add('move_zero',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.0,0.0,0.0,0.0,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'gripper_open', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:331 y:92
            OperatableStateMachine.add('gripper_open',
                                       PiperMoveItOpenState(target_value=0.098, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'move_tf', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:539 y:93
            OperatableStateMachine.add('move_tf',
                                       MoveItTfClientState(group_name='arm', end_effector_link='link6', reference_frame='base_link', pos_tolerance=0.01, orient_tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'gripper_close', 'failed': 'gripper_open'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off},
                                       remapping={'target_frame': 'target_frame'})

            # x:790 y:84
            OperatableStateMachine.add('gripper_close',
                                       PiperMoveItCloseState(target_value=0.0, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'finished', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
