#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import re

import numpy as np
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxySubscriberCached
from geometry_msgs.msg import PointStamped, TransformStamped
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import StaticTransformBroadcaster


class Sam3CentorPointToTF(EventState):
    """
    /sam3/mask/centroid から画像座標の PointStamped を受け取り、depth画像とCameraInfoからカメラ座標へ変換して静的TFを配信する State。

    ># object_name    string  子TFフレーム名に使用するオブジェクト名

    <= done           静的TFの配信に成功
    <= failed         重心メッセージ、depth、CameraInfo が不正
    <= timeout        タイムアウトまでに有効な重心が届かなかった
    """

    def __init__(self,centroid_topic="/sam3/mask/centroid",depth_topic="/camera/camera/aligned_depth_to_color/image_raw",camera_info_topic="/camera/camera/color/camera_info",parent_frame_id="camera_color_optical_frame",child_frame_prefix="sam3_",child_frame_suffix="_tf",timeout=5.0,depth_search_radius=3):
        super(Sam3CentorPointToTF, self).__init__(outcomes=["done", "failed", "timeout"],input_keys=["object_name"])
        self._centroid_topic = centroid_topic
        self._depth_topic = depth_topic
        self._camera_info_topic = camera_info_topic
        self._parent_frame_id = parent_frame_id
        self._child_frame_prefix = child_frame_prefix
        self._child_frame_suffix = child_frame_suffix
        self._timeout_sec = float(timeout)
        self._timeout_ns = int(self._timeout_sec * 1e9)
        self._depth_search_radius = int(depth_search_radius)
        self._enter_time = None
        self._published = False
        self._object_name = ""
        self._sub = ProxySubscriberCached({self._centroid_topic: PointStamped,self._depth_topic: Image,self._camera_info_topic: CameraInfo})

        # ROS2のStaticTransformBroadcasterはnodeを渡す
        self._tf_broadcaster = StaticTransformBroadcaster(self._node)

    def on_enter(self, userdata):
        self._enter_time = self._node.get_clock().now()
        self._published = False
        self._object_name = str(getattr(userdata, "object_name", "")).strip()

        # 前回の古い重心メッセージを使いたくないので消す
        if self._sub.has_msg(self._centroid_topic):
            self._sub.remove_last_msg(self._centroid_topic)
        Logger.loginfo("Sam3CentorPointToTF waiting on centroid={} depth={} camera_info={} object_name={}".format(self._centroid_topic,self._depth_topic,self._camera_info_topic,self._object_name))

    def execute(self, userdata):
        if self._published:
            return "done"

        if self._sub.has_msg(self._centroid_topic):
            if not self._sub.has_msg(self._depth_topic):
                Logger.logwarn("Sam3CentorPointToTF waiting depth image: {}".format(self._depth_topic))
                return None

            if not self._sub.has_msg(self._camera_info_topic):
                Logger.logwarn("Sam3CentorPointToTF waiting camera info: {}".format(self._camera_info_topic))
                return None

            centroid_msg = self._sub.get_last_msg(self._centroid_topic)
            depth_msg = self._sub.get_last_msg(self._depth_topic)
            camera_info_msg = self._sub.get_last_msg(self._camera_info_topic)
            self._sub.remove_last_msg(self._centroid_topic)

            try:
                self._publish_tf_from_image_point(centroid_msg,depth_msg,camera_info_msg)
                self._published = True
                return "done"

            except Exception as e:
                Logger.logerr("Sam3CentorPointToTF failed to publish TF: {}".format(e))
                return "failed"

        if self._timeout_sec > 0.0 and self._enter_time is not None:
            now = self._node.get_clock().now()
            elapsed_ns = now.nanoseconds - self._enter_time.nanoseconds

            if elapsed_ns > self._timeout_ns:
                Logger.logwarn("Sam3CentorPointToTF timed out after {:.3f}s".format(elapsed_ns * 1e-9))
                return "timeout"

        return None

    def _publish_tf_from_image_point(self, centroid_msg, depth_msg, camera_info_msg):
        u = int(round(float(centroid_msg.point.x)))
        v = int(round(float(centroid_msg.point.y)))

        if u < 0 or v < 0 or u >= int(depth_msg.width) or v >= int(depth_msg.height):
            raise ValueError("centroid pixel is out of depth image range. u={} v={} width={} height={}".format(u,v,depth_msg.width,depth_msg.height))

        fx = float(camera_info_msg.k[0])
        fy = float(camera_info_msg.k[4])
        cx = float(camera_info_msg.k[2])
        cy = float(camera_info_msg.k[5])

        if fx == 0.0 or fy == 0.0:
            raise ValueError("invalid CameraInfo. fx={} fy={}".format(fx,fy))

        depth_m = self._read_valid_depth_m(depth_msg,u,v)

        if depth_m is None:
            raise ValueError("valid depth was not found around centroid. u={} v={} radius={}".format(u,v,self._depth_search_radius))

        x = (float(u) - cx) * depth_m / fx
        y = (float(v) - cy) * depth_m / fy
        z = depth_m

        parent_frame_id = str(camera_info_msg.header.frame_id).strip()
        if not parent_frame_id:
            parent_frame_id = str(depth_msg.header.frame_id).strip()
        if not parent_frame_id:
            parent_frame_id = str(centroid_msg.header.frame_id).strip()
        if not parent_frame_id:
            parent_frame_id = self._parent_frame_id

        child_frame_id = self._build_child_frame_id(self._object_name)
        transform = TransformStamped()

        # stampが未設定なら現在時刻を使う
        if depth_msg.header.stamp.sec == 0 and depth_msg.header.stamp.nanosec == 0:
            transform.header.stamp = self._node.get_clock().now().to_msg()
        else:
            transform.header.stamp = depth_msg.header.stamp

        transform.header.frame_id = parent_frame_id
        transform.child_frame_id = child_frame_id
        transform.transform.translation.x = float(x)
        transform.transform.translation.y = float(y)
        transform.transform.translation.z = float(z)
        # 回転なし。単位クォータニオン。
        transform.transform.rotation.x = 0.0
        transform.transform.rotation.y = 0.0
        transform.transform.rotation.z = 0.0
        transform.transform.rotation.w = 1.0
        self._tf_broadcaster.sendTransform(transform)
        Logger.loginfo("Sam3CentorPointToTF published static TF {} -> {} from pixel [{}, {}] depth={:.3f}m camera_xyz=[{:.3f}, {:.3f}, {:.3f}]".format(parent_frame_id,child_frame_id,u,v,depth_m,x,y,z))

    def _read_valid_depth_m(self, depth_msg, u, v):
        depth_m = self._read_depth_m(depth_msg,u,v)

        if self._is_valid_depth(depth_m):
            return depth_m

        for radius in range(1,self._depth_search_radius + 1):
            best_depth = None
            best_dist2 = None

            for yy in range(max(0,v - radius),min(int(depth_msg.height),v + radius + 1)):
                for xx in range(max(0,u - radius),min(int(depth_msg.width),u + radius + 1)):
                    depth_m = self._read_depth_m(depth_msg,xx,yy)
                    if not self._is_valid_depth(depth_m):
                        continue
                    dist2 = (xx - u) * (xx - u) + (yy - v) * (yy - v)

                    if best_dist2 is None or dist2 < best_dist2:
                        best_dist2 = dist2
                        best_depth = depth_m

            if best_depth is not None:
                Logger.logwarn("Sam3CentorPointToTF used nearby depth. center=[{}, {}] radius={} depth={:.3f}m".format(u,v,radius,best_depth))
                return best_depth

        return None

    def _read_depth_m(self, depth_msg, u, v):
        encoding = str(depth_msg.encoding)

        if encoding in ["16UC1", "mono16"]:
            dtype = np.dtype(np.uint16)
            scale = 0.001
        elif encoding == "32FC1":
            dtype = np.dtype(np.float32)
            scale = 1.0
        elif encoding == "64FC1":
            dtype = np.dtype(np.float64)
            scale = 1.0
        else:
            raise ValueError("unsupported depth image encoding: {}".format(encoding))

        if int(depth_msg.is_bigendian) != 0:
            dtype = dtype.newbyteorder(">")
        else:
            dtype = dtype.newbyteorder("<")

        item_size = dtype.itemsize
        values_per_row = int(depth_msg.step) // item_size

        if u >= values_per_row:
            raise ValueError("u is out of row step range. u={} values_per_row={} step={} encoding={}".format(u,values_per_row,depth_msg.step,encoding))
        depth_array = np.frombuffer(depth_msg.data,dtype=dtype)

        if depth_array.size < int(depth_msg.height) * values_per_row:
            raise ValueError("depth data size is too small. size={} required={}".format(depth_array.size,int(depth_msg.height) * values_per_row))
        raw_depth = depth_array[v * values_per_row + u]

        return float(raw_depth) * scale

    @staticmethod
    def _is_valid_depth(depth_m):
        if depth_m is None:
            return False
        if not math.isfinite(float(depth_m)):
            return False
        if float(depth_m) <= 0.0:
            return False
        return True

    def _build_child_frame_id(self, object_name):
        name = object_name.strip() or "object"
        name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower() or "object"
        return "{}{}{}".format(self._child_frame_prefix,name,self._child_frame_suffix)