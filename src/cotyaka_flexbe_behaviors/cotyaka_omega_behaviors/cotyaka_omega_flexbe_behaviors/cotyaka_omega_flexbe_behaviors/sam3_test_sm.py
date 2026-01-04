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

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:573 y:184, x:130 y:365
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:30 y:40
            OperatableStateMachine.add('detect',
                                       DetectObjectWithSAM3State(object_name="pen"),
                                       transitions={'succeeded': 'tf', 'failed': 'failed', 'timeout': 'failed'},
                                       autonomy={'succeeded': Autonomy.Off, 'failed': Autonomy.Off, 'timeout': Autonomy.Off},
                                       remapping={'u': 'u', 'v': 'v', 'z': 'z'})

            # x:296 y:49
            OperatableStateMachine.add('tf',
                                       BroadcastTFfromVision(parent_frame="camera_link", child_frame="target", camera_frame="camera_link"),
                                       transitions={'succeeded': 'finished', 'tf_not_found': 'failed', 'failed': 'failed'},
                                       autonomy={'succeeded': Autonomy.Off, 'tf_not_found': Autonomy.Off, 'failed': Autonomy.Off},
                                       remapping={'u': 'u', 'v': 'v', 'z': 'z'})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
