# 12. ROS 2 cheat sheet for this project

```bash
source /opt/ros/jazzy/setup.bash && source ~/Desktop/quality_inspection_cell/ros2_ws/install/setup.bash

ros2 node list                                   # running nodes
ros2 node info /supervisor                       # pubs/subs of a node
ros2 topic list -t                               # topics + types
ros2 topic echo /robot/status                    # print messages
ros2 topic echo /camera/inspection_result --once
ros2 topic hz /ir_sensor/status                  # rate
ros2 topic info -v /conveyor/command             # who publishes / subscribes (QoS too)
ros2 interface show cell_interfaces/msg/RobotCommand

# Talk to the cell by hand (testing a device WITHOUT the supervisor: stop the supervisor first!)
ros2 topic pub --once /conveyor/command cell_interfaces/msg/ConveyorCommand "{command: RUN, reason: manual}"
ros2 topic pub --once /robot/command cell_interfaces/msg/RobotCommand \
  "{command: PICK_AND_PLACE, job_id: 99, pick_x_mm: -20.0, pick_y_mm: -250.0, pick_z_mm: 6.0, destination_bin: BIN_RED_CIRCLE}"
ros2 topic pub --once /robot/command cell_interfaces/msg/RobotCommand "{command: GO_HOME}"
ros2 topic pub --once /robot/command cell_interfaces/msg/RobotCommand "{command: RESET}"

# Real hardware drivers
ros2 run quality_cell arduino_io_node --ros-args -p port:=/dev/ttyACM0
ros2 run quality_cell ur7e_robot_node --ros-args -p ur_ip:=192.168.1.102     # -p dry_run:=true without robot

# Simulation helpers
ros2 topic pub --once /sim/spawn_piece cell_interfaces/msg/SpawnPiece \
  "{shape: SQUARE, color_name: GREEN, r: 40, g: 170, b: 75, size_mm: 42.0, mark: NONE}"
ros2 topic pub --once /sim/reset std_msgs/msg/Empty "{}"

# Record and replay a session (great for reports)
ros2 bag record /conveyor/status /ir_sensor/status /camera/inspection_result /robot/status /supervisor/status
ros2 bag play <bag_folder>
```
