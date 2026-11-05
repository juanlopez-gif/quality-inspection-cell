# 6. Simulation and dashboard

## 6.1 What is simulated and how

| Real thing | Simulated by | Notes |
|---|---|---|
| Physical pieces, belt movement, gravity in bins | `world_sim_node.py` | 50 Hz; publishes ground truth on `/sim/world_state` |
| Conveyor motor | `conveyor_node.py` | Instant start/stop at `speed_mm_s` (80 mm/s) |
| IR beam | `ir_sensor_node.py` | Beam is the line `x = ir_sensor.x_mm`; occupied if a piece footprint crosses it |
| Camera image | `sim_renderer.py` (inside `camera_node`) | Renders the belt and pieces with perspective, light gradient, blur and noise; the **real** OpenCV pipeline analyses it (`camera_backend:=sim` = ground truth + noise instead) |
| UR7e + vacuum | `robot_node.py` (or `ur7e_robot_node.py` with `robot:=ur7e_dry`) | Straight-line TCP moves at `tcp_speed_mm_s`, vacuum times, reach check (850 mm) |
| Operator | `dashboard_node.py` (web) | Publishes `/sim/spawn_piece` |

`world_sim` attaches a piece to the suction cup when the vacuum turns ON with the cup on the
piece (centre within 1/3 of the piece size, cup at the piece height), and drops it in the
bin under the TCP when the vacuum turns OFF. A cup that is off-centre picks nothing
(event `Vacuum ON but NO piece under the cup`) — useful to test the calibration. If the robot
releases outside a bin the piece goes to the `FLOOR` (shown in the view) — useful to test
wrong calibrations. Placing a piece while the start of the belt is busy is refused
(event `SPAWN REJECTED`); the dashboard queues pieces and waits for space automatically.

## 6.2 Dashboard (http://localhost:8080)

Served by `dashboard_node.py` (Python standard library HTTP server, no internet needed).
Files: `quality_cell/web/index.html`, `style.css`, `app.js`.

### Tab "Cell view"
* Top view of the cell to scale: belt with moving slats, LOAD zone, camera field of view,
  pick ROI (turns bright while INSPECTING), IR beam (green FREE / red OCCUPIED), UR7e arm
  with the suction cup (glows blue while vacuum is ON) and height, the 9 bins with counters.
* Yellow dashed boxes = what the **camera** reports (preliminary detections), with track
  id, class and confidence — compare them with the real pieces.
* **Operator panel**: shape, color (6 presets + custom picker), size slider, surface mark
  (none, cross, smiley, scratch, dot, groove), lateral offset, rotation → *Place on belt*.
  Quick buttons: random good piece, random defective piece, batch of 6 mixed, reset world.
* **What the camera sees**: `/camera/debug_image` — the camera image with the contours, class,
  size and id of each piece, the pick ROI and the last inspection (opencv backend).
* Status cards for every device (straight from the `status` topics), last inspection
  result (verdict, measurements, pick pose in robot frame), robot state strip, latest events.

### Tab "Architecture (rqt_graph)"
* Live graph from ROS introspection (`get_publishers_info_by_topic`, …), drawn as one
  horizontal **lane per device**: device → status topic → supervisor, and supervisor →
  command topic → device. All edges are straight and never cross.
* By default only the real architecture is shown. *Show simulation-only nodes* adds the
  `world_sim` column (its subscriptions to `/conveyor/status` and `/robot/status` are written
  in its box instead of drawn, to keep the graph readable); *Show dashboard links* adds the
  monitor node.
* Blue = status, orange = command, grey dashed = simulation. Moving dashes = messages are
  flowing (speed ∝ rate); command edges flash when a command is sent; rate shown in Hz.
* Red dotted edge / red node = **expected but not found** (e.g. a node crashed or a topic
  name typo). The **topic contract check** table lists each expected publisher/subscriber
  with ✓ / ✗.
* Click a node or a topic to see its role, source file, publishers and subscribers.
* Toggle *Animate message flow* to switch the moving dashes off.

### Tab "Supervisor rules & state machines"
Rule table with the rules that were TRUE in the last evaluation highlighted, and the live
state of the conveyor, IR sensor, camera, robot and cell.

### Tab "Event log"
Commands (always), status changes, inspection results and simulation events, each with
time stamp and topic. Commands include the rule that produced them, e.g.
`STOP [R2: SAFETY: IR sensor OCCUPIED -> STOP conveyor (always)]`. Filter, pause, clear.

### Tab "Topics & messages"
All topics with type, direction, rate and count. Click a row to see the last message as JSON.

## 6.3 Dashboard HTTP API (for scripts / tests)

```bash
curl localhost:8080/api/state                  # latest messages + stats
curl localhost:8080/api/graph                  # live ROS graph
curl "localhost:8080/api/events?since=0"       # event log
curl -X POST localhost:8080/api/spawn -d '{"shape":"SQUARE","color_name":"BLUE","r":40,"g":95,"b":225,"size_mm":42,"mark":"NONE"}'
curl -X POST localhost:8080/api/reset
```

Or without the dashboard, directly with ROS:

```bash
ros2 topic pub --once /sim/spawn_piece cell_interfaces/msg/SpawnPiece \
  "{shape: CIRCLE, color_name: RED, r: 220, g: 45, b: 45, size_mm: 42.0, mark: CROSS}"
```

Continue with [07_installation_and_running.md](07_installation_and_running.md).
