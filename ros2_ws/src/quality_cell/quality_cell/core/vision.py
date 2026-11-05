"""REAL vision pipeline (OpenCV) - works on camera images, no ROS inside.

Used by camera_node.py when `camera.backend: opencv`. The same code runs on
images from a USB camera or on images rendered by the simulator
(sim_renderer.py), so it can be developed and tested without hardware.

Pipeline
--------
 1. RECTIFY   image --homography--> top view of the belt in millimetres
              (rectified image: 1 px = 1/px_per_mm mm, axes = CELL frame)
 2. SEGMENT   foreground = saturated pixels OR pixels far from the belt
              brightness (belt = median of the image); morphology; holes filled
 3. CONTOURS  one external contour per piece; area filter (touching pieces ignored)
 4. MEASURE   per piece:
                shape  : fill ratio = area / min-area-rectangle  (square ~1, circle ~pi/4)
                size   : circle -> diameter from area; square -> mean side of the rectangle
                colour : median RGB of the inner region (edges removed)
                marks  : inner pixels whose Lab colour is far from the piece colour
                pose   : centroid (mm) + rectangle angle (yaw, folded to +-45 deg for squares)
 5. CLASSIFY  done by classifier.py (same as the simulated backend)

All tunable numbers are in cell_config.yaml -> camera.vision.
"""
import math

import cv2
import numpy as np

from quality_cell.core.classifier import classify_color


def rect_matrix(region, px_per_mm):
    """CELL mm -> rectified pixel. Columns grow with +X, rows grow with -Y."""
    s = px_per_mm
    return np.array([[s, 0.0, -region['x_min'] * s],
                     [0.0, -s, region['y_max'] * s],
                     [0.0, 0.0, 1.0]])


class BeltVision:
    def __init__(self, cfg, H_img_to_cell):
        self.cfg = cfg
        self.v = cfg['camera']['vision']
        self.H = np.asarray(H_img_to_cell, dtype=np.float64)
        self.H_cell_to_img = np.linalg.inv(self.H)
        self.prev_gray = None

    # ------------------------------------------------------------------ geometry
    def rectify(self, img, region, s):
        M = rect_matrix(region, s) @ self.H
        w = int(round((region['x_max'] - region['x_min']) * s))
        h = int(round((region['y_max'] - region['y_min']) * s))
        return cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_LINEAR)

    def cell_to_img(self, pts):
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(p, self.H_cell_to_img).reshape(-1, 2)

    # ------------------------------------------------------------------ segmentation
    def segment(self, rect_bgr, s):
        hsv = cv2.cvtColor(rect_bgr, cv2.COLOR_BGR2HSV)
        sat, val = hsv[:, :, 1], hsv[:, :, 2]
        belt_v = int(np.median(val[::4, ::4]))     # the belt covers most of the image
        fg = (sat > int(self.v['min_saturation'] * 255)) & (val > 30)
        fg |= cv2.absdiff(val, np.full_like(val, belt_v)) > int(self.v['belt_value_delta'] * 255)
        mask = fg.astype(np.uint8) * 255
        k = max(1, int(round(s)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k + 1, k + 1), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2 * k + 1, 2 * k + 1), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        sub_bgr, sub_mask = rect_bgr[::4, ::4], mask[::4, ::4]     # belt colour (Lab), subsampled
        bg = sub_bgr[sub_mask == 0]
        if len(bg) == 0:
            bg = sub_bgr.reshape(-1, 3)
        self._belt_lab = self.lab(np.median(bg, axis=0).reshape(1, 1, 3).astype(np.uint8))[0, 0]
        self._rect = rect_bgr
        return contours, belt_v / 255.0

    @staticmethod
    def lab(bgr):
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)

    def refine(self, contour, shape_hw):
        """Sub-pixel-ish edge: re-threshold the blob at 50 % between the belt colour and
        the piece colour. A blurred edge is then measured in the middle of the ramp, so the
        size does not grow with blur / defocus (the first mask is deliberately generous)."""
        h_img, w_img = shape_hw
        x, y, w, h = cv2.boundingRect(contour)
        m = 6
        x0, y0, x1, y1 = max(0, x - m), max(0, y - m), min(w_img, x + w + m), min(h_img, y + h + m)
        blob = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.drawContours(blob, [contour], -1, 255, cv2.FILLED, offset=(-x0, -y0))
        core = cv2.erode(blob, np.ones((7, 7), np.uint8))
        lab = self.lab(self._rect[y0:y1, x0:x1])
        if cv2.countNonZero(core) < 20:
            return contour
        piece = np.median(lab[core > 0], axis=0)
        d = piece - self._belt_lab
        nd = float(d @ d)
        if nd < 100.0:                      # piece colour too close to the belt: keep as is
            return contour
        t = ((lab - self._belt_lab) @ d) / nd
        m50 = ((t > 0.5) & (cv2.dilate(blob, np.ones((5, 5), np.uint8)) > 0)).astype(np.uint8) * 255
        cs, _ = cv2.findContours(m50, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not cs:
            return contour
        # A dark mark (groove, scratch) may cut the piece in two at 50 %: the pieces are
        # CONVEX (circle / square), so take the convex hull of all the fragments.
        pts = np.vstack([c for c in cs if cv2.contourArea(c) > 10] or [max(cs, key=cv2.contourArea)])
        hull = cv2.convexHull(pts)
        return hull + np.array([[[x0, y0]]], dtype=hull.dtype)

    def measure(self, rect_bgr, contour, s, region, inspect):
        h_img, w_img = rect_bgr.shape[:2]
        contour = self.refine(contour, (h_img, w_img))
        area_mm2 = cv2.contourArea(contour) / (s * s)
        if not (self.v['min_area_mm2'] <= area_mm2 <= self.v['max_area_mm2']):
            return None
        x, y, w, h = cv2.boundingRect(contour)
        partial = x <= 1 or y <= 1 or x + w >= w_img - 1 or y + h >= h_img - 1

        (cx, cy), (rw, rh), ang = cv2.minAreaRect(contour)
        fill = cv2.contourArea(contour) / max(rw * rh, 1e-6)
        lo, hi = self.v['circle_fill_range']
        if fill >= self.v['square_fill_min']:
            shape = 'SQUARE'
            size = (rw + rh) / 2.0 / s
        elif lo <= fill <= hi:
            shape = 'CIRCLE'
            size = 2.0 * math.sqrt(area_mm2 / math.pi)
        else:
            shape = 'UNKNOWN'
            size = math.sqrt(area_mm2)

        size += self.v.get('size_correction_mm', {}).get(shape, 0.0)

        m = cv2.moments(contour)
        px, py = m['m10'] / m['m00'], m['m01'] / m['m00']
        x_mm = region['x_min'] + px / s
        y_mm = region['y_max'] - py / s
        # image rows go DOWN (= -Y): a CCW rotation in the cell is CW in the image
        yaw = -ang
        if shape == 'SQUARE':
            yaw = ((yaw + 45.0) % 90.0) - 45.0
        else:
            yaw = 0.0

        # inner region (without the anti-aliased / shadowed border), on a crop for speed
        x0, y0 = max(0, x - 2), max(0, y - 2)
        x1, y1 = min(w_img, x + w + 2), min(h_img, y + h + 2)
        full = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.drawContours(full, [contour], -1, 255, cv2.FILLED, offset=(-x0, -y0))
        margin = max(1, int(round(self.v['edge_margin_mm'] * s)))
        inner = cv2.erode(full, np.ones((2 * margin + 1, 2 * margin + 1), np.uint8))
        if cv2.countNonZero(inner) < 20:
            inner = full
        crop = rect_bgr[y0:y1, x0:x1]
        pix = crop[inner > 0]
        b, g, r = np.median(pix, axis=0)
        rgb = (float(r), float(g), float(b))

        res = {'shape': shape, 'size_mm': size, 'area_mm2': area_mm2, 'fill': fill,
               'x_mm': x_mm, 'y_mm': y_mm, 'yaw_deg': yaw, 'rgb': rgb,
               'color': classify_color(rgb, self.cfg['classification']),
               'partial': partial, 'contour': contour}
        if inspect:
            res.update(self.find_marks(self.lab(crop), inner, s))
        return res

    def find_marks(self, lab, inner, s):
        ref = np.median(lab[inner > 0], axis=0)
        dist = np.linalg.norm(lab - ref, axis=2)
        defect = ((dist > self.v['mark_color_distance']) & (inner > 0)).astype(np.uint8)
        defect = cv2.morphologyEx(defect, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(defect)
        areas = [stats[i, cv2.CC_STAT_AREA] / (s * s) for i in range(1, n)]
        biggest = max(areas) if areas else 0.0
        detected = biggest >= self.v['mark_min_area_mm2']
        return {'mark_detected': detected, 'mark_area_mm2': float(sum(areas)),
                'mark_type': 'MARK' if detected else 'NONE', 'mark_mask': defect}

    # ------------------------------------------------------------------ public API
    def detect(self, img, region):
        """Fast detection of all pieces in `region` (CELL frame box)."""
        s = self.v['detect_px_per_mm']
        rect = self.rectify(img, region, s)
        contours, _ = self.segment(rect, s)
        out = [self.measure(rect, c, s, region, inspect=False) for c in contours]
        return [o for o in out if o is not None]

    def inspect(self, img, region):
        """Careful inspection of the pieces in `region` (the pick ROI)."""
        s = self.v['inspect_px_per_mm']
        rect = self.rectify(img, region, s)
        contours, _ = self.segment(rect, s)
        out = [self.measure(rect, c, s, region, inspect=True) for c in contours]
        return [o for o in out if o is not None], rect

    def belt_motion(self, img, region):
        """Camera-only estimate of belt motion.

        The rectified belt is averaged across its width -> a 1-D brightness profile
        along X (seams, slats, dirt). Averaging removes the pixel noise, so a shift of
        the profile between two frames means the belt surface moved. (Pieces moving
        also count: a moving piece is a moving belt.)"""
        gray = cv2.cvtColor(self.rectify(img, region, 1.0), cv2.COLOR_BGR2GRAY).astype(np.float32)
        profile = gray.mean(axis=0)
        moving = False
        if self.prev_gray is not None and self.prev_gray.shape == profile.shape:
            moving = float(np.mean(np.abs(profile - self.prev_gray))) > self.v['motion_threshold']
        self.prev_gray = profile
        return moving


class SimpleTracker:
    """Gives stable ids to pieces between frames. Pieces only move along +X."""

    def __init__(self, max_jump_mm=60.0, forget_s=1.5):
        self.tracks = {}            # id -> (x, y, t)
        self.next_id = 1
        self.max_jump, self.forget = max_jump_mm, forget_s

    def update(self, dets, now):
        used = set()
        for d in sorted(dets, key=lambda q: -q['x_mm']):
            best, best_cost = None, 1e9
            for tid, (x, y, _) in self.tracks.items():
                dx, dy = d['x_mm'] - x, d['y_mm'] - y
                if tid in used or abs(dy) > 15.0 or dx < -10.0 or dx > self.max_jump:
                    continue
                cost = abs(dx) + 2 * abs(dy)
                if cost < best_cost:
                    best, best_cost = tid, cost
            if best is None:
                best = self.next_id
                self.next_id += 1
            used.add(best)
            self.tracks[best] = (d['x_mm'], d['y_mm'], now)
            d['track_id'] = best
        self.tracks = {k: v for k, v in self.tracks.items() if now - v[2] < self.forget}
        return dets
