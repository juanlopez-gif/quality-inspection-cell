# 7. Installation and running

## 7.1 Requirements

* Ubuntu 24.04, ROS 2 **Jazzy** installed in `/opt/ros/jazzy`
  (`sudo apt install ros-jazzy-desktop python3-colcon-common-extensions`)
* `python3-yaml`, `python3-pytest`, `python3-serial`, `python3-opencv`, `python3-numpy`
  (`sudo apt install python3-opencv python3-serial` if missing)
* Only for the real robot: `pip3 install --user --break-system-packages ur_rtde`
* A web browser. No internet needed.

> **Python virtual environments**: if a `venv` is active (or on your `PATH`), `colcon` and
> `rclpy` may pick the wrong Python and fail with `No module named 'rclpy'` or
> `catkin_pkg`. The scripts `build.sh`, `run.sh` and `test.sh` remove any venv from the
> `PATH` automatically. If you build by hand, run `deactivate` first.

## 7.2 Build

```bash
cd ~/Desktop/quality_inspection_cell
./build.sh            # or ./build.sh clean  for a full rebuild
```

By hand:

```bash
cd ~/Desktop/quality_inspection_cell/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
```

`--symlink-install` means Python files, the YAML config and the web files are linked, not
copied: after editing them just relaunch. Changing a `.msg` file **does** need a rebuild.

## 7.3 Run

```bash
./run.sh                               # opens http://localhost:8080
./run.sh dashboard_port:=8081          # another port
./run.sh config:=/abs/path/config.yaml # another configuration
./run.sh robot:=ur7e_dry               # simulated cell + real UR7e driver code (no robot)
./run.sh camera_backend:=sim           # ground-truth camera (no images, less CPU)
./run.sh camera_source:=0              # OpenCV pipeline on a USB camera (needs calibration_file)
./run.sh robot:=ur7e ur_ip:=192.168.1.102   # real UR7e + virtual pieces (see docs/13)
```

By hand:

```bash
cd ~/Desktop/quality_inspection_cell/ros2_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch quality_cell cell_sim.launch.py
```

Running one node alone (e.g. to debug it):

```bash
ros2 run quality_cell supervisor_node
ros2 run quality_cell camera_node --ros-args -p cell_config_file:=/abs/path/cell_config.yaml
```

Stop everything with **Ctrl+C** in the launch terminal.

## 7.4 Tests

```bash
./test.sh
```

199 tests: color/size/mark classification and defect priority, and the supervisor rules
(fail-safe stop, empty cell, new piece, IR occupied always stops, full cycle, inspection
retry, stale results ignored) the pick & place plan (order, vacuum ON/OFF, reach, unknown bin) and the OpenCV
pipeline on synthetic images (180 shape × colour × size × mark cases, tracking, belt motion). They do not need any node to be running.

## 7.5 Watching the system from the terminal

```bash
ros2 node list
ros2 topic list -t
ros2 topic echo /supervisor/status
ros2 topic echo /camera/inspection_result
ros2 topic hz /ir_sensor/status
rqt_graph                       # classic graph (the dashboard has a nicer one)
```

Continue with [08_moving_to_real_hardware.md](08_moving_to_real_hardware.md).
