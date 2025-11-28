import numpy as np
from record3d import Record3DStream
import cv2
from threading import Event
import os
import time
import json
import lzfse

class Record3DReceiver:
    def __init__(self, output_dir="output"):
        self.event = Event()
        self.session = None
        self.output_dir = output_dir
        self.rgbd_dir = os.path.join(output_dir, "rgbd")
        self.metadata_file = os.path.join(output_dir, "metadata")
        
        os.makedirs(self.rgbd_dir, exist_ok=True)
        
        # Metadata storage
        self.poses = []
        self.frame_timestamps = []
        self.intrinsic_matrix = None
        self.init_pose = None
        self.fps = 30 # Default, will try to get from device
        self.width = 0
        self.height = 0

    def on_new_frame(self):
        self.event.set()

    def on_stream_stopped(self):
        print('Stream stopped')
        self.event.set()

    def connect_to_device(self, dev_idx=0):
        print('Searching for devices...')
        devs = Record3DStream.get_connected_devices()
        print('{} device(s) found'.format(len(devs)))
        for dev in devs:
            print('\tID: {}\n\tUDID: {}\n'.format(dev.product_id, dev.udid))

        if len(devs) <= dev_idx:
            raise RuntimeError('Cannot connect to device #{}, try different index.'.format(dev_idx))

        dev = devs[dev_idx]
        self.session = Record3DStream()
        self.session.on_new_frame = self.on_new_frame
        self.session.on_stream_stopped = self.on_stream_stopped
        self.session.connect(dev)

    def save_metadata(self):
        if self.intrinsic_matrix is None:
            print("No intrinsic matrix found, cannot save metadata.")
            return

        # Prepare metadata dict
        # Flatten K to list
        K_list = self.intrinsic_matrix.flatten().tolist()
        
        # Poses: [qx, qy, qz, qw, tx, ty, tz]
        # Record3D provides pose as quaternion + translation
        # We need to make sure we store it in the format expected by clip-fields-km
        # Looking at record3d.py: qx, qy, qz, qw, px, py, pz = self.poses[index]
        
        metadata = {
            "w": self.width,
            "h": self.height,
            "fps": self.fps,
            "K": K_list,
            "poses": self.poses,
            "initPose": self.init_pose if self.init_pose else [0,0,0,1,0,0,0],
            "frameTimestamps": self.frame_timestamps
        }
        
        with open(self.metadata_file, 'w') as f:
            json.dump(metadata, f)
        print(f"Metadata saved to {self.metadata_file}")

    def start_processing_stream(self):
        print("Starting stream processing. Press Ctrl+C to stop.")
        frame_idx = 0
        try:
            while True:
                self.event.wait()
                self.event.clear()

                # Get data
                depth = self.session.get_depth_frame()
                rgb = self.session.get_rgb_frame()
                confidence = self.session.get_confidence_frame()
                camera_pose = self.session.get_camera_pose()
                timestamp = time.time()

                # Initialize metadata on first frame
                if frame_idx == 0:
                    self.width = rgb.shape[1]
                    self.height = rgb.shape[0]
                    intrinsics = self.session.get_intrinsic_mat()
                    self.intrinsic_matrix = np.array([[intrinsics.fx, 0, intrinsics.tx],
                                                      [0, intrinsics.fy, intrinsics.ty],
                                                      [0, 0, 1]])
                    # Store init pose
                    self.init_pose = [camera_pose.qx, camera_pose.qy, camera_pose.qz, camera_pose.qw,
                                      camera_pose.tx, camera_pose.ty, camera_pose.tz]

                # Store pose
                current_pose = [camera_pose.qx, camera_pose.qy, camera_pose.qz, camera_pose.qw,
                                camera_pose.tx, camera_pose.ty, camera_pose.tz]
                self.poses.append(current_pose)
                self.frame_timestamps.append(timestamp)

                # Save RGB
                rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                cv2.imshow("Record3D Stream", rgb_bgr)
                cv2.waitKey(1)
                cv2.imwrite(os.path.join(self.rgbd_dir, f"{frame_idx}.jpg"), rgb_bgr)

                # Save Depth (Compressed)
                # Depth is float32
                depth_bytes = depth.tobytes()
                compressed_depth = lzfse.compress(depth_bytes)
                with open(os.path.join(self.rgbd_dir, f"{frame_idx}.depth"), 'wb') as f:
                    f.write(compressed_depth)

                # Save Confidence (Compressed)
                # Confidence is uint8 (0, 1, 2)
                conf_bytes = confidence.tobytes()
                compressed_conf = lzfse.compress(conf_bytes)
                with open(os.path.join(self.rgbd_dir, f"{frame_idx}.conf"), 'wb') as f:
                    f.write(compressed_conf)

                print(f"Recorded frame {frame_idx}", end='\r')
                frame_idx += 1

        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            self.save_metadata()
            cv2.destroyAllWindows()

if __name__ == '__main__':
    receiver = Record3DReceiver(output_dir="/app/output")
    try:
        receiver.connect_to_device()
        receiver.start_processing_stream()
    except Exception as e:
        print(f"Error: {e}")
