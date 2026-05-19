#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flexbe_core import EventState, Logger


class IncrementIndex(EventState):
    '''
    インデックスを加算し、対象リストの処理が完了したかを確認する。

    ># index        int     現在のインデックス。
    ># target_list  list    長さ確認対象のリスト。

    #> index        int     加算後のインデックス。

    <= done                 次のインデックスが利用可能。
    <= complete             インデックスが対象リストの長さを超えた。
    '''

    def __init__(self):
        super().__init__(
            outcomes=['done', 'complete'],
            input_keys=['index', 'target_list'],
            output_keys=['index']
        )

    def execute(self, userdata):
        target_list = userdata.target_list

        if target_list is None:
            Logger.logwarn('IncrementIndex: target_list is None.')
            return 'complete'

        if len(target_list) == 0:
            Logger.logwarn('IncrementIndex: target_list is empty.')
            return 'complete'

        # 現在の index の処理が終わった後に呼ばれる前提なので、
        # ここで次の index に進める。
        userdata.index = userdata.index + 1

        Logger.loginfo(
            'IncrementIndex: index incremented to {} / {}'.format(
                userdata.index,
                len(target_list) - 1
            )
        )

        # index がリスト長以上になったら、全要素を処理済み
        if userdata.index >= len(target_list):
            Logger.loginfo(
                'IncrementIndex: complete. index={} len={}'.format(
                    userdata.index,
                    len(target_list)
                )
            )
            return 'complete'

        return 'done'