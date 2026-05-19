#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
from flexbe_core import EventState, Logger


class waittime(EventState):
    '''
    指定秒数だけ FlexBE のステート遷移を待機する State。

    -- wait_time   float   Wait time [sec]

    <= done                Wait finished
    '''

    def __init__(self, wait_time=1.0):
        super(waittime, self).__init__(outcomes=['done'])
        self._wait_time = float(wait_time)
        self._start_time = None

    def on_enter(self, userdata):
        self._start_time = rospy.Time.now()
        Logger.loginfo('waittime: wait for {:.2f} sec'.format(self._wait_time))

    def execute(self, userdata):
        if self._start_time is None:
            self._start_time = rospy.Time.now()
        elapsed = rospy.Time.now() - self._start_time
        if elapsed >= rospy.Duration(self._wait_time):
            Logger.loginfo('waittime: done')
            return 'done'
        return None # まだ待機中なので outcome を返さない