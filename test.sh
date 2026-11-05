#!/usr/bin/env bash
# Run the unit tests of the supervisor rules and the classifier (no ROS graph needed).
set -e
cd "$(dirname "$0")/ros2_ws/src/quality_cell"
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v -i venv | paste -sd:)
source /opt/ros/jazzy/setup.bash
python3 -m pytest -v test/
