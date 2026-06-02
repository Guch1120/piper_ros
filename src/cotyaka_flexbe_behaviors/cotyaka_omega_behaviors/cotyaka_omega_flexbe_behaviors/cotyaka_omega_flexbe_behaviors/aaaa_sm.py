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
Define aaaa.

Created on Wed Dec 24 2025
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_states.broadcast_static_tf_param import BroadcastStaticTFParamState
from cotyaka_omega_flexbe_states.moveit_client_tf import MoveItClientTF

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class aaaaSM(Behavior):
    """
    Define aaaa.

    aaaaaaa

    """

    def __init__(self, node):
        super().__init__()
        self.name = 'aaaa'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)
        BroadcastStaticTFParamState.initialize_ros(node)
        MoveItClientTF.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:30 y:365, x:130 y:365
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])
        _state_machine.userdata.index = 0
        _state_machine.userdata.object_list = ["floor"]
        _state_machine.userdata.target_frame = 'target_position'

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:93 y:65
            OperatableStateMachine.add('aa',
                                       BroadcastStaticTFParamState(parent_frame='base_link', child_frame='target_position', xyz_val=[0.4,0.25,0.0], rpy_val=[0.0,0.0,0.0], wait_time=0.5),
                                       transitions={'done': 'a'},
                                       autonomy={'done': Autonomy.Off})

            # x:83 y:188
            OperatableStateMachine.add('a',
                                       MoveItClientTF(group_name='arm', end_effector_link='link6', reference_frame='base_link', pos_tolerance=0.01, orient_tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'finished', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off},
                                       remapping={'target_frame': 'target_frame'})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
