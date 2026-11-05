#!/usr/bin/env python3
"""Fake Arduino: emulates arduino/cell_io/cell_io.ino on a virtual serial port.

Lets you test arduino_io_node.py without hardware.

    python3 tools/fake_arduino.py               # prints the port, e.g. /dev/pts/5
    ros2 run quality_cell arduino_io_node --ros-args -p port:=/dev/pts/5

Keyboard (type + Enter in this terminal):
    b   block the IR beam        f   free the IR beam
    r   reset (BOOT)             q   quit
"""
import os
import select
import sys
import time
import tty  # noqa: F401  (keeps the pty in raw mode on some systems)

master, slave = os.openpty()
os.system('stty -F %s raw -echo' % os.ttyname(slave))
print('Fake Arduino on  %s   (keys: b=block IR, f=free IR, q=quit)' % os.ttyname(slave), flush=True)

ir, motor, last_status, last_rx = False, False, 0.0, time.time()
buf = b''


def send(line):
    os.write(master, (line + '\n').encode())


def status():
    global last_status
    send('STAT %d %d' % (ir, motor))
    last_status = time.time()


send('BOOT quality_cell_io 1')
while True:
    r, _, _ = select.select([master, sys.stdin], [], [], 0.01)
    now = time.time()
    if master in r:
        buf += os.read(master, 256)
        while b'\n' in buf:
            line, buf = buf.split(b'\n', 1)
            line = line.decode().strip()
            last_rx = now
            if line == 'RUN':
                if ir:
                    send('ERR INTERLOCK')
                else:
                    motor = True
                    send('ACK RUN')
                status()
                print('<- RUN  (motor %s)' % ('ON' if motor else 'refused'), flush=True)
            elif line == 'STOP':
                motor = False
                send('ACK STOP')
                status()
                print('<- STOP', flush=True)
    if sys.stdin in r:
        k = sys.stdin.readline().strip()
        if k == 'q':
            break
        if k in ('b', 'f'):
            ir = k == 'b'
            if ir and motor:
                motor = False          # firmware interlock
            print('IR beam %s' % ('BLOCKED' if ir else 'free'), flush=True)
            status()
        if k == 'r':
            send('BOOT quality_cell_io 1')
    if motor and now - last_rx > 1.5:
        motor = False
        send('ERR WATCHDOG')
        status()
    if now - last_status > 0.05:
        status()
