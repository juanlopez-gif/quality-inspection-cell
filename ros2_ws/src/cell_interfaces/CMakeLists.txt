cmake_minimum_required(VERSION 3.8)
project(cell_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  # ---- Command / status interfaces (the "real" cell contract) ----
  "msg/ConveyorCommand.msg"
  "msg/ConveyorStatus.msg"
  "msg/IRSensorStatus.msg"
  "msg/CameraCommand.msg"
  "msg/DetectedPiece.msg"
  "msg/CameraDetections.msg"
  "msg/InspectionResult.msg"
  "msg/RobotCommand.msg"
  "msg/RobotStatus.msg"
  "msg/SupervisorStatus.msg"
  # ---- Simulation-only interfaces (removed when using real hardware) ----
  "msg/SimPiece.msg"
  "msg/SimWorldState.msg"
  "msg/SpawnPiece.msg"
  DEPENDENCIES std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
