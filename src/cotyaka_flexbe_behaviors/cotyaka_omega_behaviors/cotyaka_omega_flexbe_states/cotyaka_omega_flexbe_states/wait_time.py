#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from flexbe_core import EventState, Logger


class waittime(EventState):
    """
    指定秒数だけ FlexBE のステート遷移を待機する State。

    execute() 内で sleep しないため、FlexBE 全体をブロックしにくい。

    -- wait_time   float   Wait time [sec]

    <= done                Wait finished
    """

    def __init__(self, wait_time=1.0):
        super(waittime, self).__init__(outcomes=['done'])
        self._wait_time = float(wait_time)
        self._start_time = None

    def on_enter(self, userdata):
        self._start_time = time.monotonic()
        Logger.loginfo('waittime: wait for {:.2f} sec'.format(self._wait_time))

    def execute(self, userdata):
        if self._start_time is None:
            self._start_time = time.monotonic()

        elapsed = time.monotonic() - self._start_time
        if elapsed >= self._wait_time:
            Logger.loginfo('waittime: done')
            return 'done'

        return None

    def on_exit(self, userdata):
        self._start_time = None