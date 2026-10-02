from setuptools import setup

package_name = "optics_bench_driver"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Ryan Vincent",
    maintainer_email="120872605+CoraBeanz@users.noreply.github.com",
    description="ROS 2 driver for the optics bench controller, with auto-align.",
    license="Proprietary",
    extras_require={"test": ["pytest"]},
    entry_points={"console_scripts": ["bench_driver = optics_bench_driver.driver_node:main"]},
)
