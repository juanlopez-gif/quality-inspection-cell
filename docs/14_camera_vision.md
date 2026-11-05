# 14. Camera and vision pipeline (OpenCV)

The camera node has two perception backends (`camera.backend` in `cell_config.yaml`,
or the launch argument `camera_backend:=`):

| Backend | What it uses | When |
|---|---|---|
| `opencv` (**default**) | The **real vision pipeline** (`quality_cell/core/vision.py`) on camera **images** | Always, for the real cell. In simulation it runs on images **rendered** from the simulator |
| `sim` | Simulator ground truth + noise (`perception.py`), no images | Fast tests of the supervisor logic, low CPU |

With `opencv`, the image source (`camera.source` or `camera_source:=`) is:

| Source | Meaning |
|---|---|
| `sim_render` | Synthetic camera: the simulator draws the belt and pieces as a camera would see them (perspective, uneven light, noise, blur) — `sim_renderer.py` |
| `0`, `1`, … / `/dev/video2` | USB camera (OpenCV, V4L2 backend) |
| `rtsp://…`, `file.mp4` | anything `cv2.VideoCapture` opens (IP camera, recorded video) |

**The same pipeline code runs in simulation and on the real camera.** In simulation it is
tested against the ground truth: `test/test_vision.py` renders every combination of
shape × colour × size × mark at random positions and rotations and checks that the piece
ends up in the right bin (180 cases + tracking + belt motion).

---

## 14.1 The pipeline step by step (`vision.py`)

```
 camera image ──► 1 RECTIFY ──► 2 SEGMENT ──► 3 CONTOURS ──► 4 MEASURE ──► 5 CLASSIFY
  (perspective)    top view       foreground     one per        shape, size,     classifier.py
                   in mm          mask           piece          colour, marks,   → verdict + bin
                                                                pose
```

1. **Rectify.** The calibration homography maps image pixels to the belt plane in mm.
   `cv2.warpPerspective` produces a *top view* of the belt where 1 px = 1/`px_per_mm` mm
   and the axes are the CELL frame. From here on everything is measured in millimetres,
   so the perspective of the camera does not matter.
   Detection uses 2 px/mm (whole belt, fast); the final inspection 4 px/mm (pick ROI only).
2. **Segment.** Foreground = pixels that are **saturated** (coloured pieces) **or** much
   brighter/darker than the belt (belt brightness = median of the image, since the belt
   covers most of it). Opening removes noise, closing fills small gaps.
3. **Contours.** External contours only (marks inside the piece do not create holes).
   Blobs smaller than `min_area_mm2` (dirt) or larger than `max_area_mm2` (two touching
   pieces) are ignored. Blobs touching the image border are flagged `partial`.
4. **Measure.**
   * **Edge refinement**: the blob is re-thresholded at **50 % between the belt colour and
     the piece colour** (in Lab). A blurred edge is then cut in the middle of the ramp, so
     the size does not grow with blur or defocus. Because pieces are convex, the convex
     hull of the fragments is used (a groove that cuts the piece in two does not matter).
   * **Shape**: fill ratio = area / area of the minimum-area rectangle. Square ≈ 1.0,
     circle ≈ π/4 = 0.785. Anything else → `UNKNOWN`.
   * **Size**: circle → diameter from the area (2√(A/π)); square → mean side of the
     rectangle. Plus `size_correction_mm` (systematic camera error, see 14.4).
   * **Colour**: **median** RGB of the inner region (border of `edge_margin_mm` removed).
     The median ignores marks and highlights. → `classify_color` (HSV hue windows).
   * **Marks**: inner pixels whose Lab colour is farther than `mark_color_distance` from
     the piece colour; connected groups larger than `mark_min_area_mm2` = a mark. It
     detects any kind of mark (cross, smiley, scratch, dot, groove…) without knowing its
     shape, which is exactly the requirement. `mark_type` is reported as `MARK`.
   * **Pose**: centroid (image moments) in mm, and yaw from the rectangle angle (folded to
     ±45° for squares, 0 for circles). The camera node converts it to the UR base frame.
5. **Classify**: `classifier.py`, the same rules as with the simulated backend.

### Final inspection
On `INSPECT` the node measures the piece in the pick ROI on `inspect_frames` (3)
consecutive frames and combines them: majority vote for shape and mark, **median** for
size, colour and position. This rejects a single bad frame (reflection, hand in the image…).
If no piece is found in 12 frames the result is `success=false, NO_PIECE` and the
supervisor retries (rule R7).

### Tracking and belt motion
* `SimpleTracker` gives each piece a stable `track_id`: pieces only move along +X, so a
  detection is matched to the closest previous track slightly behind it.
* Belt motion is estimated from the image alone: the rectified belt is averaged across
  its width into a 1-D brightness profile; if the profile changes between frames, the
  belt surface moved. Needs some texture on the belt (seams, marks); tune
  `motion_threshold`.

### Debug image
`/camera/debug_image` (`sensor_msgs/CompressedImage`, JPEG, 5 Hz) shows the camera image
with the FOV, the pick ROI, every detected contour (green = known colour, red = unknown
colour), its id, class and size, and the last inspection result. The dashboard shows it
under the cell view ("What the camera sees"). From a terminal: `ros2 topic hz /camera/debug_image`.

---

## 14.2 Measured performance (synthetic camera, 1280×720, ~1.3 px/mm on the belt)

| Test | Result |
|---|---|
| 720 inspections (2 shapes × 6 colours × 5 sizes × 6 marks × 2, random pose) | **720 / 720 in the right bin** |
| Size error | mean 0.09 mm, max 0.34 mm |
| Position error | < 0.2 mm |
| Same with noise ×2.5, stronger blur, 35 % light gradient | 720 / 720, size error max 0.35 mm |
| 10 random pieces through the whole running cell (camera → supervisor → robot) | 10 / 10 in the right bin |
| CPU | ~20 ms render + ~22 ms detection per frame (10 Hz ≈ ½ core) |

Real images are harder (reflections, shadows, lens distortion, colour casts): expect to
re-tune thresholds with your camera. See 14.5.

---

## 14.3 Setting up the real camera

1. **Mounting.** Above the belt, looking down, the whole belt (or at least the transport
   zone + pick ROI) in view. Fixed, rigid mount: if the camera moves, re-calibrate.
2. **Lighting.** Diffuse, constant light (LED panel / ring light). Avoid windows and
   direct spotlights (reflections on the pieces look like marks). Turn off camera
   auto-white-balance / auto-exposure if possible (`v4l2-ctl`).
3. **Belt colour.** The belt must contrast with the pieces. A dark grey / black belt works
   with red, green, blue (and the reject colours). A grey piece on a grey belt cannot be
   segmented.
4. **Resolution.** 1280×720 over a 900 mm belt gives ~1.4 px/mm (a 42 mm piece ≈ 60 px).
   Enough for ±2 mm. For finer tolerances or small marks: zoom on the pick ROI or add a
   second camera only for the ROI.
5. **Lens distortion.** A wide-angle webcam bends straight lines, and a homography cannot
   fix that. Check the rectified preview of the calibration tool: if the belt edges are
   curved, calibrate the intrinsics first (`cv2.calibrateCamera` with a checkerboard) and
   undistort, or use a camera with a less distorting lens.

### Calibration (image → cell homography)

```bash
# markers.txt: CELL coordinates (mm) of 4+ small marks stuck on the belt surface
0    -50
900  -50
900   50
0     50
450    0

python3 tools/calibrate_camera.py --points markers.txt --source 0 --out camera_calibration.yaml
#   click the marks in the same order, Enter -> error per mark (< 1 mm is good) + rectified preview
```

Then in `cell_config.yaml`:

```yaml
camera:
  backend: opencv
  source: 0                     # or /dev/video2
  calibration_file: /home/<user>/Desktop/quality_inspection_cell/camera_calibration.yaml
  capture: {width: 1280, height: 720, fps: 30}   # same resolution as the calibration!
```

The node checks that the image size equals the calibration size and logs an error if
not. Also set `camera.pick_roi` around the IR sensor so the stopped piece is fully inside.

### Size correction
Place a reference piece of known size (e.g. a good 42.0 mm square, measured with a
caliper) in the pick ROI, trigger an inspection and read the measured size (dashboard
"Last final inspection"). Do it for a circle and a square:

```yaml
size_correction_mm: {CIRCLE: <true - measured>, SQUARE: <true - measured>}
```

---

## 14.4 Tuning guide (`camera.vision`)

| Symptom | Parameter |
|---|---|
| Pieces not detected / partly detected | lower `min_saturation`, lower `belt_value_delta`; check light |
| Belt texture / dirt detected as pieces | raise `min_area_mm2`, raise `belt_value_delta` |
| Clean pieces rejected as MARKED (reflections) | raise `mark_color_distance` or `mark_min_area_mm2`; diffuse the light |
| Small marks missed | lower `mark_min_area_mm2` / `mark_color_distance`; more px/mm (zoom) |
| Colour at the edge of a hue window | adjust `classification.colors` with real measurements (print the median RGB) |
| Squares classified as circles or vice-versa | `square_fill_min`, `circle_fill_range` |
| Sizes all too big/small by the same amount | `size_correction_mm` |
| Belt reported as still while moving | lower `motion_threshold` (or add marks to the belt) |

Quick offline test on a saved frame:

```python
import cv2, yaml, numpy as np
from quality_cell.core.cell_config import load_config
from quality_cell.core.vision import BeltVision
cfg = load_config('ros2_ws/src/quality_cell/config/cell_config.yaml')
H = np.array(yaml.safe_load(open('camera_calibration.yaml'))['homography_img_to_cell'])
V = BeltVision(cfg, H)
img = cv2.imread('frame.png')
for d in V.inspect(img, cfg['camera']['pick_roi'])[0]:
    print(d['shape'], d['color'], round(d['size_mm'], 2), d['mark_detected'], d['rgb'])
```

---

## 14.5 Limitations (good topics for the students)

* Touching pieces are one blob → ignored (size filter). Operators must leave a gap.
* `mark_type` is not classified (only "there is a mark"): classifying cross / smiley /
  scratch would need a trained model (e.g. a small CNN on crops of the ROI).
* Flat-belt assumption: the homography is exact only on the belt plane. Pieces are 6 mm
  thick, which shifts their top slightly away from the image centre — included in the
  size correction for the ROI.
* Specular pieces (glossy plastic) under a point light produce white spots → false marks.
* Colours depend on light: re-check hue windows when the light changes.
