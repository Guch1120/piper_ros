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
from cotyaka_omega_flexbe_states.moveit_client_tf import MoveItClientTF
from cotyaka_omega_flexbe_states.sam3_centorpoint_to_tf import Sam3CentorPointToTF
from cotyaka_omega_flexbe_states.transform_tf import TransformTF

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
        MoveItClientTF.initialize_ros(node)
        Sam3CentorPointToTF.initialize_ros(node)
        TransformTF.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:449 y:269, x:69 y:347
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])
        _state_machine.userdata.index = 0
        _state_machine.userdata.object_list = ["floor"]
        _state_machine.userdata.object_name = "apple"
        _state_machine.userdata.angle = 0
        _state_machine.userdata.source_frame = "sam3_apple_tf"

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:96 y:108
            OperatableStateMachine.add('aa',
                                       Sam3CentorPointToTF(centroid_topic="/sam3/mask/centroid", depth_topic="/camera/camera/aligned_depth_to_color/image_raw", camera_info_topic="/camera/camera/color/camera_info", parent_frame_id="world", child_frame_prefix="sam3_", child_frame_suffix="_tf", timeout=10.0, depth_search_radius=3),
                                       transitions={'done': 'aaa', 'failed': 'failed', 'timeout': 'aa'},
                                       autonomy={'done': Autonomy.Off, 'failed': Autonomy.Off, 'timeout': Autonomy.Off},
                                       remapping={'object_name': 'object_name'})

            # x:155 y:257
            OperatableStateMachine.add('aaa',
                                       TransformTF(target_frame="world", output_frame_prefix="target_", tf_timeout=1.0),
                                       transitions={'done': 'move'},
                                       autonomy={'done': Autonomy.Off},
                                       remapping={'object_name': 'object_name', 'source_frame': 'source_frame', 'angle': 'angle', 'after_transform': 'after_transform'})

            # x:213 y:368
            OperatableStateMachine.add('move',
                                       MoveItClientTF(group_name='arm', end_effector_link='link6', reference_frame='base_link', pos_tolerance=0.01, orient_tolerance=0.01, action_topic='move_action'),
                                       transitions={'reached': 'finished', 'failed': 'failed'},
                                       autonomy={'reached': Autonomy.Off, 'failed': Autonomy.Off},
                                       remapping={'target_frame': 'after_transform'})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
