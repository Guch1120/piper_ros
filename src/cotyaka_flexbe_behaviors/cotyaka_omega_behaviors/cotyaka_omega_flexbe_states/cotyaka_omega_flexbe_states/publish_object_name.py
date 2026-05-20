#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher
from std_msgs.msg import String


class PublishObjectName(EventState):
    """
    object_list[index]を/object_nameにpublishする

    このステートはindexの更新・範囲管理は行わない
    indexの管理は別Stateで行う。

    ># object_list   list    Object name list
    ># index         int     Current index

    #> object_name   string  Published object name

    <= done                  Published successfully
    """

    def __init__(self):
        super(PublishObjectName, self).__init__(outcomes=['done'],input_keys=['object_list', 'index'],output_keys=['object_name'])
        self._topic = '/object_name'
        self._pub = ProxyPublisher({self._topic: String})

    @staticmethod
    def _extract_object_name(entry):
        """
        object_list の要素から object_name を取り出す。

        想定:
          - "apple"
          - {"object_name": "apple"}
          - {"name": "apple"}
          - {"label": "apple"}
          - {"color_type": "apple"}
        """
        if isinstance(entry, dict):
            for key in ['object_name', 'name', 'label', 'color_type']:
                value = entry.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return ''

        if entry is None:
            return ''

        return str(entry).strip()

    def execute(self, userdata):
        Logger.loginfo('PublishObjectName: start')
        Logger.loginfo('  index       = {}'.format(userdata.index))
        Logger.loginfo('  object_list = {}'.format(userdata.object_list))

        userdata.object_name = ''

        try:
            current_index = int(userdata.index)
        
    #---------------------------------------------------------------------------------------------------
    #-----------------------ここからエラーハンドリング-----------------------------------------------------
    #----------------------------------------------------------------------------------------------------
        except Exception as e:
            Logger.logerr('PublishObjectName: userdata.index cannot be converted to int. ''index={}, error={}'.format(userdata.index, e))
            return 'done'
        if userdata.object_list is None:
            Logger.logerr('PublishObjectName: object_list is None.')
            return 'done'

        if not isinstance(userdata.object_list, list):
            Logger.logerr('PublishObjectName: object_list is not list. type={}'.format(type(userdata.object_list)))
            return 'done'

        if current_index < 0 or current_index >= len(userdata.object_list):
            Logger.logerr('PublishObjectName: index out of range. index={}, len={}'.format(current_index,len(userdata.object_list)))
            return 'done'
    #---------------------------------------------------------------------------------------------------
    #-----------------------ここまでエラーハンドリング-----------------------------------------------------
    #----------------------------------------------------------------------------------------------------
        object_entry = userdata.object_list[current_index]
        object_name = self._extract_object_name(object_entry)

        if not object_name:
            Logger.logwarn('PublishObjectName: could not extract object_name from entry: {}'.format(object_entry))
            return 'done'

        userdata.object_name = object_name
        msg = String()
        msg.data = object_name
        self._pub.publish(self._topic, msg)
        Logger.loginfo('PublishObjectName: published {} = {}'.format(self._topic,object_name))

        return 'done'