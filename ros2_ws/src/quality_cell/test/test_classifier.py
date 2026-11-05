"""Unit tests of the classification rules (no ROS needed):  python3 -m pytest test/"""
import os

from quality_cell.core.cell_config import load_config
from quality_cell.core.classifier import classify, classify_color

CFG = load_config(os.path.join(os.path.dirname(__file__), '..', 'config', 'cell_config.yaml'))
C = CFG['classification']


def test_basic_colors():
    assert classify_color((220, 30, 30), C) == 'RED'
    assert classify_color((30, 180, 60), C) == 'GREEN'
    assert classify_color((30, 70, 220), C) == 'BLUE'


def test_unknown_colors():
    assert classify_color((240, 220, 30), C) == 'UNKNOWN'   # yellow
    assert classify_color((240, 140, 20), C) == 'UNKNOWN'   # orange
    assert classify_color((140, 40, 200), C) == 'UNKNOWN'   # purple
    assert classify_color((120, 120, 120), C) == 'UNKNOWN'  # grey (low saturation)


def test_good_piece_goes_to_its_bin():
    d = classify('SQUARE', (30, 70, 220), 42.3, False, CFG)
    assert d['verdict'] == 'OK' and d['destination_bin'] == 'BIN_BLUE_SQUARE'


def test_wrong_size():
    d = classify('CIRCLE', (220, 30, 30), 35.0, False, CFG)
    assert d['defect'] == 'WRONG_SIZE' and d['destination_bin'] == 'BIN_REJECT_SIZE'


def test_marked():
    d = classify('CIRCLE', (220, 30, 30), 42.0, True, CFG)
    assert d['defect'] == 'MARKED' and d['destination_bin'] == 'BIN_REJECT_MARKED'


def test_priority_with_several_defects():
    d = classify('SQUARE', (240, 220, 30), 30.0, True, CFG)   # marked + yellow + small
    assert set(d['defects']) == {'MARKED', 'WRONG_COLOR', 'WRONG_SIZE'}
    assert d['destination_bin'] == 'BIN_REJECT_MARKED'
    d = classify('SQUARE', (240, 220, 30), 30.0, False, CFG)  # yellow + small
    assert d['destination_bin'] == 'BIN_REJECT_COLOR'
