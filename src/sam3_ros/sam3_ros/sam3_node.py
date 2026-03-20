#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import Point, PoseArray, Pose
from std_msgs.msg import String
from cv_bridge import CvBridge
import numpy as np
import torch
from PIL import Image as PILImage
import sam3
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.visualization_utils import plot_results
import os
import matplotlib.pyplot as plt


class Sam3ServiceNode(Node):
    def __init__(self):
        super().__init__('sam3_node')
        self.bridge = CvBridge()

        self.latest_rgb_msg = None
        self.latest_depth_msg = None

        # ---- Subscribers ----
        self.create_subscription(
            Image,
            '/camera/camera/color/image_raw',
            self.rgb_cb,
            1
        )
        self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self.depth_cb,
            1
        )
        self.create_subscription(
            String,
            '/sam3/request',
            self.request_cb,
            1
        )

        # ---- Publishers ----
        # 互換性維持: 重心1点 (x=u, y=v, z=depth)
        self.pub_result = self.create_publisher(Point, '/sam3/result', 1)
        
        # 新規: 重心周辺の複数点 (PoseArrayを使用するが、中身は u, v, depth のリスト)
        # 受取側のノードで position.x を u, position.y を v として扱ってください。
        self.pub_result_points = self.create_publisher(PoseArray, '/sam3/result_points', 1)
        
        self.pub_debug = self.create_publisher(Image, '/sam3/debug_image', 1)

        self.get_logger().info('Loading SAM3 model...')
        self.model, self.processor = self._setup_sam3()
        self.get_logger().info('SAM3 ready.')

        # サンプリング設定: 重心周辺の探索サイズ (片側ピクセル数)
        # 例: 10の場合、重心を中心に 21x21 (±10) の領域を探索
        self.sampling_kernel_radius = 10

    def _setup_sam3(self):
        device = "cuda" if torch.cuda.is_available() else "cpu"

        sam3_root = os.path.dirname(sam3.__file__)
        bpe_path = os.path.join(
            sam3_root, "..", "assets",
            "bpe_simple_vocab_16e6.txt.gz"
        )

        model = build_sam3_image_model(
            bpe_path=bpe_path,
            device=device
        )
        processor = Sam3Processor(
            model,
            confidence_threshold=0.5,
            device=device
        )
        return model, processor

    def rgb_cb(self, msg):
        self.latest_rgb_msg = msg

    def depth_cb(self, msg):
        self.latest_depth_msg = msg

    def request_cb(self, msg):
        target = msg.data
        self.get_logger().info(f'Request: {target}')

        if self.latest_rgb_msg is None or self.latest_depth_msg is None:
            self.get_logger().warn('No image received yet.')
            return

        try:
            rgb = self.bridge.imgmsg_to_cv2(
                self.latest_rgb_msg,
                desired_encoding='rgb8'
            )
            # Depth画像取得 (単位はセンサ依存、通常mm)
            depth = self.bridge.imgmsg_to_cv2(
                self.latest_depth_msg,
                desired_encoding='passthrough'
            )

            # ===== SAM3 推論 =====
            image_pil = PILImage.fromarray(rgb)
            state = self.processor.set_image(image_pil)
            results = self.processor.set_text_prompt(target, state)

            # ===== 検出なし =====
            if len(results['masks']) == 0:
                self.get_logger().info('Nothing detected.')
                # 失敗時は (0,0,-1) を投げる運用
                fail_res = Point(x=0.0, y=0.0, z=-1.0)
                self.pub_result.publish(fail_res)
                return

            # ===== マスク取得 =====
            mask = results['masks'][0].squeeze().cpu().numpy().astype(bool)
            indices = np.argwhere(mask)
            if len(indices) == 0:
                return

            # 重心計算 (indicesは y, x 順)
            v_cg = float(np.mean(indices[:, 0]))
            u_cg = float(np.mean(indices[:, 1]))

            # --- 1. 既存互換: 重心位置のパブリッシュ ---
            masked_depth = depth[mask]
            # 中央値による代表深度
            if depth.dtype == np.uint16:
                z_cg = float(np.median(masked_depth) / 1000.0)
            else:
                z_cg = float(np.median(masked_depth))

            res = Point(x=u_cg, y=v_cg, z=z_cg)
            self.pub_result.publish(res)

            # --- 2. 新規: 重心周辺サンプリング (PoseArrayにパッキング) ---
            
            # 探索範囲の決定
            h_img, w_img = mask.shape
            r = self.sampling_kernel_radius
            
            # 重心座標(float)を整数インデックスへ
            cv, cu = int(v_cg), int(u_cg)

            v_min = max(0, cv - r)
            v_max = min(h_img, cv + r + 1)
            u_min = max(0, cu - r)
            u_max = min(w_img, cu + r + 1)

            # 局所領域の切り出し
            local_mask = mask[v_min:v_max, u_min:u_max]
            local_depth = depth[v_min:v_max, u_min:u_max]

            # 局所領域内の絶対座標グリッド作成
            # grid_v, grid_u は局所内のオフセット
            grid_v, grid_u = np.indices(local_mask.shape)
            abs_v = grid_v + v_min
            abs_u = grid_u + u_min

            # フィルタ条件: マスク内 かつ 深度有効値(>0)
            valid_mask = (local_mask) & (local_depth > 0)
            
            # 該当するピクセル座標と深度を抽出
            # flattenしてリスト化
            valid_v = abs_v[valid_mask]
            valid_u = abs_u[valid_mask]
            valid_d = local_depth[valid_mask]

            # PoseArray作成
            pose_array_msg = PoseArray()
            pose_array_msg.header = self.latest_depth_msg.header
            
            vis_u_list = []
            vis_v_list = []

            # 抽出した点群をPoseArrayに詰める
            # ここでは「Poseを作成」するのではなく「データコンテナ」として使用
            for i in range(len(valid_d)):
                d_val = valid_d[i]
                
                # 単位変換 (mm -> m)
                if depth.dtype == np.uint16:
                    z_val = float(d_val) / 1000.0
                else:
                    z_val = float(d_val)

                pose = Pose()
                # 重要: ここには3次元座標ではなく画像座標と深度を入れる
                pose.position.x = float(valid_u[i]) # pixel u
                pose.position.y = float(valid_v[i]) # pixel v
                pose.position.z = z_val             # depth (meter)
                
                # orientationは使用しないためデフォルト(単位元)
                pose.orientation.w = 1.0 

                pose_array_msg.poses.append(pose)
                
                # 可視化用に保存
                vis_u_list.append(valid_u[i])
                vis_v_list.append(valid_v[i])

            self.pub_result_points.publish(pose_array_msg)


            # ===== デバッグ画像作成 =====
            plt.close('all')
            plot_results(image_pil, results) # SAM3可視化

            # 重心(+)
            plt.scatter(u_cg, v_cg, color='red', marker='+', s=500, linewidth=3, label='Centroid')
            
            # サンプリング点(.)
            if vis_u_list:
                # 数が多い場合は間引いて描画してもよいが、局所領域なら全点描画でもOK
                plt.scatter(vis_u_list, vis_v_list, color='lime', marker='.', s=10, alpha=0.6, label='Samples')

            plt.text(u_cg + 5, v_cg - 5, f'N={len(pose_array_msg.poses)}', 
                     color='lime', fontsize=12, fontweight='bold',
                     bbox=dict(facecolor='black', alpha=0.5, edgecolor='none'))

            fig = plt.gcf()
            plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
            fig.set_size_inches(12, 9, forward=True)
            fig.tight_layout(pad=0)
            fig.canvas.draw()

            w, h = fig.canvas.get_width_height()
            img_buf = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8).reshape(h, w, 3)
            plt.close(fig)

            debug_msg = self.bridge.cv2_to_imgmsg(img_buf, encoding='rgb8')
            self.pub_debug.publish(debug_msg)

            self.get_logger().info(
                f'Published: CG(u={u_cg:.1f}, v={v_cg:.1f}), Samples={len(pose_array_msg.poses)}'
            )

        except Exception as e:
            self.get_logger().error(f'SAM3 failed: {e}')
            import traceback
            traceback.print_exc()


def main():
    rclpy.init()
    node = Sam3ServiceNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()