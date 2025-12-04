import pyrealsense2 as rs
import numpy as np
import cv2
import os
import datetime

def capture_rgb_and_depth():
    # 保存先ディレクトリの作成
    save_dir = "captured_data"
    os.makedirs(save_dir, exist_ok=True)

    # RealSenseのパイプライン設定
    pipeline = rs.pipeline()
    config = rs.config()

    # デバイスの確認（接続されていないとここでエラーになる）
    try:
        pipeline_wrapper = rs.pipeline_wrapper(pipeline)
        pipeline_profile = config.resolve(pipeline_wrapper)
        device = pipeline_profile.get_device()
        device_product_line = str(device.get_info(rs.camera_info.product_line))
        print(f"Connected device: {device_product_line}")
    except RuntimeError:
        print("RealSenseカメラが見つかりません。接続を確認してください。")
        return

    # ストリームの設定 (RGB: 640x480, Depth: 640x480, 30fps)
    # ※解像度は必要に応じて 1280x720 などに変更可
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

    # ストリーミング開始
    profile = pipeline.start(config)

    # 深度とカラーの位置合わせ（Align）オブジェクト
    # これをしないとRGB画像と深度画像の画角がズレて使い物にならない
    align_to = rs.stream.color
    align = rs.align(align_to)

    print("撮影準備完了。's'キーで保存、'q'キーで終了します。")

    try:
        while True:
            # フレーム待ち受け
            frames = pipeline.wait_for_frames()
            
            # アライメント実行（深度をカラーに合わせる）
            aligned_frames = align.process(frames)
            
            aligned_depth_frame = aligned_frames.get_depth_frame()
            color_frame = aligned_frames.get_color_frame()

            if not aligned_depth_frame or not color_frame:
                continue

            # 画像データをnumpy配列に変換
            depth_image = np.asanyarray(aligned_depth_frame.get_data())
            color_image = np.asanyarray(color_frame.get_data())

            # 深度画像の可視化用に色付け（ヒートマップ的なやつ）
            # データ解析用ではなく、人間が見る確認用
            depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET)

            # 画面表示用に画像を横に連結
            images = np.hstack((color_image, depth_colormap))

            cv2.imshow('RealSense Capture (Press "s" to save)', images)
            key = cv2.waitKey(1)

            # 's'キーで保存
            if key & 0xFF == ord('s'):
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # 1. RGB画像の保存
                rgb_filename = os.path.join(save_dir, f"{timestamp}_rgb.jpg")
                cv2.imwrite(rgb_filename, color_image)
                
                # 2. 深度データの保存（生データ .npy）
                # これが一番重要。後で正確な距離（ミリメートル）を取り出せる。
                depth_raw_filename = os.path.join(save_dir, f"{timestamp}_depth_raw.npy")
                np.save(depth_raw_filename, depth_image)
                
                # 3. 深度画像の保存（確認用 .png）
                depth_img_filename = os.path.join(save_dir, f"{timestamp}_depth_view.png")
                cv2.imwrite(depth_img_filename, depth_colormap)

                print(f"Saved: {timestamp}")

            # 'q'キーで終了
            elif key & 0xFF == ord('q'):
                break

    finally:
        # 終了処理
        pipeline.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    capture_rgb_and_depth()