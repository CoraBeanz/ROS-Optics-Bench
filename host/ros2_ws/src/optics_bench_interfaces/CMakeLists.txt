cmake_minimum_required(VERSION 3.8)
project(optics_bench_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/BenchStatus.msg"
  "msg/Photodiodes.msg"
  "msg/BeamSpot.msg"
  "srv/Command.srv"
  "action/MoveTo.action"
  "action/Align.action"
  DEPENDENCIES std_msgs
)

ament_package()
