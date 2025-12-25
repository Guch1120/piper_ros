#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import Point
from cv_bridge import CvBridge
import numpy as np
import torch
from PIL import Image as PILImage
import sam3
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.visualization_utils import plot_results
import os
from datetime import datetime
import matplotlib.pyplot as plt


class SegmentWithDepthPub(Node):
    
    """
    RealsenseのRGB-D画像を受け取り,
    SAM3で指定オブジェクトをセグメンテーションし,
    セグメント領域の重心座標(u, v)と深度値(z)を1回だけパブリッシュするノード.
    input_textで指定したオブジェクトを検出する(例: "bottle", "cup", "book" など)
    結果は/asets/saved_framesに保存される.
    
    物体追跡やTF発行はこのノードでできていない.
    """
    
    def __init__(self):
        super().__init__('segment_with_depth_pub_node')
        self.bridge = CvBridge()
        self.frame_processed = False

        # 保存パスを指定
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_dir = os.path.join(script_dir, '..', 'assets', 'saved_frames')
        # ディレクトリが存在しない場合は作成
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # 座標値(u, v, z)を配信するパブリッシャーを作成する,x=u(pixel), y=v(pixel), z=depth(meter) として扱う
        # オブジェクトを指定していないときはトピック名を`target_object_uvz`にする
        self.coord_pub = self.create_publisher(Point, '/object_uvz', 10)

        # RGB画像のサブスクライバー
        self.rgb_sub = self.create_subscription(
            Image,
            '/camera/camera/color/image_raw',
            self.rgb_callback,
            10
        )
        # Depth画像のサブスクライバー (RGBにアライメントされたDepthを使用する)
        self.depth_sub = self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self.depth_callback,
            10
        )
        
        # 画像を一時保持する変数
        self.latest_rgb = None
        self.latest_depth = None
        # SAM3のセットアップ
        self.model, self.processor, self.device = self.setup_sam3()


    def setup_sam3(self):
        # デバイスの決定
        if torch.cuda.is_available():
            device = "cuda"
            self.get_logger().info("Using CUDA")
        else:
            device = "cpu"
            self.get_logger().info("Using CPU")

        # BPEファイルのパス設定
        current_dir = os.path.dirname(os.path.abspath(__file__))
        bpe_path = os.path.join(current_dir, "assets", "bpe_simple_vocab_16e6.txt.gz")
        if not os.path.exists(bpe_path):
            sam3_root = os.path.dirname(sam3.__file__)
            bpe_path = os.path.join(sam3_root, "..", "assets", "bpe_simple_vocab_16e6.txt.gz")
        self.get_logger().info(f"Loading SAM3 with BPE : {bpe_path}")
        model = build_sam3_image_model(bpe_path=bpe_path, device=device)
        if device == "cpu":
            model = model.to("cpu")
        processor = Sam3Processor(model, confidence_threshold=0.5, device=device)
        return model, processor, device

    # OpenCVで扱える画像に変換
    def rgb_callback(self, msg):
        if self.frame_processed:
            return
        try:
            # ROS Image -> OpenCV image (numpy array)
            self.latest_rgb = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
            self.try_process_frame()
        except Exception as e:
            self.get_logger().error(f"RGB callback error : {e}")
            
    def depth_callback(self, msg):
        if self.frame_processed:
            return
        try:
            # Depth画像は通常 16UC1 (uint16) でmm単位である
            self.latest_depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
            self.try_process_frame()
        except Exception as e:
            self.get_logger().error(f"Depth callback error : {e}")


    def try_process_frame(self):
        # RGBとDepthの両方が揃ったら処理を開始する
        if self.latest_rgb is not None and self.latest_depth is not None:
            self.process_frame(self.latest_rgb, self.latest_depth)
            self.frame_processed = True
            rclpy.shutdown()

    # フレーム処理を実行
    def process_frame(self, rgb_image, depth_image):
        timestamp = datetime.now().strftime('%Y_%m%d_%H_%M_%S')
        self.get_logger().info("Starting SAM3 segmentation and depth calculation...")

        # SAM3用にPIL画像へ変換
        image_pil = PILImage.fromarray(rgb_image)
        
        # 推論を実行
        inference_state = self.processor.set_image(image_pil)
        
#==========================================#
#       検出したいオブジェクトを指定
#==========================================#
        input_text = "object"
#==========================================#
#==========================================#
        self.get_logger().info(f"SAM3 text prompt : {input_text}")
        results = self.processor.set_text_prompt(input_text, inference_state)

        # マスクが見つからなかった場合の処理を行う
        if len(results['masks']) == 0:
            self.get_logger().warn("Object not found by SAM3.")
            return

        # SAM3の出力形式に合わせて次元を調整. 最初のマスクを取得 (Tensor -> Numpy, Shape: [H, W])
        mask_tensor = results['masks'][0]
        mask = mask_tensor.squeeze().cpu().numpy().astype(bool)

        # 重心座標 (u, v) の計算. マスクがTrueのインデックスを取得
        indices = np.argwhere(mask)
        center_u = 0.0
        center_v = 0.0
        
        if len(indices) > 0:
            # indices は [y, x] の順で格納されているため, xがu, yがvに対応させる
            y_indices = indices[:, 0]
            x_indices = indices[:, 1]
            
            # 重心を平均値として計算
            center_v = np.mean(y_indices)
            center_u = np.mean(x_indices)
            
            self.get_logger().info(f"Found Mask Center (u, v) : ({center_u:.2f}, {center_v:.2f})")
        else:
            self.get_logger().warn("Mask is empty, cannot calculate center.")

        # Depth画像をNumpy配列として扱う
        depth_np = depth_image
        if torch.is_tensor(depth_image):
            depth_np = depth_image.cpu().numpy()
        # Depth画像の次元を確認して調整 (H, W) にする
        if depth_np.ndim == 3:
            depth_np = np.squeeze(depth_np)

        # マスク領域のDepth値のみを抽出
        # maskがTrueの場所にあるdepth_npの値を取得
        # depthは近すぎると取れないので, 20cm以上遠ざけると良い
        masked_depth = depth_np[mask]

        if masked_depth.size == 0:
            self.get_logger().warn("No depth pixels found in the masked area.")
        else:
            # 中央値 (Median) を計算
            median_depth = np.median(masked_depth)
            
            # RealSenseのDepthは通常mm単位 (uint16) である
            if depth_np.dtype == np.uint16:
                median_depth_m = median_depth / 1000.0
                unit_str = "(converted from mm)"
            else:
                median_depth_m = median_depth
                unit_str = "(original unit)"

            self.get_logger().info(f"Median Depth : {median_depth_m:.3f} m {unit_str}")
            
            # TF発行用の情報をログに出力
            self.get_logger().info("--- Data for TF ---")
            self.get_logger().info(f"u (x) : {center_u:.2f}")
            self.get_logger().info(f"v (y) : {center_v:.2f}")
            self.get_logger().info(f"z (depth) : {median_depth_m:.3f} m")
            self.get_logger().info("-------------------")

            # 座標データのPublish
            point_msg = Point()
            point_msg.x = float(center_u)
            point_msg.y = float(center_v)
            point_msg.z = float(median_depth_m)
            self.coord_pub.publish(point_msg)
            self.get_logger().info("Published coordinates to /object_uvz")

        # 結果画像の保存
        result_path = os.path.join(self.output_dir, f"segmented_{timestamp}.png")
        plot_results(image_pil, results)
        plt.savefig(result_path)
        plt.close()
        self.get_logger().info(f"Segmented image saved : {result_path}")
        self.get_logger().info("Processing complete, please press Ctrl+C to exit.")


def main(args=None):
    rclpy.init(args=args)
    node = SegmentWithDepthPub()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()

if __name__ == '__main__':
    main()