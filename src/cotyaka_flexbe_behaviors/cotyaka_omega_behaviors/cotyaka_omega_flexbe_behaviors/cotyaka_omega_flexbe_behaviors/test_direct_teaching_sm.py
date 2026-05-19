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
Define test_direct_teaching.

Created on Mon May 18 2026
@author: Yamaguchi Takuma
"""


from flexbe_core import Autonomy
from flexbe_core import Behavior
from flexbe_core import ConcurrencyContainer
from flexbe_core import Logger
from flexbe_core import OperatableStateMachine
from flexbe_core import PriorityContainer
from cotyaka_omega_flexbe_states.arm_power_switch import ArmPowerSwitch
from cotyaka_omega_flexbe_states.increment_index import IncrementIndex
from cotyaka_omega_flexbe_states.move_joint_by_input_key_list import MoveJointListInputKey
from cotyaka_omega_flexbe_states.publish_joint import PublishJoint
from cotyaka_omega_flexbe_states.record_joint import RecordJoint
from cotyaka_omega_flexbe_states.wait_enter_check import WaitEnterCheck

# Additional imports can be added inside the following tags
# [MANUAL_IMPORT]

# [/MANUAL_IMPORT]


class test_direct_teachingSM(Behavior):
    """
    Define test_direct_teaching.

    test direct teaching playground

    """

    def __init__(self, node):
        super().__init__()
        self.name = 'test_direct_teaching'

        # parameters of this behavior

        # references to used behaviors
        OperatableStateMachine.initialize_ros(node)
        ConcurrencyContainer.initialize_ros(node)
        PriorityContainer.initialize_ros(node)
        Logger.initialize(node)
        ArmPowerSwitch.initialize_ros(node)
        IncrementIndex.initialize_ros(node)
        MoveJointListInputKey.initialize_ros(node)
        PublishJoint.initialize_ros(node)
        RecordJoint.initialize_ros(node)
        WaitEnterCheck.initialize_ros(node)

        # Additional initialization code can be added inside the following tags
        # [MANUAL_INIT]

        # [/MANUAL_INIT]

        # Behavior comments:

    def create(self):
        # x:1024 y:319, x:189 y:458
        _state_machine = OperatableStateMachine(outcomes=['finished', 'failed'])
        _state_machine.userdata.index = 0
        _state_machine.userdata.joint_list = []

        # Additional creation code can be added inside the following tags
        # [MANUAL_CREATE]

        # [/MANUAL_CREATE]
        with _state_machine:
            # x:22 y:75
            OperatableStateMachine.add('poewr OFF',
                                       ArmPowerSwitch(enable_flag=False, topic='/enable_flag', verify=True, timeout=2.0, publish_period=0.2),
                                       transitions={'done': 'wait enter key'},
                                       autonomy={'done': Autonomy.Off})

            # x:403 y:295
            OperatableStateMachine.add('move',
                                       MoveJointListInputKey(group_name='arm', joint_names=None, tolerance=0.01, action_topic='move_action', allowed_planning_time=5.0),
                                       transitions={'done': 'increment index'},
                                       autonomy={'done': Autonomy.Off},
                                       remapping={'joint_values': 'joint_values'})

            # x:520 y:74
            OperatableStateMachine.add('power ON',
                                       ArmPowerSwitch(enable_flag=True, topic='/enable_flag', verify=True, timeout=2.0, publish_period=0.2),
                                       transitions={'done': 'publish joint'},
                                       autonomy={'done': Autonomy.Off})

            # x:519 y:183
            OperatableStateMachine.add('publish joint',
                                       PublishJoint(),
                                       transitions={'repeat': 'move'},
                                       autonomy={'repeat': Autonomy.Off},
                                       remapping={'joint_list': 'joint_list', 'index': 'index', 'joint_values': 'joint_values'})

            # x:120 y:224
            OperatableStateMachine.add('record joint',
                                       RecordJoint(joint_state_topic='/joint_states', joint_names=['joint1','joint2','joint3','joint4','joint5','joint6']),
                                       transitions={'done': 'wait enter key'},
                                       autonomy={'done': Autonomy.Off},
                                       remapping={'joint_list': 'joint_list'})

            # x:270 y:74
            OperatableStateMachine.add('wait enter key',
                                       WaitEnterCheck(command_topic='/record_joint_command', record_command='record', done_command='done'),
                                       transitions={'record': 'record joint', 'done': 'power ON'},
                                       autonomy={'record': Autonomy.Off, 'done': Autonomy.Off})

            # x:720 y:296
            OperatableStateMachine.add('increment index',
                                       IncrementIndex(),
                                       transitions={'done': 'publish joint', 'complete': 'finished'},
                                       autonomy={'done': Autonomy.Off, 'complete': Autonomy.Off},
                                       remapping={'index': 'index', 'target_list': 'joint_list'})

        return _state_machine

    # Private functions can be added inside the following tags
    # [MANUAL_FUNC]

    # [/MANUAL_FUNC]
