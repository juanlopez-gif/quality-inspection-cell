#!/usr/bin/env bash
# Launch the whole simulated cell + dashboard.  Then open http://localhost:8080
#   ./run.sh                     default
#   ./run.sh dashboard_port:=8081
set -e
cd "$(dirname "$0")/ros2_ws"
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v -i venv | paste -sd:)
unset VIRTUAL_ENV
source /opt/ros/jazzy/setup.bash
source install/setup.bash
( sleep 4; [ -z "$NO_BROWSER" ] && xdg-open http://localhost:8080 >/dev/null 2>&1 || true ) &
ros2 launch quality_cell cell_sim.launch.py "$@"
