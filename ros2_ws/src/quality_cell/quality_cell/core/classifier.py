"""Classification rules of the cell.

This is the ONLY place where "is the piece good?" and "which bin?" are decided.
It works on *measured features*, so the same code is used with the simulated
camera and with a real OpenCV / ML pipeline.

Features in:
    shape          'CIRCLE' | 'SQUARE' | 'UNKNOWN'
    rgb            (r, g, b) 0..255  - average colour of the piece
    size_mm        measured side / diameter
    mark_detected  bool              - any mark / scratch / drawing on the surface

Decision out (dict):
    color, verdict ('OK'|'REJECT'), defect, defects (all found), destination_bin
"""
import colorsys

OK, REJECT = 'OK', 'REJECT'
NONE, MARKED, WRONG_COLOR, WRONG_SIZE = 'NONE', 'MARKED', 'WRONG_COLOR', 'WRONG_SIZE'

REJECT_BIN_FOR_DEFECT = {
    MARKED: 'BIN_REJECT_MARKED',
    WRONG_COLOR: 'BIN_REJECT_COLOR',
    WRONG_SIZE: 'BIN_REJECT_SIZE',
}


def classify_color(rgb, cls_cfg):
    """Return 'RED' | 'GREEN' | 'BLUE' | 'UNKNOWN' using HSV hue windows."""
    r, g, b = [max(0.0, min(255.0, float(c))) / 255.0 for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    hue = h * 360.0
    if s < cls_cfg['min_saturation'] or v < cls_cfg['min_value']:
        return 'UNKNOWN'
    for name, spec in cls_cfg['colors'].items():
        for lo, hi in spec['hue_ranges']:
            if lo <= hue <= hi:
                return name
    return 'UNKNOWN'


def size_ok(size_mm, pieces_cfg):
    return abs(size_mm - pieces_cfg['nominal_size_mm']) <= pieces_cfg['size_tolerance_mm']


def good_bin_id(shape, color):
    return 'BIN_%s_%s' % (color, shape)


def classify(shape, rgb, size_mm, mark_detected, cfg):
    """Full final classification -> verdict + destination bin."""
    cls_cfg, pieces_cfg = cfg['classification'], cfg['pieces']
    color = classify_color(rgb, cls_cfg)

    defects = []
    if mark_detected:
        defects.append(MARKED)
    if color == 'UNKNOWN':
        defects.append(WRONG_COLOR)
    # An unknown shape is a geometric defect -> same bin as wrong size.
    if not size_ok(size_mm, pieces_cfg) or shape not in ('CIRCLE', 'SQUARE'):
        defects.append(WRONG_SIZE)

    if not defects:
        return {'color': color, 'verdict': OK, 'defect': NONE, 'defects': [],
                'destination_bin': good_bin_id(shape, color)}

    # Several defects -> the priority list in the config decides.
    priority = cls_cfg.get('defect_priority', [MARKED, WRONG_COLOR, WRONG_SIZE])
    main = sorted(defects, key=lambda d: priority.index(d) if d in priority else 99)[0]
    return {'color': color, 'verdict': REJECT, 'defect': main, 'defects': defects,
            'destination_bin': REJECT_BIN_FOR_DEFECT[main]}
