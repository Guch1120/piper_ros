#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import re
import traceback
from flexbe_core import EventState, Logger
from geometry_msgs.msg import TransformStamped
from rclpy.duration import Duration
from rclpy.time import Time
from tf2_ros import Buffer, TransformException
from tf2_ros.transform_listener import TransformListener
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
from tf_transformations import quaternion_from_euler, quaternion_multiply


class TransformTF(EventState):
    '''
    入力されたsource_frameを
    target_frame基準の把持用TFに変換して発行する。

    例:
      object_name = "apple"
      source_frame = "sam3_apple_tf"

      入力TF:
        任意の親フレーム -> sam3_apple_tf

      出力TF:
        map -> target_apple

    -- target_frame              string  変換先の基準座標系(default: "map")
    -- output_frame_prefix       string  出力TF prefix(default: "target_")
    -- tf_timeout                float   TF待機時間[sec]

    ># object_name               string  出力TF名に使う物体名
    ># source_frame              string  変換元TF名
    ># angle                     float   grasp angle[rad]

    #> after_transform           TransformStamped  変換後TF

    <= done                      transform complete
    '''

    def __init__(self,target_frame="map",output_frame_prefix="target_",tf_timeout=1.0):
        super(TransformTF, self).__init__(
            outcomes=['done'],
            input_keys=['object_name', 'source_frame', 'angle'],
            output_keys=['after_transform']
        )

        self.target_frame = target_frame
        self.output_frame_prefix = output_frame_prefix
        self.tf_timeout = float(tf_timeout)
        self._node = EventState._node
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer,self._node)
        self.broadcaster = StaticTransformBroadcaster(self._node)
        Logger.loginfo("[TransformTF] initialized.")

    def execute(self, userdata):
        object_name = str(getattr(userdata, 'object_name', '')).strip()
        source_frame = str(getattr(userdata, 'source_frame', '')).strip()

        if object_name == '':
            Logger.logwarn('[TransformTF] object_name is empty.')
            return None

        if source_frame == '':
            Logger.logwarn('[TransformTF] source_frame is empty.')
            return None

        output_frame = self._build_output_frame_id(object_name)

        Logger.loginfo(
            '[TransformTF] object_name={} source_frame={} target_frame={} output_frame={}'.format(
                object_name,
                source_frame,
                self.target_frame,
                output_frame
            )
        )

        try:
            # target_frame から source_frame への変換を取得する
            #
            # 例:
            #   target_frame = map
            #   source_frame = sam3_apple_tf
            #
            # 結果:
            #   map -> sam3_apple_tf の位置姿勢
            trans = self.tf_buffer.lookup_transform(
                self.target_frame,
                source_frame,
                Time(),
                timeout=Duration(seconds=self.tf_timeout)
            )

        except TransformException as e:
            Logger.logwarn(
                '[TransformTF] TF transform NG: {} -> {}: {}'.format(
                    self.target_frame,
                    source_frame,
                    e
                )
            )
            traceback.print_exc()
            return None

        try:
            angle = float(userdata.angle)
        except Exception:
            Logger.logwarn('[TransformTF] userdata.angle is invalid.')
            return None

        # 把持用の姿勢を作る
        #
        # q1 = Ry(-90deg)
        # q2 = Rz(180deg)
        # q3 = Rx(angle)
        #
        # q = q2 * q1 * q3
        rotate_pitch = math.radians(90.0)
        rotate_yaw = math.radians(0.0)
        q1 = quaternion_from_euler(0.0, rotate_pitch, 0.0)
        q2 = quaternion_from_euler(0.0, 0.0, rotate_yaw)
        q3 = quaternion_from_euler(angle, 0.0, 0.0)
        q = quaternion_multiply(q2, q1)
        q = quaternion_multiply(q, q3)

        after_transform = TransformStamped()
        after_transform.header.frame_id = self.target_frame
        after_transform.header.stamp = self._node.get_clock().now().to_msg()
        after_transform.child_frame_id = output_frame

        # 位置は source_frame から取得した値を使う
        after_transform.transform.translation.x = trans.transform.translation.x
        after_transform.transform.translation.y = trans.transform.translation.y
        after_transform.transform.translation.z = trans.transform.translation.z

        # 姿勢は把持用に上書きする
        after_transform.transform.rotation.x = q[0]
        after_transform.transform.rotation.y = q[1]
        after_transform.transform.rotation.z = q[2]
        after_transform.transform.rotation.w = q[3]

        userdata.after_transform = output_frame
        Logger.loginfo(
            f"[TransformTF] xyz=({after_transform.transform.translation.x:.3f}, "
            f"{after_transform.transform.translation.y:.3f}, "
            f"{after_transform.transform.translation.z:.3f})"
        )

        Logger.loginfo(f"[TransformTF] output={userdata.after_transform}")
        try:
            self.broadcaster.sendTransform(after_transform)

            Logger.loginfo(
                '[TransformTF] TF write complete: {} -> {}'.format(
                    self.target_frame,
                    output_frame
                )
            )

        except Exception as e:
            Logger.logwarn(
                '[TransformTF] TF write failed: {}'.format(e)
            )
            return None
        return 'done'

    def _build_output_frame_id(self, object_name):
        """
        出力側TF名を作る。
        """
        name = self._normalize_object_name(object_name)
        return '{}{}'.format(self.output_frame_prefix,name)

    @staticmethod
    def _normalize_object_name(object_name):
        """
        TF名として使えるように物体名を整形する。
        空白や記号は '_' に置換し、小文字化する。
        """
        name = object_name.strip() or 'object'
        name = re.sub(r'[^A-Za-z0-9_]+', '_', name)
        name = name.strip('_').lower() or 'object'
        return name