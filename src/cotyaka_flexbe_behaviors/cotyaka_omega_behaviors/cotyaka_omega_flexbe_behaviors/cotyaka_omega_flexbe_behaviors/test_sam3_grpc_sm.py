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
Define test sam3 gRPC.

Created on Tue May 19 2026
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_states.increment_index import IncrementIndex
from cotyaka_omega_flexbe_states.publish_object_name import PublishObjectName
from cotyaka_omega_flexbe_states.sam3_centorpoint_to_tf import Sam3CentorPointToTF
from cotyaka_omega_flexbe_states.wait_time import waittime

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class testsam3gRPCSM(Behavior):
    """
    Define test sam3 gRPC.

    test sam3 gRPC playground

    """

    def __init__(self, node):
        super().__init__()
        self.name = 'test sam3 gRPC'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)
        IncrementIndex.initialize_ros(node)
        PublishObjectName.initialize_ros(node)
        Sam3CentorPointToTF.initialize_ros(node)
        waittime.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:791 y:274, x:669 y:182
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])
        _state_machine.userdata.object_list = ["floor"]
        _state_machine.userdata.index = 0

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:100 y:34
            OperatableStateMachine.add('Publish object name',
                                       PublishObjectName(),
                                       transitions={'done': 'finished'},
                                       autonomy={'done': Autonomy.Off},
                                       remapping={'object_list': 'object_list', 'index': 'index', 'object_name': 'object_name'})

            # x:114 y:256
            OperatableStateMachine.add('index',
                                       IncrementIndex(),
                                       transitions={'done': 'wait 1sec', 'complete': 'finished'},
                                       autonomy={'done': Autonomy.Off, 'complete': Autonomy.Off},
                                       remapping={'index': 'index', 'target_list': 'object_list'})

            # x:350 y:137
            OperatableStateMachine.add('wait 1sec',
                                       waittime(wait_time=1.0),
                                       transitions={'done': 'Publish TF'},
                                       autonomy={'done': Autonomy.Off})

            # x:580 y:34
            OperatableStateMachine.add('Publish TF',
                                       Sam3CentorPointToTF(centroid_topic="/sam3/mask/centroid", parent_frame_id="base_link", child_frame_prefix="sam3_", child_frame_suffix="_tf", timeout=5.0),
                                       transitions={'done': 'Publish object name', 'failed': 'failed', 'timeout': 'Publish TF'},
                                       autonomy={'done': Autonomy.Off, 'failed': Autonomy.Off, 'timeout': Autonomy.Off},
                                       remapping={'object_name': 'object_name'})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
