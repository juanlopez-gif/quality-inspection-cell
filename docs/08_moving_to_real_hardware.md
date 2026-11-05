# 8. Moving to the real hardware

The design goal: **the supervisor and the messages do not change**. Each simulated device
node is replaced by a real driver that publishes/subscribes exactly the same topics and
messages. `world_sim` disappears. Use `launch/cell_real.launch.py` as a template.

| Simulated node | Real replacement (included) | Must keep |
|---|---|---|
| `conveyor_node` | `arduino_io_node` (node `/conveyor`) + `arduino/cell_io/cell_io.ino` | Subscribe `/conveyor/command`; publish `/conveyor/status` at 10 Hz and right after each change |
| `ir_sensor_node` | `arduino_io_node` (node `/ir_sensor`), same Arduino | Publish `/ir_sensor/status` at 20 Hz **and** on every change. **No command topic** |
| `camera_node` | Same node, `backend: opencv`, `source: 0` + calibration file (docs/14) | Same detections & inspection result. **Pick pose in UR base frame** |
| `robot_node` | `ur7e_robot_node` (ur_rtde: `moveL` + digital output for the vacuum) | Same states & `/robot/status`; obey `/robot/command` |
| `world_sim_node` | — (removed) | — |

All the details (wiring, protocol, pendant setup, calibration, bring-up order) are in
[13_hardware_arduino_ur7e.md](13_hardware_arduino_ur7e.md).

## 8.1 Checklist

1. **Calibrate the camera**: intrinsics (checkerboard) and pixel → mm on the belt plane.
2. **Calibrate camera ↔ robot**: touch 3–4 points on the belt with the robot TCP, measure
   them in the image, and fit the transform (`tools/calibrate_robot_base.py`). Write the
   result in `camera.robot_base_in_cell`.
3. **Measure the cell** and update `cell_config.yaml`: IR position, ROI, belt speed, bin
   positions (in cell frame), robot home, approach heights, `drop_z_mm`, max reach
   (UR7e = 850 mm).
4. **IR latency**: measure how far a piece travels between the beam being cut and the belt
   stopping; make sure the piece stays inside the ROI. Consider wiring the IR sensor to
   also cut the motor **in hardware**: the Arduino firmware already does it (`HW_INTERLOCK`).
5. **Vacuum**: set `robot.vacuum_output` to the UR digital output that drives the valve / pump.
6. **Test each driver alone** with `ros2 topic pub` before connecting the supervisor.
7. **Lighting**: fixed, diffuse light; color thresholds depend on it. Re-tune the hue
   windows with real photos.

## 8.2 Real-cell launch

```bash
ros2 launch quality_cell cell_real.launch.py port:=/dev/ttyACM0 ur_ip:=192.168.1.102
```

It starts the supervisor, `arduino_io_node`, `ur7e_robot_node`, the camera (OpenCV on the
USB camera; arguments `camera_source:=`, `camera_calibration:=`) and the dashboard.
