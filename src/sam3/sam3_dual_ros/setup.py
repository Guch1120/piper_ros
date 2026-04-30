from setuptools import setup

package_name = "sam3_dual_ros"

setup(
    name=package_name,
    version="0.0.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/sam3.launch.py", "launch/sam3.launch"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="OpenAI",
    maintainer_email="noreply@example.com",
    description="Separate SAM3 ROS wrapper package",
    license="MIT",
    entry_points={
        "console_scripts": [
            "sam3-dual-ros = sam3_dual_ros.cli:main",
        ],
    },
)
