#!/usr/bin/env python3
"""Generate the figures of docs/15_physical_build_guide.md from cell_config.yaml.

    python3 tools/make_build_figures.py

Writes:
    docs/images/build_layout_top_view.svg   top view with the real dimensions of the config
    docs/images/build_wiring_diagram.svg    electrical / pneumatic connections

Re-run it after changing the geometry in cell_config.yaml so the drawing always
matches the configuration.
"""
import os
from html import escape as esc

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, 'ros2_ws', 'src', 'quality_cell', 'config', 'cell_config.yaml')
OUT = os.path.join(ROOT, 'docs', 'images')

STYLE = """
<style>
  text { font-family: Arial, Helvetica, sans-serif; fill: #1d2733; }
  .t  { font-size: 15px; } .s { font-size: 12px; } .xs { font-size: 10.5px; fill: #4b5866; }
  .b  { font-weight: bold; } .title { font-size: 20px; font-weight: bold; }
  .dim { stroke: #c0392b; stroke-width: 1.2; fill: none; }
  .dimt { font-size: 12px; fill: #c0392b; font-weight: bold; }
  .wire { fill: none; stroke-width: 2.5; }
</style>"""


def layout(cfg):
    """Top view in millimetres. SVG y grows down, cell Y grows up -> Y_svg = OY - y."""
    c, ir, cam, bins = cfg['conveyor'], cfg['ir_sensor'], cfg['camera'], cfg['bins']
    rb = cam['robot_base_in_cell']
    L, W, s = c['length_mm'], c['width_mm'], 1.0
    OX, OY = 230, 790                   # svg position of the cell origin
    X = lambda x: OX + x * s            # noqa: E731
    Y = lambda y: OY - y * s            # noqa: E731
    e = []
    a = e.append
    a(f'<rect x="0" y="0" width="1330" height="1040" fill="#ffffff"/>')
    a(f'<text x="20" y="34" class="title">Quality inspection cell - top view (dimensions in mm, from cell_config.yaml)</text>')
    # grid 100 mm
    for gx in range(-100, 1101, 100):
        a(f'<line x1="{X(gx)}" y1="{Y(-160)}" x2="{X(gx)}" y2="{Y(760)}" stroke="#eef1f4"/>')
    for gy in range(-100, 751, 100):
        a(f'<line x1="{X(-120)}" y1="{Y(gy)}" x2="{X(1080)}" y2="{Y(gy)}" stroke="#eef1f4"/>')
    # table outline (suggested)
    a(f'<rect x="{X(-60)}" y="{Y(720)}" width="{1140 * s}" height="{(720 + 140) * s}" rx="8" fill="none" stroke="#b9c2cc" stroke-dasharray="8 6"/>')
    a(f'<text x="{X(-50)}" y="{Y(700)}" class="xs">suggested table / work area (~1150 x 860 mm)</text>')
    # conveyor
    a(f'<rect x="{X(-25)}" y="{Y(W / 2 + 15)}" width="{(L + 50) * s}" height="{(W + 30) * s}" rx="10" fill="#5b6470"/>')
    a(f'<rect x="{X(0)}" y="{Y(W / 2)}" width="{L * s}" height="{W * s}" fill="#2f353d"/>')
    for x in range(20, int(L), 40):
        a(f'<line x1="{X(x)}" y1="{Y(W / 2)}" x2="{X(x)}" y2="{Y(-W / 2)}" stroke="#3d454f" stroke-width="3"/>')
    a(f'<text x="{X(250)}" y="{Y(0) + 5}" text-anchor="middle" class="t b" style="fill:#e6edf3">CONVEYOR  {L:.0f} x {W:.0f}   -&gt;  travel +X</text>')
    # load zone
    sx = c['spawn_x_mm']
    a(f'<rect x="{X(sx - 45)}" y="{Y(W / 2 - 6)}" width="{90 * s}" height="{(W - 12) * s}" fill="none" stroke="#7c8cff" stroke-width="2" stroke-dasharray="6 4"/>')
    a(f'<text x="{X(sx)}" y="{Y(-W / 2 - 33)}" text-anchor="middle" class="s b" style="fill:#4a57d6">LOAD (operator)</text>')
    # pick ROI
    r = cam['pick_roi']
    a(f'<rect x="{X(r["x_min"])}" y="{Y(r["y_max"])}" width="{(r["x_max"] - r["x_min"]) * s}" height="{(r["y_max"] - r["y_min"]) * s}" fill="rgba(245,197,66,0.25)" stroke="#d4a017" stroke-width="2"/>')
    a(f'<text x="{X(r["x_min"]) + 6}" y="{Y(r["y_max"]) + 16}" class="s b" style="fill:#f5c542">PICK ROI</text>')
    # IR sensor
    xi = ir['x_mm']
    a(f'<line x1="{X(xi)}" y1="{Y(W / 2 + 32)}" x2="{X(xi)}" y2="{Y(-W / 2 - 32)}" stroke="#e74c3c" stroke-width="3"/>')
    a(f'<rect x="{X(xi) - 12}" y="{Y(W / 2 + 52)}" width="24" height="22" fill="#e74c3c"/>')
    a(f'<rect x="{X(xi) - 12}" y="{Y(-W / 2 - 30)}" width="24" height="22" fill="#e74c3c"/>')
    a(f'<text x="{X(xi) + 18}" y="{Y(W / 2 + 40)}" class="s b" style="fill:#c0392b">IR emitter</text>')
    a(f'<text x="{X(xi) + 18}" y="{Y(-W / 2 - 44)}" class="s b" style="fill:#c0392b">IR receiver (beam across the belt)</text>')
    # camera
    a(f'<rect x="{X(cam["fov"]["x_min"])}" y="{Y(cam["fov"]["y_max"] + 22)}" width="{(cam["fov"]["x_max"] - cam["fov"]["x_min"]) * s}" height="{(cam["fov"]["y_max"] - cam["fov"]["y_min"] + 44) * s}" fill="none" stroke="#d4a017" stroke-dasharray="10 6"/>')
    cx = (cam['fov']['x_min'] + cam['fov']['x_max']) / 2
    a(f'<circle cx="{X(cx)}" cy="{Y(0)}" r="16" fill="#f5c542" stroke="#8a6d00" stroke-width="2"/>')
    a(f'<text x="{X(cx) + 24}" y="{Y(0) + 5}" class="s b" style="fill:#f5c542">camera (above)</text>')
    a(f'<text x="{X(cx)}" y="{Y(-W / 2 - 150)}" text-anchor="middle" class="s b" style="fill:#8a6d00">CAMERA: above the belt centre, looking straight down, ~0.7-0.9 m high (see guide section 4)</text>')
    # robot
    a(f'<circle cx="{X(rb["x"])}" cy="{Y(rb["y"])}" r="{cfg["robot"]["max_reach_mm"] * s}" fill="rgba(31,181,168,0.05)" stroke="#1fb5a8" stroke-dasharray="6 6"/>')
    a(f'<circle cx="{X(rb["x"])}" cy="{Y(rb["y"])}" r="65" fill="#e9f7f6" stroke="#1fb5a8" stroke-width="3"/>')
    a(f'<text x="{X(rb["x"])}" y="{Y(rb["y"]) + 5}" text-anchor="middle" class="t b" style="fill:#13857b">UR7e base</text>')
    rr = cfg['robot']['max_reach_mm']
    a(f'<text x="{X(rb["x"] - rr * 0.94) + 8}" y="{Y(rb["y"] + rr * 0.34)}" class="s" style="fill:#13857b">UR7e reach {rr:.0f} mm</text>')
    # bins
    bs = bins['size_mm']
    for b in bins['list']:
        good = b['kind'] == 'good'
        dash_attr = '' if good else 'stroke-dasharray="7 4"'
        col = {'RED': '#e74c3c', 'GREEN': '#27ae60', 'BLUE': '#2e6fe0'}.get(b.get('color'), '#c0392b')
        a(f'<rect x="{X(b["x"] - bs / 2)}" y="{Y(b["y"] + bs / 2)}" width="{bs * s}" height="{bs * s}" rx="6" fill="#ffffff" stroke="{col}" stroke-width="3" {dash_attr}/>')
        a(f'<text x="{X(b["x"])}" y="{Y(b["y"]) - 4}" text-anchor="middle" class="xs b">{b["label"]}</text>')
        a(f'<text x="{X(b["x"])}" y="{Y(b["y"]) + 12}" text-anchor="middle" class="xs">({b["x"]:.0f}, {b["y"]:.0f})</text>')
    # dimensions
    def hdim(x1, x2, y, label, off=0):
        a(f'<line x1="{X(x1)}" y1="{Y(y)}" x2="{X(x2)}" y2="{Y(y)}" class="dim" marker-start="url(#d)" marker-end="url(#d)"/>')
        a(f'<text x="{(X(x1) + X(x2)) / 2}" y="{Y(y) - 6 + off}" text-anchor="middle" class="dimt">{label}</text>')

    def vdim(y1, y2, x, label):
        a(f'<line x1="{X(x)}" y1="{Y(y1)}" x2="{X(x)}" y2="{Y(y2)}" class="dim" marker-start="url(#d)" marker-end="url(#d)"/>')
        a(f'<text x="{X(x) + (6 if x > 0 else -6)}" y="{(Y(y1) + Y(y2)) / 2 + 4}" text-anchor="{"start" if x > 0 else "end"}" class="dimt">{label}</text>')
    hdim(0, L, -140, f'belt length {L:.0f}')
    hdim(0, xi, -112, f'IR beam at X = {xi:.0f} from belt start')
    vdim(0, rb['y'], rb['x'] + 90, f'{rb["y"]:.0f} (belt centre -&gt; robot base)')
    vdim(-W / 2, W / 2, -45, f'{W:.0f}')
    # origin
    a(f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(90)}" y2="{Y(0)}" stroke="#e74c3c" stroke-width="3" marker-end="url(#ax)"/>')
    a(f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(0)}" y2="{Y(90)}" stroke="#27ae60" stroke-width="3" marker-end="url(#ax)"/>')
    a(f'<circle cx="{X(0)}" cy="{Y(0)}" r="5" fill="#000"/>')
    a(f'<text x="{X(-90)}" y="{Y(0) - 22}" text-anchor="end" class="s b">CELL origin (0,0)</text>')
    a(f'<text x="{X(-90)}" y="{Y(0) - 8}" text-anchor="end" class="xs">belt start, centre line,</text>')
    a(f'<text x="{X(-90)}" y="{Y(0) + 6}" text-anchor="end" class="xs">belt surface</text>')
    a(f'<line x1="{X(-88)}" y1="{Y(0) - 10}" x2="{X(-6)}" y2="{Y(0) - 2}" stroke="#333" stroke-width="1"/>')
    a(f'<text x="{X(96)}" y="{Y(0) + 4}" class="s b" style="fill:#e74c3c">X</text>')
    a(f'<text x="{X(0) + 6}" y="{Y(96)}" class="s b" style="fill:#27ae60">Y</text>')
    a(f'<text x="20" y="1025" class="xs">Generated by tools/make_build_figures.py from cell_config.yaml. Re-run it after changing the geometry.</text>')
    defs = ('<defs><marker id="d" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
            '<path d="M5,0 L5,10" stroke="#c0392b" stroke-width="2"/></marker>'
            '<marker id="ax" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#333"/></marker></defs>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1330" height="1040" viewBox="0 0 1330 1040">'
            + STYLE + defs + ''.join(e) + '</svg>')


def wiring():
    e = []
    a = e.append

    def box(x, y, w, h, title, lines, color):
        a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#ffffff" stroke="{color}" stroke-width="2.5"/>')
        a(f'<rect x="{x}" y="{y}" width="{w}" height="30" rx="10" fill="{color}"/>')
        a(f'<rect x="{x}" y="{y + 20}" width="{w}" height="10" fill="{color}"/>')
        a(f'<text x="{x + w / 2}" y="{y + 21}" text-anchor="middle" class="t b" style="fill:#fff">{esc(title)}</text>')
        for i, l in enumerate(lines):
            a(f'<text x="{x + 12}" y="{y + 52 + i * 18}" class="s">{esc(l)}</text>')

    def wire(pts, color, label=None, lx=None, ly=None, dash=''):
        d = 'M' + ' L'.join(f'{x},{y}' for x, y in pts)
        dash_attr = f'stroke-dasharray="{dash}"' if dash else ''
        a(f'<path d="{d}" class="wire" stroke="{color}" {dash_attr}/>')
        if label:
            a(f'<text x="{lx}" y="{ly}" class="xs b" style="fill:{color}">{esc(label)}</text>')

    a('<rect x="0" y="0" width="1300" height="900" fill="#ffffff"/>')
    a('<text x="20" y="34" class="title">Quality inspection cell - wiring and connections</text>')
    box(520, 60, 260, 150, 'PC  (Ubuntu 24.04 + ROS 2 Jazzy)', ['runs all ROS 2 nodes', 'supervisor, drivers, dashboard', 'USB: Arduino, camera', 'Ethernet: UR7e controller'], '#34495e')
    box(80, 300, 280, 200, 'Arduino Uno / Nano', ['firmware: arduino/cell_io/cell_io.ino', 'USB serial 115200 baud', 'D2  <- IR receiver OUT (pull-up)', 'D7  -> relay / MOSFET IN', '5V, GND -> sensor + relay logic', 'D13 LED = beam blocked'], '#d08b3e')
    box(20, 580, 210, 130, 'IR break-beam sensor', ['emitter: 5V, GND', 'receiver: 5V, GND, OUT', 'beam across the belt at', 'X = ir_sensor.x_mm'], '#e74c3c')
    box(260, 580, 230, 130, 'Relay module / MOSFET', ['IN  <- Arduino D7', 'VCC 5V, GND (Arduino)', 'contact COM/NO in series', 'with the motor supply'], '#8e44ad')
    box(260, 750, 230, 90, 'Conveyor motor + PSU', ['separate supply (e.g. 24 V DC)', 'flyback diode if MOSFET'], '#8e44ad')
    box(560, 300, 210, 120, 'USB camera', ['above the belt, looking down', 'source: 0 (/dev/video0)', 'fixed mount, diffuse light'], '#d4a017')
    box(880, 60, 330, 200, 'UR7e control box', ['Ethernet <-> PC (static IP)', 'Remote Control mode ON', 'DO0 (standard, 24 V) -> vacuum', '   valve / pump relay', 'E-stop on teach pendant', '(+ optional external E-stop)'], '#1fb5a8')
    box(880, 330, 330, 150, 'UR7e arm + suction cup', ['TCP = tip of the suction cup', 'payload = cup + piece', 'vacuum hose from ejector to cup'], '#1fb5a8')
    box(880, 560, 330, 160, 'Vacuum generation', ['A) 24 V solenoid valve + venturi', '    ejector + compressed air', 'B) 24 V vacuum pump (via relay)', 'driven by UR DO0 (robot.vacuum_output)'], '#2e86de')
    # wires
    wire([(520, 150), (220, 150), (220, 300)], '#34495e', 'USB (serial /dev/ttyACM0)', 230, 140)
    wire([(650, 210), (650, 300)], '#34495e', 'USB (video)', 660, 260)
    wire([(780, 130), (880, 130)], '#34495e', 'Ethernet', 795, 120)
    wire([(150, 500), (150, 580)], '#e74c3c', 'D2 / 5V / GND', 158, 545)
    wire([(300, 500), (300, 580)], '#8e44ad', 'D7 / 5V / GND', 308, 545)
    wire([(375, 710), (375, 750)], '#8e44ad', 'COM / NO', 383, 735)
    wire([(1045, 260), (1045, 330)], '#1fb5a8', 'arm cable', 1053, 300)
    wire([(1210, 200), (1260, 200), (1260, 640), (1210, 640)], '#2e86de', 'DO0 24 V + 0 V', 1140, 525)
    wire([(880, 640), (840, 640), (840, 420), (880, 420)], '#2e86de', 'vacuum hose', 770, 540, '8 5')
    a('<rect x="520" y="560" width="300" height="190" rx="10" fill="#fff6f5" stroke="#c0392b" stroke-width="2"/>')
    for i, l in enumerate(['SAFETY NOTES', 'Common GND: Arduino + relay logic only.', 'Never power the motor from the Arduino.',
                           'Check UR DO current limits in the manual;', 'use a relay for a pump.', 'E-stop within reach at all times.',
                           'Test the robot at low speed first.']):
        a(f'<text x="535" y="{588 + i * 22}" class="{"s b" if i == 0 else "s"}" style="fill:#922b21">{esc(l)}</text>')
    a('<text x="20" y="885" class="xs">Generated by tools/make_build_figures.py. Pins and outputs are the defaults of cell_io.ino and cell_config.yaml.</text>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1300" height="900" viewBox="0 0 1300 900">'
            + STYLE + ''.join(e) + '</svg>')


if __name__ == '__main__':
    with open(CFG) as f:
        cfg = yaml.safe_load(f)
    os.makedirs(OUT, exist_ok=True)
    for name, svg in (('build_layout_top_view.svg', layout(cfg)), ('build_wiring_diagram.svg', wiring())):
        with open(os.path.join(OUT, name), 'w') as f:
            f.write(svg)
        print('wrote docs/images/' + name)
