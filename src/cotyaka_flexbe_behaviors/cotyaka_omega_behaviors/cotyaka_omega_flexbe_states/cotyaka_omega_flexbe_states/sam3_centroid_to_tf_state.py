#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import threading

import rospy
import tf2_ros
from flexbe_core import EventState, Logger
from geometry_msgs.msg import Point, PointStamped, PoseStamped, TransformStamped, Vector3Stamped
from std_msgs.msg import Float32MultiArray, Float64MultiArray, Int32MultiArray, String
from tf.transformations import quaternion_from_euler


class Sam3CentroidToTFState(EventState):
    """
    /sam3/mask/centoroid から静的TFを配信する状態クラス。

    この状態では、深度取得、カメラ投影、点群生成は行わない。
    入力される重心座標は、すでに親フレーム上の3次元位置である必要がある。

    ># object_name    string  子TFフレーム名に使用するオブジェクト名。

    <= done           静的TFの配信に成功した。
    <= failed         重心メッセージが不正だった。
    <= timeout        タイムアウトまでに有効な重心が届かなかった。
    """

    def __init__(self,centroid_topic="/sam3/mask/centoroid",parent_frame_id="base_link",child_frame_prefix="sam3_",child_frame_suffix="_tf",timeout=5.0):
        # 状態クラスを初期化し、FlexBEの結果と入力キーを定義する。
        super(Sam3CentroidToTFState, self).__init__(
            outcomes=["done", "failed", "timeout"],
            input_keys=["object_name"],
        )

        # トピック名、親フレーム名、子フレーム名の接頭辞・接尾辞、タイムアウト時間を保存する。
        self._centroid_topic = centroid_topic
        self._parent_frame_id = parent_frame_id
        self._child_frame_prefix = child_frame_prefix
        self._child_frame_suffix = child_frame_suffix
        self._timeout = float(timeout)

        # 任意のROSメッセージ型として重心トピックを購読する。
        self._centroid_sub = rospy.Subscriber(
            self._centroid_topic, rospy.AnyMsg, self._centroid_callback, queue_size=1
        )

        # 静的TFを配信するためのブロードキャスタを生成する。
        self._tf_broadcaster = tf2_ros.StaticTransformBroadcaster()

        # コールバックと実行処理が同時に変数へアクセスするため、排他制御用ロックを用意する。
        self._lock = threading.Lock()

        # 最新の重心メッセージを保持する。
        self._latest_any_centroid = None

        # 状態が実行中かどうかを表すフラグ。
        self._active = False

        # 状態に入った時刻。
        self._enter_time = None

        # TFをすでに配信したかどうかを表すフラグ。
        self._published = False

        # 子TFフレーム名の生成に使用するオブジェクト名。
        self._object_name = ""

    def on_enter(self, userdata):
        # 状態に入ったときに呼ばれる処理。
        # 実行フラグや時刻、エラー状態を初期化し、userdataからオブジェクト名を取得する。
        self._active = True
        self._enter_time = rospy.Time.now()
        self._published = False
        self._object_name = str(getattr(userdata, "object_name", "")).strip()

        Logger.loginfo(
            "Sam3CentroidToTFState waiting on centroid={} object_name={}".format(
                self._centroid_topic, self._object_name
            )
        )

        # すでに受信済みの重心メッセージがあれば、すぐにTF配信を試みる。
        self._try_publish_latest()

    def execute(self, userdata):
        # 状態の実行中に周期的に呼ばれる処理。

        if self._published:
            return "done"

        self._try_publish_latest()

        if self._timeout > 0.0 and self._enter_time is not None:
            elapsed = (rospy.Time.now() - self._enter_time).to_sec()
            if elapsed > self._timeout:
                Logger.logwarn(
                    "Sam3CentroidToTFState timed out after {:.3f}s".format(elapsed)
                )
                return "timeout"

        return None

    def on_exit(self, userdata):
        # 状態から抜けるときに呼ばれる処理。
        # アクティブ状態を解除する。
        self._active = False

    def on_stop(self):
        # 状態が停止されたときに呼ばれる処理。
        # アクティブ状態を解除する。
        self._active = False

    def on_pause(self):
        # 状態が一時停止されたときに呼ばれる処理。
        # アクティブ状態を解除する。
        self._active = False

    def _centroid_callback(self, msg):
        # 重心トピックを受信したときのコールバック。
        # 最新メッセージを保存し、状態が実行中ならTF配信を試みる。
        with self._lock:
            self._latest_any_centroid = msg
        self._try_publish_latest()

    def _try_publish_latest(self):
        # 最新の重心メッセージから座標を取り出し、静的TFとして配信する。
        # 状態が非アクティブ、ROS終了中、またはすでに配信済みの場合は何もしない。
        if not self._active or rospy.is_shutdown() or self._published:
            return

        with self._lock:
            any_msg = self._latest_any_centroid

        if any_msg is None:
            return

        # AnyMsgを実際のメッセージ型に復元し、xyz座標・親フレーム・時刻を取得する。
        xyz, parent_frame_id, stamp = self._any_centroid_to_xyz(any_msg)

        # object_nameから子フレーム名を生成する。
        child_frame_id = self._build_child_frame_id(self._object_name)

        # TransformStampedを作成して静的TFとして配信する。
        transform = self._build_transform(xyz, parent_frame_id, child_frame_id, stamp)
        self._tf_broadcaster.sendTransform(transform)

        self._published = True

        Logger.loginfo(
            "Sam3CentroidToTFState published static TF {} -> {} at [{:.3f}, {:.3f}, {:.3f}]".format(
                parent_frame_id, child_frame_id, xyz[0], xyz[1], xyz[2]
            )
        )

    def _any_centroid_to_xyz(self, any_msg):
        # rospy.AnyMsgとして受信した重心メッセージを実際の型に復元し、
        # xyz座標、親フレームID、タイムスタンプを返す。
        type_name = any_msg._connection_header.get("type", "")
        msg = self._deserialize_any(any_msg, type_name)

        if isinstance(msg, PointStamped):
            return (
                [float(msg.point.x), float(msg.point.y), float(msg.point.z)],
                self._parent_frame(msg.header.frame_id),
                self._stamp_or_now(msg.header.stamp),
            )

        if isinstance(msg, Vector3Stamped):
            return (
                [float(msg.vector.x), float(msg.vector.y), float(msg.vector.z)],
                self._parent_frame(msg.header.frame_id),
                self._stamp_or_now(msg.header.stamp),
            )

        if isinstance(msg, PoseStamped):
            return (
                [
                    float(msg.pose.position.x),
                    float(msg.pose.position.y),
                    float(msg.pose.position.z),
                ],
                self._parent_frame(msg.header.frame_id),
                self._stamp_or_now(msg.header.stamp),
            )

        if isinstance(msg, Point):
            return (
                [float(msg.x), float(msg.y), float(msg.z)],
                self._parent_frame(""),
                rospy.Time.now(),
            )

        # MultiArrayやString形式の場合はリスト形式のxyzに変換する。
        values = self._message_to_xyz_list(msg)
        if values is None:
            raise ValueError("Unsupported centroid message type: {}".format(type_name))

        return values, self._parent_frame(""), rospy.Time.now()

    @staticmethod
    def _deserialize_any(any_msg, type_name):
        # rospy.AnyMsgを、接続ヘッダに記録されているROSメッセージ型に応じてデシリアライズする。
        msg_class_by_type = {
            "geometry_msgs/PointStamped": PointStamped,
            "geometry_msgs/Point": Point,
            "geometry_msgs/Vector3Stamped": Vector3Stamped,
            "geometry_msgs/PoseStamped": PoseStamped,
            "std_msgs/Float32MultiArray": Float32MultiArray,
            "std_msgs/Float64MultiArray": Float64MultiArray,
            "std_msgs/Int32MultiArray": Int32MultiArray,
            "std_msgs/String": String,
        }

        msg_class = msg_class_by_type.get(type_name)
        if msg_class is None:
            raise ValueError("Unsupported centroid message type: {}".format(type_name))

        msg = msg_class()
        msg.deserialize(any_msg._buff)
        return msg

    @staticmethod
    def _message_to_xyz_list(msg):
        # Float32MultiArray、Float64MultiArray、Int32MultiArray、String形式のメッセージから
        # xyz座標のリストを取り出す。
        if isinstance(msg, (Float32MultiArray, Float64MultiArray, Int32MultiArray)):
            values = [float(v) for v in msg.data]

        elif isinstance(msg, String):
            # Stringの場合はJSON文字列として解釈する。
            # {"x": ..., "y": ..., "z": ...}
            # {"centroid": [x, y, z]}
            # [x, y, z]
            # の形式に対応する。
            payload = json.loads(msg.data)

            if isinstance(payload, dict):
                if all(key in payload for key in ("x", "y", "z")):
                    values = [float(payload[key]) for key in ("x", "y", "z")]
                elif "centroid" in payload:
                    values = [float(v) for v in payload["centroid"]]
                else:
                    return None

            elif isinstance(payload, list):
                values = [float(v) for v in payload]

            else:
                return None

        else:
            return None

        if len(values) < 3:
            raise ValueError("Centroid must contain x, y, z. 2D centroid is not supported.")

        # 4要素以上ある場合でも、先頭3要素のみをxyzとして使用する。
        return values[:3]

    def _parent_frame(self, frame_id):
        # メッセージ内のframe_idが空の場合は、デフォルトの親フレームIDを使用する。
        return str(frame_id or self._parent_frame_id).strip()

    @staticmethod
    def _stamp_or_now(stamp):
        # タイムスタンプが未設定または0の場合は現在時刻を返す。
        # 有効なタイムスタンプがある場合はそのまま返す。
        if stamp is None or stamp == rospy.Time(0):
            return rospy.Time.now()
        return stamp

    def _build_child_frame_id(self, object_name):
        # object_nameからTFの子フレームIDを生成する。
        # 英数字とアンダースコア以外はアンダースコアに置換し、小文字化する。
        name = object_name.strip() or "object"
        name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower() or "object"
        return "{}{}{}".format(self._child_frame_prefix, name, self._child_frame_suffix)

    @staticmethod
    def _build_transform(xyz, parent_frame_id, child_frame_id, stamp):
        # xyz座標、親フレームID、子フレームID、時刻からTransformStampedを作成する。
        # 回転はゼロ回転、つまり単位クォータニオンに設定する。
        q = quaternion_from_euler(0.0, 0.0, 0.0, "rxyz")

        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = parent_frame_id
        transform.child_frame_id = child_frame_id

        transform.transform.translation.x = float(xyz[0])
        transform.transform.translation.y = float(xyz[1])
        transform.transform.translation.z = float(xyz[2])

        transform.transform.rotation.x = q[0]
        transform.transform.rotation.y = q[1]
        transform.transform.rotation.z = q[2]
        transform.transform.rotation.w = q[3]

        return transform