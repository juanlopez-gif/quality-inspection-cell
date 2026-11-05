#!/usr/bin/env python3
"""Camera calibration: image pixels -> CELL plane (millimetres) homography.

The vision pipeline needs to know where each pixel is on the belt plane. A
homography (3x3 matrix) does it for a flat belt, including the perspective of
a camera that is not exactly above the belt.

1. Put 4 or more small markers ON THE BELT SURFACE at known CELL coordinates
   (mm, origin = belt start on its centre line, X along travel, Y to the left).
   Spread them over the whole belt, e.g. the 4 corners of the camera FOV:
       0 -50     900 -50     900 50     0 50
   Write them in a text file, one "x y" per line (order matters).
2. Run (USB camera 0, or a saved image):
       python3 tools/calibrate_camera.py --points markers.txt --source 0
       python3 tools/calibrate_camera.py --points markers.txt --image frame.png
3. Click the markers IN THE SAME ORDER as in the file. Keys:
       u = undo last click      Enter = compute      q / Esc = quit
4. The result is written to camera_calibration.yaml (or --out). Then set in
   config/cell_config.yaml:
       camera: { backend: opencv, source: 0, calibration_file: /abs/path/camera_calibration.yaml }

The script prints the reprojection error in mm (should be < 1 mm) and shows a
rectified top view of the belt: straight, undistorted edges = good calibration.
Strong lens distortion (wide-angle lens) bends straight lines; then calibrate
the intrinsics first (cv2.calibrateCamera) or use a lens with less distortion.
"""
import argparse
import datetime
import sys

import cv2
import numpy as np
import yaml


def compute(img_pts, cell_pts):
    """Least-squares homography image -> cell, and reprojection errors in mm."""
    img_pts = np.float64(img_pts)
    cell_pts = np.float64(cell_pts)
    H, _ = cv2.findHomography(img_pts, cell_pts, 0)
    proj = cv2.perspectiveTransform(img_pts.reshape(-1, 1, 2), H).reshape(-1, 2)
    err = np.linalg.norm(proj - cell_pts, axis=1)
    return H, err


def save(path, H, err, img_pts, cell_pts, size):
    data = {
        'homography_img_to_cell': [[float(v) for v in row] for row in H],
        'image_size': [int(size[0]), int(size[1])],
        'rms_error_mm': float(np.sqrt(np.mean(err ** 2))),
        'max_error_mm': float(err.max()),
        'image_points_px': [[float(a), float(b)] for a, b in img_pts],
        'cell_points_mm': [[float(a), float(b)] for a, b in cell_pts],
        'created': datetime.datetime.now().isoformat(timespec='seconds'),
    }
    with open(path, 'w') as f:
        f.write('# Made with tools/calibrate_camera.py - image px -> CELL plane mm\n')
        yaml.safe_dump(data, f, sort_keys=False)


def rectified_preview(img, H, x0=-20, x1=920, y0=-80, y1=80, s=1.2):
    A = np.array([[s, 0, -x0 * s], [0, -s, y1 * s], [0, 0, 1.0]])
    return cv2.warpPerspective(img, A @ H, (int((x1 - x0) * s), int((y1 - y0) * s)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--points', required=True, help='text file: one "x_mm y_mm" per marker')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--source', help='camera index or URL (cv2.VideoCapture)')
    g.add_argument('--image', help='image file instead of a live camera')
    ap.add_argument('--out', default='camera_calibration.yaml')
    a = ap.parse_args()

    cell_pts = [tuple(float(v) for v in ln.split('#')[0].split()) for ln in open(a.points)
                if ln.split('#')[0].strip()]
    if len(cell_pts) < 4:
        sys.exit('Need at least 4 markers')
    if a.image:
        frame = cv2.imread(a.image)
    else:
        src = int(a.source) if a.source.isdigit() else a.source
        v4l2 = isinstance(src, int) or str(src).startswith('/dev/video')
        cap = cv2.VideoCapture(src, cv2.CAP_V4L2) if v4l2 else cv2.VideoCapture(src)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        for _ in range(10):                  # let auto-exposure settle
            ok, frame = cap.read()
        if not ok:
            sys.exit('Cannot read from camera %s' % a.source)
    clicks = []

    def on_mouse(ev, x, y, *_):
        if ev == cv2.EVENT_LBUTTONDOWN and len(clicks) < len(cell_pts):
            clicks.append((x, y))
    win = 'calibrate_camera - click the markers in order'
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    while True:
        view = frame.copy()
        for i, (x, y) in enumerate(clicks):
            cv2.drawMarker(view, (x, y), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)
            cv2.putText(view, '%d (%g, %g)' % (i + 1, *cell_pts[i]), (x + 8, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        msg = ('click marker %d at cell (%g, %g) mm' % (len(clicks) + 1, *cell_pts[len(clicks)])
               if len(clicks) < len(cell_pts) else 'all markers clicked: press Enter')
        cv2.putText(view, msg + '   [u]ndo  [Enter] compute  [q]uit', (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow(win, view)
        k = cv2.waitKey(30) & 0xFF
        if k in (ord('q'), 27):
            sys.exit('aborted')
        if k == ord('u') and clicks:
            clicks.pop()
        if k in (13, 10) and len(clicks) == len(cell_pts):
            break
    H, err = compute(clicks, cell_pts)
    for i, e in enumerate(err):
        print('marker %d  error %.2f mm' % (i + 1, e))
    print('RMS error %.2f mm' % np.sqrt(np.mean(err ** 2)))
    save(a.out, H, err, clicks, cell_pts, frame.shape[1::-1])
    print('Saved %s' % a.out)
    cv2.imshow('rectified top view (check straight edges)', rectified_preview(frame, H))
    cv2.waitKey(0)


if __name__ == '__main__':
    main()
