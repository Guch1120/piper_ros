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
Define test_tf.

Created on Wed Dec 24 2025
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_states.broadcast_static_tf_inout import BroadcastStaticTfInout
from cotyaka_omega_flexbe_states.transform_tf import TransformTF
from cotyaka_omega_flexbe_states.wait_time import waittime

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class test_tfSM(Behavior):
    """
    Define test_tf.

    test tf playground

    """

    def __init__(self, node):
        super().__init__()
        self.name = 'test_tf'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)
        BroadcastStaticTfInout.initialize_ros(node)
        TransformTF.initialize_ros(node)
        waittime.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:146 y:426, x:628 y:83
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])
        _state_machine.userdata.xyz_val = [0.4,0.0,0.15]
        _state_machine.userdata.rpy_val = [0.0,1.57,0.0]
        _state_machine.userdata.angle = 0

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:97 y:34
            OperatableStateMachine.add('broadcast TF',
                                       BroadcastStaticTfInout(parent_frame='base_link', child_frame='target_position', wait_time=0.5),
                                       transitions={'done': 'wait 1sec', 'failed': 'failed'},
                                       autonomy={'done': Autonomy.Off, 'failed': Autonomy.Off},
                                       remapping={'xyz_val': 'xyz_val', 'rpy_val': 'rpy_val', 'answerTF': 'answerTF'})

            # x:100 y:153
            OperatableStateMachine.add('wait 1sec',
                                       waittime(wait_time=1.0),
                                       transitions={'done': 'Transform TF'},
                                       autonomy={'done': Autonomy.Off})

            # x:98 y:278
            OperatableStateMachine.add('Transform TF',
                                       TransformTF(target_frame="world", output_frame_prefix="target_", tf_timeout=1.0),
                                       transitions={'done': 'finished'},
                                       autonomy={'done': Autonomy.Off},
                                       remapping={'object_name': 'answerTF', 'source_frame': 'answerTF', 'angle': 'angle', 'after_transform': 'after_transform'})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
