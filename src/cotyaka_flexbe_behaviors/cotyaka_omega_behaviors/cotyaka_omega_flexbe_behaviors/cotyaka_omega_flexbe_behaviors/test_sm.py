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
Define test.

Created on Mon Dec 15 2025
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_states.broadcast_tf_param import BroadcastStaticTFParamState
from cotyaka_omega_flexbe_states.moveit_griper_close import PiperMoveItCloseState
from cotyaka_omega_flexbe_states.moveit_griper_open import PiperMoveItOpenState
from cotyaka_omega_flexbe_states.moveit_param_client_joint import MoveItJointClientParamState
from cotyaka_omega_flexbe_states.moveit_param_client_tf import MoveItTfClientParamState

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class testSM(Behavior):
    """
    Define test.

    test 'grasp and slide

    """

    def __init__(self, node):
        super().__init__()
        self.name = 'test'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)
        BroadcastStaticTFParamState.initialize_ros(node)
        MoveItJointClientParamState.initialize_ros(node)
        MoveItTfClientParamState.initialize_ros(node)
        PiperMoveItCloseState.initialize_ros(node)
        PiperMoveItOpenState.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:1149 y:371, x:639 y:372
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:102 y:44
            OperatableStateMachine.add('Broadcast_TF',
                                       BroadcastStaticTFParamState(parent_frame='base_link', child_frame='interactive_set', xyz_val=[0.45,0.0,0.0], rpy_val=[-1.5,1.7,-1.5], wait_time=1.0),
                                       transitions={'done': 'Move_ZeroPosition'},
                                       autonomy={'done': Autonomy.Off})

            # x:853 y:33
            OperatableStateMachine.add('Change_Broadcast_TF',
                                       BroadcastStaticTFParamState(parent_frame='base_link', child_frame='interactive_set', xyz_val=[0.39,-0.32,0.03], rpy_val=[-0.4,1.5,-1.0], wait_time=1.0),
                                       transitions={'done': 'Move_TF_Position2'},
                                       autonomy={'done': Autonomy.Off})

            # x:614 y:36
            OperatableStateMachine.add('Gripper_Close_for_Grasp',
                                       PiperMoveItCloseState(target_value=0.063, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'Change_Broadcast_TF', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:354 y:161
            OperatableStateMachine.add('Gripper_Open_1',
                                       PiperMoveItOpenState(target_value=0.098, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'Move_TF_Position', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:1072 y:157
            OperatableStateMachine.add('Gripper_Open_for_lerease',
                                       PiperMoveItOpenState(target_value=0.098, joint_name='joint7', group_name='gripper', tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'Move_ZeroPosition_Finish', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:357 y:38
            OperatableStateMachine.add('Move_TF_Position',
                                       MoveItTfClientParamState(group_name='arm', end_effector_link='link6', reference_frame='base_link', target_frame='interactive_set', pos_tolerance=0.01, orient_tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'Gripper_Close_for_Grasp', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:1075 y:38
            OperatableStateMachine.add('Move_TF_Position2',
                                       MoveItTfClientParamState(group_name='arm', end_effector_link='link6', reference_frame='base_link', target_frame='interactive_set', pos_tolerance=0.01, orient_tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'Gripper_Open_for_lerease', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:107 y:178
            OperatableStateMachine.add('Move_ZeroPosition',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.0,0.0,0.0,0.0,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'Gripper_Open_1', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

            # x:1080 y:257
            OperatableStateMachine.add('Move_ZeroPosition_Finish',
                                       MoveItJointClientParamState(group_name='arm', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6'], target_joints=[0.0,0.0,0.0,0.0,0.0,0.0], tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'finished', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
