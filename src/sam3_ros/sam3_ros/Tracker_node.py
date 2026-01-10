#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String, Int32MultiArray
import cv2
import numpy as np

class DenseFlowTrackerNode(Node):
    def __init__(self):
        super().__init__('dense_flow_tracker_node')
        
        # --- 設定 ---
        self.target_object = "apple" 
        self.check_interval = 0.5    # 0.5秒ごとにSAM3による補正
        self.iou_threshold = 0.5
        
        # --- 状態管理 ---
        self.tracking_active = False
        self.latest_gray = None # 前フレームのグレー画像
        self.current_bbox = None # (x, y, w, h)
        
        # 遅延補償用
        self.bbox_at_request = None

        # --- 通信 ---
        self.sub_img = self.create_subscription(
            Image, '/camera/camera/color/image_raw', self.image_cb, 1)
        self.pub_sam_req = self.create_publisher(String, '/sam3/request', 1)
        self.sub_sam_bbox = self.create_subscription(
            Int32MultiArray, '/sam3/bbox', self.sam_bbox_cb, 1)
        self.pub_debug = self.create_publisher(Image, '/tracker/debug_image', 1)
        
        self.timer_control = self.create_timer(1.0/30.0, self.control_loop)
        self.timer_supervisor = self.create_timer(self.check_interval, self.supervisor_loop)

        self.get_logger().info('Dense Flow Tracker Ready. Waiting for SAM3...')

    def image_cb(self, msg):
        try:
            img = self.imgmsg_to_cv2(msg)
            # オプティカルフロー用にグレースケール変換
            self.current_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            self.latest_bgr = img
        except Exception as e:
            self.get_logger().error(f'Image error: {e}')

    def imgmsg_to_cv2(self, msg):
        dtype = np.uint8
        if '16UC1' in msg.encoding: dtype = np.uint16
        img = np.frombuffer(msg.data, dtype=dtype)
        if dtype == np.uint8:
            img = img.reshape((msg.height, msg.width, 3))
        else:
            img = img.reshape((msg.height, msg.width))
        return img

    def supervisor_loop(self):
        if self.tracking_active and self.current_bbox is not None:
            self.bbox_at_request = self.current_bbox
        else:
            self.bbox_at_request = None
        
        msg = String()
        msg.data = self.target_object
        self.pub_sam_req.publish(msg)

    def sam_bbox_cb(self, msg):
        data = msg.data
        if len(data) < 4 or data[0] == -1: return

        sam_bbox_past = (data[0], data[1], data[2], data[3])
        
        if not self.tracking_active:
            self.start_tracking(sam_bbox_past)
            return

        target_bbox = self.bbox_at_request if self.bbox_at_request else self.current_bbox
        score = self.calculate_iou(target_bbox, sam_bbox_past)
        
        # ズレていたら補正
        if score < self.iou_threshold:
            if self.bbox_at_request:
                dx = sam_bbox_past[0] - self.bbox_at_request[0]
                dy = sam_bbox_past[1] - self.bbox_at_request[1]
                # DenseFlowはサイズ変更に弱いので、SAM3のサイズを正とする
                new_w = sam_bbox_past[2] 
                new_h = sam_bbox_past[3]
                
                new_x = self.current_bbox[0] + dx
                new_y = self.current_bbox[1] + dy
                
                new_bbox = (int(new_x), int(new_y), int(new_w), int(new_h))
                self.get_logger().warn(f'Dense Drift! (IoU={score:.2f}). Compensating.')
                self.start_tracking(new_bbox)
            else:
                self.start_tracking(sam_bbox_past)

    def start_tracking(self, bbox):
        if self.latest_gray is None: return
        self.current_bbox = bbox
        self.tracking_active = True
        # フロー計算の基準となる「前フレーム」を保存
        self.prev_gray = self.latest_gray.copy()
        self.get_logger().info(f'Dense Tracker Initialized at {bbox}')

    def control_loop(self):
        if not self.tracking_active or self.latest_gray is None: return
        
        # 1. 処理範囲（ROI）を切り出し
        # 全画面でフロー計算すると重いので、現在のBBox周辺だけ計算する
        x, y, w, h = self.current_bbox
        margin = 20
        h_img, w_img = self.latest_gray.shape
        
        x1 = max(0, x - margin)
        y1 = max(0, y - margin)
        x2 = min(w_img, x + w + margin)
        y2 = min(h_img, y + h + margin)
        
        prev_roi = self.prev_gray[y1:y2, x1:x2]
        curr_roi = self.latest_gray[y1:y2, x1:x2]
        
        if prev_roi.shape != curr_roi.shape or prev_roi.size == 0:
            self.prev_gray = self.latest_gray.copy()
            return

        # 2. Dense Optical Flow (Farneback法)
        # flow は (height, width, 2) の配列。各画素の dx, dy が入る
        flow = cv2.calcOpticalFlowFarneback(
            prev_roi, curr_roi, None, 
            pyr_scale=0.5, levels=3, winsize=15, 
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0
        )
        
        # 3. 物体領域のみの移動量を抽出
        # BBoxの中心部分の動きを信頼する（背景の動きを除外するため）
        # ROI座標系でのBBoxの位置
        bx = x - x1
        by = y - y1
        
        # BBox内部のフローを切り出し
        obj_flow = flow[by:by+h, bx:bx+w]
        
        # 移動量の代表値を計算（平均だとノイズに弱いので中央値を使う）
        dx = np.median(obj_flow[..., 0])
        dy = np.median(obj_flow[..., 1])
        
        # 4. 位置更新
        # NaNチェック
        if np.isnan(dx) or np.isnan(dy): dx, dy = 0, 0
        
        new_x = x + dx
        new_y = y + dy
        
        self.current_bbox = (int(new_x), int(new_y), w, h)
        
        # 次のループのために画像を保存
        self.prev_gray = self.latest_gray.copy()

        # --- 描画 ---
        debug_img = self.latest_bgr.copy()
        p1 = (int(new_x), int(new_y))
        p2 = (int(new_x + w), int(new_y + h))
        cv2.rectangle(debug_img, p1, p2, (255, 0, 0), 2, 1) # 青枠
        
        # 中心
        cx = int(new_x + w/2)
        cy = int(new_y + h/2)
        cv2.drawMarker(debug_img, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
        
        cv2.putText(debug_img, "Dense Flow (Farneback)", (p1[0], p1[1]-10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

        # Publish
        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.height = debug_img.shape[0]
        msg.width = debug_img.shape[1]
        msg.encoding = 'bgr8'
        msg.step = debug_img.shape[1] * 3
        msg.data = debug_img.tobytes()
        self.pub_debug.publish(msg)

    def calculate_iou(self, boxA, boxB):
        if boxA is None or boxB is None: return 0.0
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
        yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])
        interArea = max(0, xB - xA) * max(0, yB - yA)
        boxAArea = boxA[2] * boxA[3]
        boxBArea = boxB[2] * boxB[3]
        denominator = float(boxAArea + boxBArea - interArea)
        if denominator == 0: return 0.0
        return interArea / denominator

def main():
    rclpy.init()
    node = DenseFlowTrackerNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()