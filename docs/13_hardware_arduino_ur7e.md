# 13. Real hardware: Arduino (conveyor + IR) and UR7e with vacuum

This chapter describes the hardware of **our** cell. For the complete build procedure (parts,
layout, wiring diagram, config, commissioning checklist) see
[15_physical_build_guide.md](15_physical_build_guide.md).

| Part | Hardware | ROS 2 node (real) | Replaces (sim) |
|---|---|---|---|
| Conveyor motor | Motor switched by a relay / MOSFET on an **Arduino** | `arduino_io_node` → node `/conveyor` | `conveyor_node` |
| IR sensor | IR break-beam (or reflective IR) on the **same Arduino** | `arduino_io_node` → node `/ir_sensor` | `ir_sensor_node` |
| Robot | **Universal Robots UR7e** (6 axes, 850 mm reach, 7.5 kg) | `ur7e_robot_node` | `robot_node` |
| End effector | **Vacuum suction cup** (valve / ejector or pump on a UR digital output) | inside `ur7e_robot_node` | — |
| Camera | overhead USB camera | `camera_node` (`backend: opencv`, see docs/14) | images rendered from the simulator |

The supervisor and all topics stay **exactly** the same.

---

## 13.1 Arduino

### Wiring (Arduino Uno / Nano / Mega)

```
 IR break-beam RECEIVER          Arduino                Relay module (or MOSFET board)
   VCC  ───────────────────────  5V  ──────────────────  VCC
   GND  ───────────────────────  GND ──────────────────  GND
   OUT  ───────────────────────  D2  (INPUT_PULLUP)
                                 D7  ──────────────────  IN
 IR EMITTER: VCC→5V, GND→GND     D13 = on-board LED (lights when the beam is blocked)

 Relay contact (COM/NO) in series with the conveyor motor supply (e.g. 24 V DC).
 Motor power supply GND is NOT the Arduino 5 V supply. Use a flyback diode if you
 switch a DC motor with a MOSFET.
```

Settings at the top of `arduino/cell_io/cell_io.ino`:

| Constant | Default | Meaning |
|---|---|---|
| `PIN_IR` / `PIN_MOTOR` | 2 / 7 | pins |
| `IR_ACTIVE_LOW` | `true` | output LOW = beam blocked (most break-beam receivers / IR modules) |
| `MOTOR_ACTIVE_HIGH` | `true` | set `false` for active-LOW relay modules |
| `HW_INTERLOCK` | `true` | firmware stops the motor when the beam is blocked and refuses `RUN` |
| `DEBOUNCE_MS` | 15 | IR must be stable this long |
| `WATCHDOG_MS` | 1500 | motor stops if the PC sends nothing (the bridge pings every 200 ms) |

Upload with the Arduino IDE (115200 baud). Check in the Serial Monitor (newline ending):
you should see `BOOT quality_cell_io 1` and `STAT 0 0` lines; type `RUN` / `STOP`.

### Serial protocol

| Direction | Line | Meaning |
|---|---|---|
| PC → Arduino | `RUN` / `STOP` | motor on / off |
| PC → Arduino | `PING` | heartbeat every 200 ms |
| Arduino → PC | `STAT <ir> <motor>` | every 50 ms **and** on every change (`ir` 1=OCCUPIED, `motor` 1=RUNNING) |
| Arduino → PC | `ACK RUN` / `ACK STOP` | command accepted |
| Arduino → PC | `ERR INTERLOCK` | `RUN` refused: beam blocked |
| Arduino → PC | `ERR WATCHDOG` | motor stopped: PC silent |

### Why ONE process with TWO nodes
One Arduino = one serial port, and a serial port can only be opened by one process.
`arduino_io_node.py` opens it once and creates two ROS nodes, `/conveyor` and
`/ir_sensor`, so the graph (and the supervisor) look exactly like in simulation. The IR
node is still **reactive**: it has no command topic.

### Three layers of safety for "IR occupied ⇒ belt stopped"
1. **Supervisor rule R2** (software, ROS).
2. **Firmware interlock** (`HW_INTERLOCK`): the Arduino stops the motor itself on the IR edge,
   within ~15 ms, even if ROS is slow.
3. **Fail-safe**: if the Arduino stops reporting (USB unplugged, reset), the `/ir_sensor`
   node **stops publishing** (it never invents a state) → rule **R1** stops the belt; and
   the firmware watchdog stops the motor if the PC disappears.

### Testing without the Arduino
`tools/fake_arduino.py` emulates the firmware on a virtual serial port:

```bash
python3 tools/fake_arduino.py                     # prints e.g. /dev/pts/5 ; type b / f + Enter
ros2 run quality_cell arduino_io_node --ros-args -p port:=/dev/pts/5
ros2 topic echo /ir_sensor/status
ros2 topic pub --once /conveyor/command cell_interfaces/msg/ConveyorCommand "{command: RUN}"
```

Serial port permissions: `sudo usermod -aG dialout $USER` (log out / in). Find the port
with `ls /dev/ttyACM* /dev/ttyUSB*`.

> Note: the belt has no encoder, so `/conveyor/status.speed_mm_s` reports the **nominal**
> speed `conveyor.speed_mm_s` while running. Measure it (time a piece over 500 mm) and
> write the real value in the config.

---

## 13.2 UR7e + vacuum

### Software
`ur7e_robot_node.py` uses the **ur_rtde** library (simple, blocking `moveL`, digital I/O):

```bash
pip3 install --user --break-system-packages ur_rtde
python3 -c "import rtde_control, rtde_receive, rtde_io; print('ur_rtde OK')"
```

> Do **not** run `ur_robot_driver` (External Control URCap) at the same time: both want to
> control the robot. If later you prefer the official ROS driver + MoveIt, keep the same
> `/robot/command` ↔ `/robot/status` contract and replace only the backend class.

### Teach pendant setup (PolyScope)
1. **Network**: static IP (e.g. `192.168.1.102`), PC on the same subnet. `ping` it.
2. **Remote Control**: Settings → System → Remote Control → *Enable*; then switch the
   robot to **Remote** mode (top-right of the pendant). ur_rtde needs it to move the robot.
3. **TCP**: Installation → General → TCP: set the TCP to the **tip of the suction cup**
   (Z offset = flange-to-cup-tip length). All pick heights assume this.
4. **Payload**: cup + piece mass and centre of gravity.
5. **Vacuum output**: note which digital output drives the vacuum valve / ejector / pump
   relay and write it in `robot.vacuum_output` (`standard` DO0–7, `configurable` CO0–7 or
   `tool` TO0–1). Check the current limits in the UR7e manual; use a relay for a pump.
6. **Safety**: configure reduced speed / safety planes around the belt and the bins.

### Configuration (`config/cell_config.yaml`, section `robot`)

| Key | Meaning |
|---|---|
| `ur_ip` | controller IP |
| `home_tcp` | home pose (UR Base frame, mm). Pick a safe pose above the belt |
| `tool_rotvec` | tool orientation (rotation vector, rad). `[3.1416, 0, 0]` = cup pointing down. **Copy RX, RY, RZ from the pendant** with the cup vertical |
| `tcp_speed_mm_s`, `tcp_acc_mm_s2` | linear speed / acceleration (start with 100 mm/s) |
| `approach_height_mm` | height above pick / bin for approach and retreat |
| `pick_press_mm` | how much below the piece top the cup goes to seal (1 mm) |
| `vacuum_on_time_s` / `vacuum_off_time_s` | wait for suction to build / for the piece to fall |
| `max_reach_mm` | 850 (UR7e). The plan is refused (state `ERROR`) beyond it |
| `vacuum_output`, `vacuum_active_high` | which output and polarity |

Yaw: with a round suction cup the yaw of the piece does not matter, so the tool
orientation is fixed (`tool_rotvec`). `pick_yaw_deg` is still reported in `/robot/status`.

### Frames and calibration
The camera sends the pick point in the **UR Base frame** (the "Base" feature on the
pendant), using `camera.robot_base_in_cell` (x, y, yaw of the UR base expressed in the
CELL frame). To measure it:

```bash
# file points.txt:   cell_x  cell_y  robot_x  robot_y     (mm, robot = pendant TCP X,Y in Base)
200   0    -580 -250
700  40     -80 -210
700 -40     -80 -290
python3 tools/calibrate_robot_base.py points.txt
# -> robot_base_in_cell: {x: 780.0, y: 250.0, z: 0.0, yaw_deg: 0.00}   + residuals
```

Copy the printed line into the config and set **z**: touch the belt surface with the
cup tip, read Z on the pendant and write `z = -Z` (belt surface = 0 in the cell frame). Residuals above ~3 mm usually mean the TCP is not
set to the cup tip or a point was read wrongly. Also re-measure the bin centres (cell
frame) and `bins.drop_z_mm`.

### Behaviour on errors
* Plan out of reach / unknown bin → `ERROR` before moving.
* `moveL` fails (protective stop, e-stop, lost connection) → `stopL`, `ERROR`, and the
  vacuum is **kept ON** so a held piece is not dropped in a random place. Clear the
  robot on the pendant, then send `RESET` (`/robot/command`).
* Connection lost → `/robot/status` reports `ERROR` ("connection to the UR controller lost").
* The node **never moves the robot when it starts**. The first motion is the first job.

---

## 13.3 Bring-up order (do it step by step!)

| Step | Command | What to check |
|---|---|---|
| 1. Logic | `./test.sh` | 199 tests pass |
| 2. Full simulation | `./run.sh` | pieces sorted in the dashboard |
| 3. UR driver code without robot | `./run.sh robot:=ur7e_dry` | same behaviour, log says `DRY RUN` |
| 4. Arduino alone | Serial Monitor `RUN`/`STOP`, block the beam | motor + `STAT` lines, interlock |
| 5. Arduino bridge | `ros2 run quality_cell arduino_io_node --ros-args -p port:=/dev/ttyACM0` + `ros2 topic echo /ir_sensor/status` | FREE/OCCUPIED, RUN/STOP by hand |
| 6. Robot alone | pendant in Remote; `ros2 run quality_cell ur7e_robot_node --ros-args -p ur_ip:=…`; send `GO_HOME`, then one `PICK_AND_PLACE` by hand (see `docs/12`) at LOW speed | correct heights, vacuum switches |
| 7. **Hardware-in-the-loop robot** | `./run.sh robot:=ur7e ur_ip:=192.168.1.102` | the **real UR7e** picks the **virtual** pieces of the simulation (empty belt!) → checks calibration, bins and reach safely |
| 8. Camera | mount + light, `tools/calibrate_camera.py` (docs/14), then `ros2 launch quality_cell cell_real.launch.py robot_dry_run:=true camera_source:=0` and put real pieces under the camera | dashboard "What the camera sees": contours, sizes ±0.5 mm, colours, marks |
| 9. Real cell | `ros2 launch quality_cell cell_real.launch.py port:=/dev/ttyACM0 ur_ip:=… camera_source:=0` | the full cycle |
