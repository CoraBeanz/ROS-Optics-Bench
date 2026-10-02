from glob import glob

from setuptools import setup

package_name = "optics_bench_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=[],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/udev", glob("udev/*.rules")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Ryan Vincent",
    maintainer_email="120872605+CoraBeanz@users.noreply.github.com",
    description="Launch files, parameters and the udev rule for the optics bench.",
    license="Proprietary",
)
