"""Synthetic overhead camera - SIMULATION ONLY.

Renders the simulator ground truth (/sim/world_state) as a camera image:
belt with moving slats, the pieces with their colour and surface marks,
perspective (the camera is not perfectly above the belt), uneven lighting,
blur and noise. The REAL OpenCV pipeline (vision.py) then has to find the
pieces in it, exactly as it will with the real camera.

It also returns the exact image -> cell homography, which plays the role of
the calibration file in simulation.
"""
import math

import cv2
import numpy as np

CANVAS_PX_PER_MM = 3.0
CANVAS = {'x_min': -40.0, 'x_max': 940.0, 'y_min': -90.0, 'y_max': 90.0}


class SimCameraRenderer:
    def __init__(self, cfg, seed=0):
        self.cfg = cfg
        r = cfg['camera']['render']
        self.w, self.h = r['image_size']
        self.noise, self.blur, self.grad = r['noise_std'], r['blur_px'], r['light_gradient']
        L, W = cfg['conveyor']['length_mm'], cfg['conveyor']['width_mm']
        self.L, self.W = L, W
        cell = np.float32([[0, -W / 2], [L, -W / 2], [L, W / 2], [0, W / 2]])
        img = np.float32(r['belt_corners_px'])
        self.H_cell_to_img = cv2.getPerspectiveTransform(cell, img).astype(np.float64)
        self.H_img_to_cell = np.linalg.inv(self.H_cell_to_img)
        s = CANVAS_PX_PER_MM
        A = np.array([[s, 0, -CANVAS['x_min'] * s], [0, -s, CANVAS['y_max'] * s], [0, 0, 1.0]])
        self.H_canvas_to_img = self.H_cell_to_img @ np.linalg.inv(A)
        self.cw = int((CANVAS['x_max'] - CANVAS['x_min']) * s)
        self.ch = int((CANVAS['y_max'] - CANVAS['y_min']) * s)
        self.rng = np.random.default_rng(seed)
        xs = np.linspace(1.0 - self.grad, 1.0 + self.grad / 2, self.w, dtype=np.float32)
        ys = np.linspace(1.0, 1.0 - self.grad / 2, self.h, dtype=np.float32)
        # light as uint8 gain (x/200) so the photometric effects stay in fast uint8 maths
        self.light = np.repeat((ys[:, None] * xs[None, :])[:, :, None] * 200.0, 3, axis=2).astype(np.uint8)
        # Pre-computed noise fields (generating Gaussian noise every frame is slow)
        self.noise_bank = [self.rng.normal(0, self.noise, (self.h, self.w, 3)).astype(np.int16)
                           for _ in range(4)] if self.noise > 0 else []
        self.frame_no = 0

    @staticmethod
    def _px(x, y):
        s = CANVAS_PX_PER_MM
        return ((x - CANVAS['x_min']) * s, (CANVAS['y_max'] - y) * s)

    def _poly(self, pts_mm):
        return np.array([self._px(x, y) for x, y in pts_mm], np.float32)

    def render(self, pieces, belt_pos_mm):
        """pieces: iterable with shape, size_mm, x_mm, y_mm, yaw_deg, r, g, b, mark, location."""
        s = CANVAS_PX_PER_MM
        shift = 4                                    # sub-pixel drawing precision
        f = float(1 << shift)
        L, W = self.L, self.W
        if getattr(self, '_bg', None) is None:
            bg = np.full((self.ch, self.cw, 3), (95, 88, 80), np.uint8)          # table
            cv2.fillPoly(bg, [np.int32(self._poly([(0, -W / 2), (L, -W / 2), (L, W / 2), (0, W / 2)]))],
                         (58, 56, 54))                                          # belt
            for yy in (W / 2 + 6, -W / 2 - 6):                                    # side rails
                cv2.fillPoly(bg, [np.int32(self._poly([(-20, yy - 5), (L + 20, yy - 5),
                                                       (L + 20, yy + 5), (-20, yy + 5)]))],
                             (150, 150, 150))
            self._bg = bg
        cv = self._bg.copy()
        off = belt_pos_mm % 40.0
        x = off
        while x < L:
            p1, p2 = self._px(x, W / 2), self._px(x, -W / 2)
            cv2.line(cv, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), (66, 64, 62), int(4 * s / 3))
            x += 40.0
        # pieces on the belt
        for p in pieces:
            if p.location != 'BELT':
                continue
            color = (int(p.b), int(p.g), int(p.r))
            a = math.radians(p.yaw_deg)
            ca, sa = math.cos(a), math.sin(a)

            def tr(u, v, p=p, ca=ca, sa=sa):        # piece frame (mm) -> canvas px
                return self._px(p.x_mm + ca * u - sa * v, p.y_mm + sa * u + ca * v)

            hs = p.size_mm / 2
            if p.shape == 'CIRCLE':
                c = self._px(p.x_mm, p.y_mm)
                cv2.circle(cv, (int(c[0] * f), int(c[1] * f)), int(hs * s * f), color, -1,
                           cv2.LINE_AA, shift)
            else:
                pts = np.array([tr(-hs, -hs), tr(hs, -hs), tr(hs, hs), tr(-hs, hs)])
                cv2.fillPoly(cv, [np.int32(pts * f)], color, cv2.LINE_AA, shift)
            self._mark(cv, p, tr, s)
        img = cv2.warpPerspective(cv, self.H_canvas_to_img, (self.w, self.h),
                                  flags=cv2.INTER_AREA, borderValue=(40, 40, 40))
        img = cv2.multiply(img, self.light, scale=1.0 / 200.0)
        if self.noise_bank:
            self.frame_no += 1
            n = self.noise_bank[self.frame_no % len(self.noise_bank)]
            img = cv2.add(img.astype(np.int16), np.roll(n, int(self.rng.integers(0, 64)), axis=1))
            img = np.clip(img, 0, 255).astype(np.uint8)
        if self.blur:
            k = 2 * int(self.blur) + 1
            img = cv2.GaussianBlur(img, (k, k), 0)
        return img

    def _mark(self, cv, p, tr, s):
        m, q = p.mark, p.size_mm * 0.25
        if not m or m == 'NONE':
            return
        dark = (25, 25, 25)
        th = max(1, int(round(p.size_mm * 0.07 * s)))

        def ln(a, b, t=th):
            pa, pb = tr(*a), tr(*b)
            cv2.line(cv, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])), dark, t, cv2.LINE_AA)
        if m == 'CROSS':
            ln((-q, -q), (q, q))
            ln((q, -q), (-q, q))
        elif m == 'SMILEY':
            for ex in (-0.6 * q, 0.6 * q):
                c = tr(ex, 0.4 * q)
                cv2.circle(cv, (int(c[0]), int(c[1])), max(2, int(p.size_mm * 0.05 * s)), dark, -1)
            prev = None
            for k in range(13):
                ang = math.radians(200 + k * 140 / 12)
                pt = (0.9 * q * math.cos(ang), 0.9 * q * math.sin(ang))
                if prev:
                    ln(prev, pt)
                prev = pt
        elif m == 'SCRATCH':
            prev = (-1.3 * q, 0.6 * q)
            for i in range(1, 7):
                pt = (-1.3 * q + i * 0.45 * q, 0.6 * q - (0.35 * q if i % 2 else 0) - i * 0.12 * q)
                ln(prev, pt, max(1, th // 2))
                prev = pt
        elif m == 'DOT':
            c = tr(0.4 * q, -0.3 * q)
            cv2.circle(cv, (int(c[0]), int(c[1])), max(2, int(p.size_mm * 0.08 * s)), dark, -1)
        elif m == 'GROOVE':
            ln((-p.size_mm * 0.45, -0.1 * p.size_mm), (p.size_mm * 0.45, 0.05 * p.size_mm))
