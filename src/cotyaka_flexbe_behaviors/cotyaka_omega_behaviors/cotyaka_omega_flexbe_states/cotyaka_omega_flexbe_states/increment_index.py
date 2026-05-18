#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flexbe_core import EventState, Logger


class IncrementIndex(EventState):
    '''
    userdata の index をインクリメントするState。

    ># index  int  現在のインデックス

    #> index  int  インクリメント後のインデックス

    <= done     インクリメント完了
    '''

    def __init__(self):
        super().__init__(
            outcomes=['done'],
            input_keys=['index'],
            output_keys=['index']
        )

    def execute(self, userdata):
        userdata.index = userdata.index + 1

        Logger.loginfo(
            'IncrementIndex: index incremented to {}'.format(
                userdata.index
            )
        )

        return 'done'