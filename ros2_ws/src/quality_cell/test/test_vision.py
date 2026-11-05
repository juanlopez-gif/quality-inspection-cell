"""Tests of the REAL OpenCV pipeline (vision.py) on images from the synthetic camera.

Every combination of shape / colour / size / mark is rendered at a random pose
in the pick ROI and must end in the right bin. Run: ./test.sh
"""
import itertools
import os
import random
import types

import pytest

from quality_cell.core.cell_config import load_config
from quality_cell.core.classifier import classify
from quality_cell.core.sim_renderer import SimCameraRenderer
from quality_cell.core.vision import BeltVision, SimpleTracker

CFG = load_config(os.path.join(os.path.dirname(__file__), '..', 'config', 'cell_config.yaml'))
COL = {'RED': (220, 45, 45), 'GREEN': (40, 170, 75), 'BLUE': (40, 95, 225),
       'YELLOW': (235, 205, 40), 'PURPLE': (140, 60, 200)}


def piece(shape, color, size, mark, x, y, yaw):
    r, g, b = COL[color]
    return types.SimpleNamespace(shape=shape, size_mm=size, x_mm=x, y_mm=y, yaw_deg=yaw,
                                 r=r, g=g, b=b, mark=mark, location='BELT')


@pytest.fixture(scope='module')
def cam():
    R = SimCameraRenderer(CFG, seed=7)
    return R, BeltVision(CFG, R.H_img_to_cell)


CASES = list(itertools.product(['CIRCLE', 'SQUARE'], COL, [36.0, 42.0, 48.0],
                               ['NONE', 'CROSS', 'SMILEY', 'SCRATCH', 'DOT', 'GROOVE']))


@pytest.mark.parametrize('shape,color,size,mark', CASES)
def test_inspection_bin(cam, shape, color, size, mark):
    R, V = cam
    rng = random.Random(hash((shape, color, size, mark)) & 0xffff)
    p = piece(shape, color, size, mark, 760 + rng.uniform(-8, 8), rng.uniform(-20, 20), rng.uniform(0, 90))
    found, _ = V.inspect(R.render([p], rng.uniform(0, 300)), CFG['camera']['pick_roi'])
    assert len(found) == 1
    d = found[0]
    assert d['shape'] == shape
    assert abs(d['size_mm'] - size) < 0.8
    assert abs(d['x_mm'] - p.x_mm) < 1.0 and abs(d['y_mm'] - p.y_mm) < 1.0
    truth = classify(shape, COL[color], size, mark != 'NONE', CFG)['destination_bin']
    assert classify(d['shape'], d['rgb'], d['size_mm'], d['mark_detected'], CFG)['destination_bin'] == truth


def test_detection_and_tracking(cam):
    R, V = cam
    tr = SimpleTracker()
    ids = None
    for k in range(5):                                    # pieces move 8 mm per frame
        ps = [piece('SQUARE', 'RED', 42, 'NONE', 150 + 8 * k, 0, 10),
              piece('CIRCLE', 'BLUE', 42, 'NONE', 400 + 8 * k, 20, 0)]
        dets = tr.update(V.detect(R.render(ps, 8 * k), CFG['camera']['fov']), k * 0.1)
        assert sorted((d['shape'], d['color']) for d in dets) == [('CIRCLE', 'BLUE'), ('SQUARE', 'RED')]
        now = sorted(d['track_id'] for d in dets)
        assert ids is None or now == ids                  # same ids frame after frame
        ids = now


def test_belt_motion(cam):
    R, V = cam
    V.prev_gray = None
    V.belt_motion(R.render([], 0.0), CFG['camera']['fov'])
    assert V.belt_motion(R.render([], 9.0), CFG['camera']['fov'])          # slats moved
    V.belt_motion(R.render([], 9.0), CFG['camera']['fov'])
    assert not V.belt_motion(R.render([], 9.0), CFG['camera']['fov'])      # still
