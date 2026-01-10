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
Define pick_and_place_with_using_TF.

Created on Sun Jan 04 2026
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_behaviors.grasp_to_tf_sm import Grasp_to_TFSM
from cotyaka_omega_flexbe_behaviors.sam3_test_sm import sam3_testSM

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class pick_and_place_with_using_TFSM(Behavior):
    """
    Define pick_and_place_with_using_TF.

    pick and place with using TF

    """

    def __init__(self, node):
        super().__init__()
        self.name = 'pick_and_place_with_using_TF'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)

        self.add_behavior(Grasp_to_TFSM, 'Grasp_to_TF', node)
        self.add_behavior(sam3_testSM, 'sam3_test', node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:830 y:332, x:483 y:347
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])
        _state_machine.userdata.target_frame = "target"

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:377 y:70
            OperatableStateMachine.add('sam3_test',
                                       self.use_behavior(sam3_testSM, 'sam3_test'),
                                       transitions={'finished': 'Grasp_to_TF', 'failed': 'failed'},
                                       autonomy={'finished': Autonomy.Inherit, 'failed': Autonomy.Inherit})

            # x:718 y:67
            OperatableStateMachine.add('Grasp_to_TF',
                                       self.use_behavior(Grasp_to_TFSM, 'Grasp_to_TF'),
                                       transitions={'finished': 'finished', 'failed': 'failed'},
                                       autonomy={'finished': Autonomy.Inherit, 'failed': Autonomy.Inherit})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
