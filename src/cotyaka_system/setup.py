from glob import glob
from setuptools import find_packages, setup

package_name = 'cotyaka_system'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='root@todo.todo',
    description='Lifecycle system monitoring for Cotyaka.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'system_monitor = cotyaka_system.system_monitor:main',
        ],
    },
)
