from glob import glob
from setuptools import setup
package_name = "piper_websim"
setup(
    name=package_name, version="0.1.0", packages=[package_name],
    data_files=[("share/ament_index/resource_index/packages", ["resource/" + package_name]), ("share/" + package_name, ["package.xml"]), ("share/" + package_name + "/launch", glob("launch/*.py")), ("share/" + package_name + "/config", glob("config/*.yaml"))],
    install_requires=["setuptools"], zip_safe=True,
    entry_points={"console_scripts": ["trajectory_bridge = piper_websim.trajectory_bridge:main", "vision_bridge = piper_websim.vision_bridge:main"]},
)
