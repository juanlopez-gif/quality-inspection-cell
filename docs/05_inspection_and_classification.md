# 5. Inspection and classification

## 5.1 Two levels of vision

| | Preliminary detection | Final inspection |
|---|---|---|
| When | continuously, 10 Hz, belt moving or stopped | only after `INSPECT`, piece stopped at the IR sensor |
| Where | transport zone (whole belt except the pick ROI) | pick-zone ROI (`camera.pick_roi`) |
| What | shape + color class, position, track id, confidence | shape, color, **size**, **marks**, verdict, **destination bin**, **pick pose** |
| Topic | `/camera/detections` | `/camera/inspection_result` |
| Used for | knowing there are pieces → run the belt; giving an idea of what is coming | sorting + robot picking |

## 5.2 Classification rules (`quality_cell/core/classifier.py`)

1. **Color** — the average RGB of the piece is converted to HSV.
   * saturation < `min_saturation` or value < `min_value` → `UNKNOWN` (grey, black, white…)
   * hue inside a window of `classification.colors` → `RED` / `GREEN` / `BLUE`
   * otherwise `UNKNOWN` (yellow, orange, purple…)

   | Color | Hue window (deg) |
   |---|---|
   | RED | 0–15 and 345–360 |
   | GREEN | 90–150 |
   | BLUE | 200–255 |

2. **Size** — OK if `|size − 42| ≤ 2` mm (`pieces.nominal_size_mm`, `pieces.size_tolerance_mm`).
   An unknown shape counts as a geometric (size) defect.
3. **Marks** — any mark detected → defect `MARKED`.
4. **Verdict** — no defect → `OK`, bin `BIN_<COLOR>_<SHAPE>`. Otherwise `REJECT` and the
   first defect in `defect_priority` decides the reject bin.

## 5.3 Pick pose

With the `opencv` backend the pick pose is the centroid of the piece contour (in mm,
thanks to the calibration) and the orientation of its minimum-area rectangle, averaged
over the inspection frames. (A learned pose model could replace it later.)

With the `sim` backend, `perception.py::SimulatedPerception.estimate_pose` plays that role: it
returns the piece centre (x, y) and yaw in the cell frame with Gaussian noise
(`position_noise_std_mm`, `yaw_noise_std_deg`) and a confidence. Yaw is folded to ±45°
for squares (90° symmetry) and set to 0 for circles. The camera node then converts it to
the robot base frame and sets `pick_z_mm` to the top of the piece.

## 5.4 Simulated perception vs. real perception

The camera node has two backends with the same output:

* `opencv` (default): the **real OpenCV pipeline** (`quality_cell/core/vision.py`) on
  images — from the USB camera, or rendered from the simulator for testing.
* `sim`: simulator ground truth + Gaussian noise (`perception.py`), no images.

Both feed the same `classifier.py`. The pipeline, its accuracy, the camera set-up,
calibration and tuning are described in [14_camera_vision.md](14_camera_vision.md).

Continue with [06_simulation_and_dashboard.md](06_simulation_and_dashboard.md).
