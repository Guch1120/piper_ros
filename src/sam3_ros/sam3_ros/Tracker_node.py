#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import Image
from geometry_msgs.msg import Point
from std_msgs.msg import String
import cv2
import numpy as np
import torch
import os
import pathlib
from collections import deque
import threading # 非同期処理用

try:
    from sam3_ros.test_sam3_online_tracker import Sam3OnlineTracker
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from test_sam3_online_tracker import Sam3OnlineTracker

class Sam3HybridTracker(Node):
    def __init__(self):
        super().__init__('sam3_hybrid_tracker')
        
        # --- 設定 ---
        # 監視間隔: 2.0秒ごとに過去の履歴とSAM3の結果を照合する
        self.VERIFY_INTERVAL_SEC = 2.0 
        # IoU閾値: 0.3を下回ったら「追跡がズレている」と判断する
        self.IOU_THRESHOLD = 0.3
        # 色変化の許容度 (0.0:完全一致 ~ 1.0:不一致)
        self.COLOR_DISTANCE_THRESHOLD = 0.7 
        
        # 履歴バッファ: 過去のDaSiamRPNの位置を保存 (非同期検証用)
        self.tracker_history = deque(maxlen=60)

        # --- SAM3 (Brain: 初期化・監視用) ---
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        home = pathlib.Path.home()
        ckpt_path = home / ".cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt"
        
        self.get_logger().info("Loading SAM3 (Brain)...")
        # 検証用なのでメモリは極小(8フレーム)でOK。FP32+Autocast構成
        self.sam3 = Sam3OnlineTracker(device=self.device, checkpoint_path=str(ckpt_path), max_frames=8)
        self.get_logger().info("SAM3 Ready.")

        # --- DaSiamRPN (Runner: 高速追跡用) ---
        self.tracker = None
        self.tracker_name = "DaSiamRPN"
        model_dir = home / ".ros/dasiamrpn"
        self.dasiam_model = str(model_dir / "dasiamrpn_model.onnx")
        self.dasiam_kernel_r1 = str(model_dir / "dasiamrpn_kernel_r1.onnx")
        self.dasiam_kernel_cls1 = str(model_dir / "dasiamrpn_kernel_cls1.onnx")
        
        # モデルファイルの存在確認
        if not os.path.exists(self.dasiam_model):
            self.get_logger().warn("DaSiamRPN not found. Fallback to CSRT.")
            self.tracker_name = "CSRT"
        else:
            self.get_logger().info("DaSiamRPN models found.")

        # --- 状態変数 ---
        self.latest_cv_image = None
        self.tracking_active = False
        self.target_prompt = None
        self.missed_frames = 0
        self.last_sam3_init_time = Time(seconds=0)
        
        # 色ヒストグラム管理用
        self.target_hist = None 
        
        # 排他制御・非同期管理用
        self.is_verifying = False
        self.lock = threading.Lock()

        # --- 通信インタフェース ---
        self.sub_img = self.create_subscription(
            Image, '/camera/camera/color/image_raw', self.image_cb, 1)
        
        # 追跡開始指示を受け取るトピック
        self.sub_start = self.create_subscription(
            String, '/sam3/start_track', self.start_text_cb, 1)
        
        self.pub_debug = self.create_publisher(Image, '/sam3/track_debug', 1)
        self.pub_result = self.create_publisher(Point, '/sam3/track_result', 1)
        
        # 定期監視用タイマー (非同期スレッドを起動するトリガー)
        self.verify_timer = self.create_timer(self.VERIFY_INTERVAL_SEC, self.verify_tracking_timer_cb)

    def _create_tracker(self):
        """OpenCVのトラッカーインスタンスを生成する"""
        if self.tracker_name == "DaSiamRPN":
            params = cv2.TrackerDaSiamRPN_Params()
            params.model = self.dasiam_model
            params.kernel_cls1 = self.dasiam_kernel_cls1
            params.kernel_r1 = self.dasiam_kernel_r1
            return cv2.TrackerDaSiamRPN_create(params)
        else:
            return cv2.TrackerCSRT_create()

    def start_text_cb(self, msg):
        """指示用コールバック: 新しいターゲットを設定"""
        target = msg.data
        self.get_logger().info(f"New Target: {target}")
        self.target_prompt = target
        
        # 追跡をリセットして、即座に再検索(フェーズB)に入るようにする
        with self.lock:
            self.tracking_active = False
            self.tracker = None
            self.tracker_history.clear()
            self.target_hist = None # 色ヒストグラムもリセット

    def image_cb(self, msg):
        """メインの画像処理ループ (約30fps)"""
        current_time = self.get_clock().now()
        
        img_np = np.frombuffer(msg.data, dtype=np.uint8).reshape((msg.height, msg.width, 3))
        if 'rgb' in msg.encoding:
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        else:
            img_bgr = img_np
            
        with self.lock:
            self.latest_cv_image = img_bgr
            
        debug_img = img_bgr.copy()
        detected = False
        center_x, center_y = 0.0, 0.0

        # === フェーズA: 高速追跡 (DaSiamRPN/CSRT) ===
        if self.tracking_active and self.tracker is not None:
            # メインスレッドで実行 (DaSiamRPNは高速なのでOK)
            success, box = self.tracker.update(img_bgr)
            
            if success:
                # 履歴に保存 (時刻, BBox)
                with self.lock:
                    self.tracker_history.append((current_time, box))
                
                x, y, w, h = [int(v) for v in box]
                
                # 色チェック (参考情報として表示)
                color_dist = self._check_color_histogram(img_bgr, (x, y, w, h))
                status_color = (0, 255, 0)
                if color_dist > self.COLOR_DISTANCE_THRESHOLD:
                    status_color = (0, 165, 255) # オレンジ (警告色)

                cv2.rectangle(debug_img, (x, y), (x+w, y+h), status_color, 2)
                cv2.putText(debug_img, f"{self.tracker_name}: {color_dist:.2f}", (x, y-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)
                
                center_x = x + w/2.0
                center_y = y + h/2.0
                detected = True
                self.missed_frames = 0
            else:
                # トラッカーが見失った場合
                self.missed_frames += 1
                if self.missed_frames > 3:
                    self.get_logger().warn("Tracker lost! Requesting recovery...")
                    self.tracking_active = False
                    self.tracker = None
                    with self.lock:
                        self.tracker_history.clear()

        # === フェーズB: リカバリー (ロスト時のみSAM3起動) ===
        if not self.tracking_active and self.target_prompt is not None:
            # 検証スレッドが走っていない時だけ実行
            if not self.is_verifying:
                self._run_sam3_init(img_bgr, debug_img)
                if self.tracking_active:
                    detected = True

        # === 結果のPublish ===
        if detected:
            self.pub_result.publish(Point(x=center_x, y=center_y, z=0.0))
            cv2.drawMarker(debug_img, (int(center_x), int(center_y)), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
        elif self.target_prompt:
            status = "Verifying..." if self.is_verifying else f"Searching: {self.target_prompt}..."
            cv2.putText(debug_img, status, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        msg = Image()
        msg.header.stamp = current_time.to_msg()
        msg.height = debug_img.shape[0]
        msg.width = debug_img.shape[1]
        msg.encoding = 'bgr8'
        msg.step = debug_img.shape[1] * 3
        msg.data = debug_img.tobytes()
        self.pub_debug.publish(msg)

    def _run_sam3_init(self, img_bgr, debug_img=None):
        """SAM3を実行してトラッカーを初期化するヘルパー関数"""
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        masks = self.sam3.init_track(img_rgb, text_prompt=self.target_prompt)
        
        if masks and len(masks) > 0 and np.sum(masks[0]) > 0:
            contours, _ = cv2.findContours(masks[0], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if len(contours) > 0:
                largest = max(contours, key=cv2.contourArea)
                bx, by, bw, bh = cv2.boundingRect(largest)
                
                self.tracker = self._create_tracker()
                self.tracker.init(img_bgr, (bx, by, bw, bh))
                self.tracking_active = True
                
                with self.lock:
                    self.tracker_history.clear()
                
                self.last_sam3_init_time = self.get_clock().now()
                self.get_logger().info(f"SAM3 initialized at ({bx},{by})")

                # 色ヒストグラムの基準を作成 (初期化時の色が正解)
                self._update_target_histogram(img_bgr, (bx, by, bw, bh))

                if debug_img is not None:
                     cv2.rectangle(debug_img, (bx, by), (bx+bw, by+bh), (255, 0, 0), 2)
                return True
        return False

    # --- 色チェック用関数 ---
    def _update_target_histogram(self, img, bbox):
        x, y, w, h = [int(v) for v in bbox]
        if w <= 0 or h <= 0: return
        roi = img[y:y+h, x:x+w]
        if roi.size == 0: return
        
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # 色相(Hue)と彩度(Saturation)だけでヒストグラムを作る
        hist = cv2.calcHist([hsv], [0, 1], None, [180, 256], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        self.target_hist = hist

    def _check_color_histogram(self, img, bbox):
        if self.target_hist is None: return 0.0
        x, y, w, h = [int(v) for v in bbox]
        if x < 0 or y < 0 or x+w > img.shape[1] or y+h > img.shape[0] or w<=0 or h<=0:
            return 1.0
            
        roi = img[y:y+h, x:x+w]
        if roi.size == 0: return 1.0
        
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        curr_hist = cv2.calcHist([hsv], [0, 1], None, [180, 256], [0, 180, 0, 256])
        cv2.normalize(curr_hist, curr_hist, 0, 1, cv2.NORM_MINMAX)
        
        # Bhattacharyya距離 (0:一致, 1:不一致)
        return cv2.compareHist(self.target_hist, curr_hist, cv2.HISTCMP_BHATTACHARYYA)

    # --- 非同期検証用ロジック ---
    def verify_tracking_timer_cb(self):
        """タイマーから呼ばれる。スレッドを起動するだけ"""
        if not self.tracking_active or self.is_verifying:
            return

        if (self.get_clock().now() - self.last_sam3_init_time).nanoseconds / 1e9 < self.VERIFY_INTERVAL_SEC:
            return
            
        # 画像をコピーしてスレッドに渡す
        with self.lock:
            if self.latest_cv_image is None: return
            verify_img = self.latest_cv_image.copy()
            verify_time = self.get_clock().now()
        
        # スレッド起動
        thread = threading.Thread(target=self._worker_verify, args=(verify_img, verify_time))
        thread.start()

    def _worker_verify(self, img_bgr, verify_time):
        """別スレッドで走る重い処理 (SAM3推論 + 履歴照合)"""
        self.is_verifying = True
        try:
            # SAM3推論
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            masks = self.sam3.init_track(img_rgb, text_prompt=self.target_prompt)
            
            sam3_box = None
            if masks and len(masks) > 0 and np.sum(masks[0]) > 0:
                contours, _ = cv2.findContours(masks[0], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if len(contours) > 0:
                    sam3_box = cv2.boundingRect(max(contours, key=cv2.contourArea))
            
            if sam3_box is None:
                # SAM3が見失った -> トラッキング中止
                self.tracking_active = False
                return

            # 履歴照合 (Time-Aligned Verification)
            closest_box = None
            min_time_diff = 1.0
            
            with self.lock:
                history_copy = list(self.tracker_history)
                
            for t, box in reversed(history_copy):
                diff = abs((t - verify_time).nanoseconds / 1e9)
                if diff < min_time_diff:
                    min_time_diff = diff
                    closest_box = box
            
            if closest_box is not None:
                iou = self.calculate_iou(closest_box, sam3_box)
                if iou < self.IOU_THRESHOLD:
                    self.get_logger().warn(f"Drift Detected! (Past IoU={iou:.2f}). Resetting.")
                    self.tracking_active = False # リセット
                    with self.lock:
                        self.tracker_history.clear()
                else:
                    # self.get_logger().info(f"Verification OK. IoU={iou:.2f}")
                    pass
                    
        finally:
            self.is_verifying = False

    def calculate_iou(self, boxA, boxB):
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
        yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])
        interArea = max(0, xB - xA) * max(0, yB - yA)
        boxAArea = boxA[2] * boxA[3]
        boxBArea = boxB[2] * boxB[3]
        denom = float(boxAArea + boxBArea - interArea)
        if denom <= 0: return 0.0
        return interArea / denom

def main():
    rclpy.init()
    node = Sam3HybridTracker()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()