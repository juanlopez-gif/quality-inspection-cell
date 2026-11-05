# 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No module named 'rclpy'` or colcon errors about `catkin_pkg` | A Python venv is on the PATH. Use `./build.sh` / `./run.sh` or `deactivate`. |
| `failed to create symbolic link ... Is a directory` while building | You switched between normal and `--symlink-install` builds. `./build.sh clean`. |
| Dashboard says "dashboard_node not reachable" | Launch not running, or port busy: `./run.sh dashboard_port:=8081`. Check `ss -ltnp | grep 8080`. |
| `Address already in use` | Another launch is still running: `pkill -f quality_cell` and relaunch. |
| Piece placed but nothing happens | Check the Event log: `SPAWN REJECTED` means the start of the belt is busy. If the camera reports 0 pieces, check `/sim/world_state`. |
| First piece after launch disappears | It was published before `world_sim` was discovered. Wait 2 s after launch. |
| Belt never starts | IR status missing (R1) → is `ir_sensor` running? `ros2 topic hz /ir_sensor/status`. |
| Robot `ERROR: out of reach` | Bin or pick point farther than `robot.max_reach_mm` from the robot base. |
| "Piece dropped OUTSIDE any bin" | Bin coordinates and `robot_base_in_cell` inconsistent. |
| Graph shows red dotted edges | A node is down or a topic name does not match the contract. See the contract table. |
| Two launches see each other's nodes | Same `ROS_DOMAIN_ID` on the same network. `export ROS_DOMAIN_ID=42` (any 0–101). |
| Camera node: `Cannot open camera source` | Wrong index (`ls /dev/video*`; `v4l2-ctl --list-devices`), camera used by another program, user not in group `video`. |
| Camera node: `Image size … differs from the calibration` | The camera ignored the requested resolution. Set `camera.capture` to a supported mode (`v4l2-ctl --list-formats-ext`) and re-calibrate. |
| Every piece rejected as MARKED on the real camera | Reflections: diffuse the light, raise `mark_color_distance` (docs/14 §14.4). |
| Camera image stays black / "No camera image" in the dashboard | `camera.backend` is `sim` (no images), or the camera node crashed: check the launch terminal. |
| Camera node uses a lot of CPU | Normal with `sim_render` (it renders + analyses 10 images/s). Use `camera_backend:=sim` on slow PCs. |
