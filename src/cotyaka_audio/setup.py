from setuptools import find_packages, setup

package_name = 'cotyaka_audio'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='root@todo.todo',
    description='Audio output service for Cotyaka: fixed MP3 and TTS.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'audio_node = cotyaka_audio.audio_node:main',
        ],
    },
)
