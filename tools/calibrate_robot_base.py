#!/usr/bin/env python3
"""Compute camera.robot_base_in_cell (x, y, yaw_deg) from touched points.

Procedure (see docs/13):
  1. Put 3 or more marks on the belt / table whose CELL coordinates you know
     (e.g. measured from the belt start: (200, 0), (700, 40), (700, -40)).
  2. Jog the UR7e so the suction-cup tip touches each mark and read X, Y of the
     TCP on the teach pendant (feature: Base, units mm).
  3. Write the pairs in a text file, one per line:   cell_x cell_y robot_x robot_y
  4. python3 tools/calibrate_robot_base.py points.txt

Fits the 2-D rigid transform  p_cell = R(yaw) * p_robot + t  by least squares.
"""
import math
import sys


def fit(pairs):
    n = len(pairs)
    cx = sum(p[0] for p in pairs) / n
    cy = sum(p[1] for p in pairs) / n
    rx = sum(p[2] for p in pairs) / n
    ry = sum(p[3] for p in pairs) / n
    s_cos = s_sin = 0.0
    for X, Y, x, y in pairs:
        a, b = x - rx, y - ry            # robot, centred
        c, d = X - cx, Y - cy            # cell, centred
        s_cos += a * c + b * d
        s_sin += a * d - b * c
    yaw = math.atan2(s_sin, s_cos)
    tx = cx - (math.cos(yaw) * rx - math.sin(yaw) * ry)
    ty = cy - (math.sin(yaw) * rx + math.cos(yaw) * ry)
    err = []
    for X, Y, x, y in pairs:
        px = math.cos(yaw) * x - math.sin(yaw) * y + tx
        py = math.sin(yaw) * x + math.cos(yaw) * y + ty
        err.append(math.hypot(px - X, py - Y))
    return tx, ty, math.degrees(yaw), err


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    pairs = []
    for line in open(sys.argv[1]):
        line = line.split('#')[0].strip()
        if line:
            pairs.append(tuple(float(v) for v in line.split()))
    if len(pairs) < 3:
        sys.exit('Need at least 3 point pairs')
    tx, ty, yaw, err = fit(pairs)
    print('robot_base_in_cell: {x: %.1f, y: %.1f, z: 0.0, yaw_deg: %.2f}' % (tx, ty, yaw))
    print('  (z: touch the belt surface with the cup tip and use z = -Z shown on the pendant)')
    print('residuals (mm): ' + ', '.join('%.2f' % e for e in err))
    if max(err) > 3.0:
        print('WARNING: residual > 3 mm: re-check the points (TCP set to the cup tip?)')
