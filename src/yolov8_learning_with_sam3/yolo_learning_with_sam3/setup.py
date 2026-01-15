from setuptools import find_packages, setup

package_name = 'yolov8_learning_with_sam3'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', [
            'launch/yolov8_bb.launch.py',
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='root@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'yolov8_node_bb = yolov8_learning_with_sam3.yolov8_node_bb:main',
            'debug_yolov8_bb_node = yolov8_learning_with_sam3.debug_yolov8_bb_node:main',
        ],
    },
)
