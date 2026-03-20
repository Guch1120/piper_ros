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
Define pick_and_place_with_kobuki.

Created on Tue Mar 17 2026
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


class pick_and_place_with_kobukiSM(Behavior):
    """
    Define pick_and_place_with_kobuki.

    pick and place with kobuki.
    .....no tumori 
    """

    def __init__(self, node):
        super().__init__()
        self.name = 'pick_and_place_with_kobuki'

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
        # x:1639 y:628, x:710 y:702
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:86 y:42
            OperatableStateMachine.add('move_to_zero',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.0,0.0,0.0,0.0,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'move_above', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:333 y:50
            OperatableStateMachine.add('move_above',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.01,1.34,-1.9,0.06,0.79,0.21], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'move_beofre_grasp', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:1096 y:255
            OperatableStateMachine.add('move_after_place',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.01,1.3,-1.9,0.06,0.79,0.21], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'move_tjo_zero_after', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:554 y:43
            OperatableStateMachine.add('move_beofre_grasp',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.01,1.69,-1.82,-0.08,0.32,0.24], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'open', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:824 y:160
            OperatableStateMachine.add('move_for_grasp',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.0,0.0,0.0,0.0,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'close', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:1354 y:366
            OperatableStateMachine.add('move_for_place',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[-2.48,2.56,-2.51,1.61,0.63,-1.42], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'open_place', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:1351 y:263
            OperatableStateMachine.add('move_tjo_zero_after',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.0,0.0,0.0,0.0,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'move_for_place', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:816 y:36
            OperatableStateMachine.add('open',
                                       PiperMoveItOpenState(target_value=0.098, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'move_for_grasp', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:1588 y:377
            OperatableStateMachine.add('open_place',
                                       PiperMoveItOpenState(target_value=0.098, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'finished', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:839 y:262
            OperatableStateMachine.add('close',
                                       PiperMoveItCloseState(target_value=0.0, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'move_after_place', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
