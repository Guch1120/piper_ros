from setuptools import find_packages, setup
import glob
import sys
import os
from glob import glob

package_name = 'piper'

python_version = f'{sys.version_info.major}.{sys.version_info.minor}'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='root@todo.todo',
    description='TODO: Package description',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'piper_single_ctrl = piper.piper_single_ctrl_node:main',
            'piper_read_slave_joint = piper.piper_read_slave_joint:main',
            'piper_single_ctrl_moveit = piper.piper_single_ctrl_moveit_node:main',
            'piper_moveit_bridge = piper.moveit_bridge:main',
            'piper_moveit_bridge_smooth = piper.moveit_bridge_smoth:main',
            'moveit_client = piper.moveit_client_node:main ',
            'moveit_client_tf = piper.moveit_client_tf_node:main',
            'moveit_client_tf_interactive = piper.moveit_client_tf_interactive:main',
            'pick_and_place_trajectory = piper.pick_and_place_trajectry:main',
            'gripper_open_test = piper.gripper_open_test_node:main',
            'gripper_close_test = piper.gripper_close_test_node:main',
        ],
    },
)
