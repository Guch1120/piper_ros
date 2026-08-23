from setuptools import find_packages, setup
from glob import glob
import os

package_name = 'kobuki_unity'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='guch1120',
    maintainer_email='taku.fcbarca.messi10@gmail.com',
    description='Unity simulator bridge for the Kobuki mobile base',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'kobuki_unity_sim = kobuki_unity.kobuki_unity_sim_node:main',
            'cmd_vel_relay = kobuki_unity.cmd_vel_relay:main',
        ],
    },
)
