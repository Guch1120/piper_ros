#!/usr/bin/env python3
import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyActionClient
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint

class PiperMoveItState(EventState):
    '''
    State to move the Piper robot arm using MoveIt.

    -- timeout      float       Timeout for the motion.

    ># target_joints dict       Dictionary of joint names and target angles (radians).

    <= reached                  Target reached.
    <= failed                   Failed to reach target.
    '''

    def __init__(self, timeout=5.0):
        super(PiperMoveItState, self).__init__(outcomes=['reached', 'failed'],
                                               input_keys=['target_joints'])
        self._action_topic = 'move_action'
        self._client = ProxyActionClient({self._action_topic: MoveGroup})
        self._timeout = timeout
        self._error = False

    def on_enter(self, userdata):
        self._error = False
        
        # Check if client is available
        if not self._client.is_available(self._action_topic):
            Logger.logwarn('Action client %s not available!' % self._action_topic)
            self._error = True
            return

        # Create goal
        goal = MoveGroup.Goal()
        goal.request.group_name = 'arm'
        goal.request.allowed_planning_time = self._timeout
        
        constraints = Constraints()
        try:
            for name, angle in userdata.target_joints.items():
                jc = JointConstraint()
                jc.joint_name = name
                jc.position = float(angle)
                jc.tolerance_above = 0.01
                jc.tolerance_below = 0.01
                jc.weight = 1.0
                constraints.joint_constraints.append(jc)
        except Exception as e:
            Logger.logwarn('Failed to parse target_joints: %s' % str(e))
            self._error = True
            return
            
        goal.request.goal_constraints.append(constraints)

        # Send goal
        try:
            self._client.send_goal(self._action_topic, goal)
            Logger.loginfo('Goal sent to MoveIt')
        except Exception as e:
            Logger.logwarn('Failed to send goal: %s' % str(e))
            self._error = True

    def execute(self, userdata):
        if self._error:
            return 'failed'

        if self._client.has_result(self._action_topic):
            result = self._client.get_result(self._action_topic)
            if result.error_code.val == 1: # SUCCESS
                Logger.loginfo('MoveIt execution successful')
                return 'reached'
            else:
                Logger.logwarn('MoveIt failed with error code: %s' % str(result.error_code.val))
                return 'failed'
        
        # TODO: Handle timeout if needed, though MoveIt handles planning time.
        
    def on_exit(self, userdata):
        if not self._client.has_result(self._action_topic):
            self._client.cancel(self._action_topic)
            Logger.loginfo('Cancelled active goal.')
