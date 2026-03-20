from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'sam3_ros'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='user',
    maintainer_email='user@todo.todo',
    description='SAM3 object tracking ROS 2 package',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
        'sam3_node = sam3_ros.sam3_node:main',
        'segment_with_depth_pub = sam3_ros.segment_with_depth_pub_node:main',
        'tf_pub_node = sam3_ros.TF_pub_node:main',
        'sam3_node_for_tracker = sam3_ros.sam3_node_pub_BB_position:main',
        'sam3_hybrid_tracker = sam3_ros.Tracker_node:main',
        'sam3_node_for_videoTracker = sam3_ros.test_sam3_node_for_videoTracker:main',
        ],
    },
)
