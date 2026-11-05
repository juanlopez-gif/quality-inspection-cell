#!/usr/bin/env bash
# Build the ROS 2 workspace.  Usage:  ./build.sh        (./build.sh clean  -> full rebuild)
set -e
cd "$(dirname "$0")/ros2_ws"
# A Python virtualenv on PATH breaks colcon/rclpy: remove it for this shell only.
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v -i venv | paste -sd:)
unset VIRTUAL_ENV
source /opt/ros/jazzy/setup.bash
if [ "$1" == "clean" ]; then rm -rf build install log; fi
colcon build --symlink-install
echo
echo "Build OK.  Now run:  ./run.sh"
