"""ARDUINO I/O NODE (real hardware) - conveyor motor + IR sensor over USB serial.

One Arduino drives the conveyor and reads the IR sensor, but the ROS graph must
look EXACTLY like in simulation. So this process creates TWO ROS nodes that
share one serial port:

    /conveyor   subscribes /conveyor/command  ->  "RUN" / "STOP" to the Arduino
                publishes  /conveyor/status   <-  motor state REPORTED by the Arduino
    /ir_sensor  publishes  /ir_sensor/status  <-  IR state reported by the Arduino
                (still purely reactive: no command topic)

The supervisor does not know whether it talks to the simulation or to this.

Fail-safe: if the Arduino stops reporting (cable unplugged, reset...), the
/ir_sensor node STOPS publishing -> the supervisor's rule R1 stops the belt.
The firmware also has its own interlock and watchdog (arduino/cell_io/cell_io.ino).

Parameters:
    port      (string) serial device, default /dev/ttyACM0
    baud      (int)    default 115200
    stale_s   (float)  data older than this is considered lost, default 0.5

Run:  ros2 run quality_cell arduino_io_node --ros-args -p port:=/dev/ttyACM0
Protocol: see the header of arduino/cell_io/cell_io.ino
"""
import threading
import time

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from cell_interfaces.msg import ConveyorCommand, ConveyorStatus, IRSensorStatus
from quality_cell.core.cell_config import load_config

try:
    import serial   # python3-serial (pyserial)
except ImportError:  # pragma: no cover
    serial = None


class ArduinoLink:
    """Owns the serial port. Reader thread parses lines, keeps the last state."""

    def __init__(self, port, baud, logger):
        if serial is None:
            raise RuntimeError('pyserial missing: sudo apt install python3-serial')
        self.log = logger
        self.port, self.baud = port, baud
        self.ser = None
        self.lock = threading.Lock()
        self.ir_occupied = None
        self.motor_on = None
        self.last_rx = 0.0
        self.listeners = []          # callbacks(ir_changed, motor_changed)
        self.running = True
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _open(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            self.log.info('Serial port %s open' % self.port)
        except Exception as e:
            self.log.warn('Cannot open %s (%s); retrying...' % (self.port, e), throttle_duration_sec=5)
            self.ser = None
            time.sleep(1.0)

    def write(self, line):
        with self.lock:
            if self.ser is None:
                return False
            try:
                self.ser.write((line + '\n').encode())
                return True
            except Exception as e:
                self.log.error('Serial write failed: %s' % e)
                self.ser = None
                return False

    def _heartbeat(self):
        while self.running:
            self.write('PING')
            time.sleep(0.2)

    def _reader(self):
        buf = b''
        while self.running:
            if self.ser is None:
                self._open()
                continue
            try:
                buf += self.ser.read(64)
            except Exception as e:
                self.log.error('Serial read failed: %s' % e)
                with self.lock:
                    self.ser = None
                continue
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                self._parse(line.decode(errors='ignore').strip())

    def _parse(self, line):
        if not line:
            return
        parts = line.split()
        if parts[0] == 'STAT' and len(parts) == 3:
            ir, motor = parts[1] == '1', parts[2] == '1'
            ir_changed, motor_changed = ir != self.ir_occupied, motor != self.motor_on
            self.ir_occupied, self.motor_on = ir, motor
            self.last_rx = time.monotonic()
            for cb in self.listeners:
                cb(ir_changed, motor_changed)
        elif parts[0] == 'BOOT':
            self.log.info('Arduino booted: %s' % line)
        elif parts[0] == 'ERR':
            self.log.warn('Arduino: %s' % line)
        elif parts[0] == 'ACK':
            self.log.debug('Arduino: %s' % line)

    def fresh(self, stale_s):
        return self.ir_occupied is not None and time.monotonic() - self.last_rx < stale_s


class ConveyorDriver(Node):
    def __init__(self, link, stale_s, nominal_speed):
        super().__init__('conveyor')
        self.nominal_speed = nominal_speed
        self.link, self.stale_s = link, stale_s
        self.last_command = ''
        self.pub = self.create_publisher(ConveyorStatus, '/conveyor/status', 10)
        self.create_subscription(ConveyorCommand, '/conveyor/command', self.on_command, 10)
        self.create_timer(0.1, self.publish_status)
        link.listeners.append(lambda ir, motor: motor and self.publish_status())

    def on_command(self, msg):
        if msg.command not in (ConveyorCommand.RUN, ConveyorCommand.STOP):
            self.get_logger().warn('Unknown command %r' % msg.command)
            return
        self.last_command = msg.command
        if not self.link.write(msg.command):
            self.get_logger().error('Arduino not connected: %s not sent' % msg.command)

    def publish_status(self):
        if not self.link.fresh(self.stale_s):
            return                      # no data -> no status (do not invent one)
        m = ConveyorStatus()
        m.header.stamp = self.get_clock().now().to_msg()
        m.state = ConveyorStatus.RUNNING if self.link.motor_on else ConveyorStatus.STOPPED
        # No encoder: report the NOMINAL speed from the config while running.
        m.speed_mm_s = self.nominal_speed if self.link.motor_on else 0.0
        m.last_command = self.last_command
        self.pub.publish(m)


class IRSensorDriver(Node):
    def __init__(self, link, stale_s):
        super().__init__('ir_sensor')
        self.link, self.stale_s = link, stale_s
        self.pub = self.create_publisher(IRSensorStatus, '/ir_sensor/status', 10)
        self.create_timer(0.05, lambda: self.publish(False))
        link.listeners.append(lambda ir, motor: ir and self.publish(True))

    def publish(self, changed):
        if not self.link.fresh(self.stale_s):
            self.get_logger().warn('No data from the Arduino: IR status NOT published '
                                   '(supervisor will stop the belt)', throttle_duration_sec=2)
            return
        m = IRSensorStatus()
        m.header.stamp = self.get_clock().now().to_msg()
        m.state = IRSensorStatus.OCCUPIED if self.link.ir_occupied else IRSensorStatus.FREE
        m.changed = changed
        if changed:
            self.get_logger().info('IR beam -> %s' % m.state)
        self.pub.publish(m)


def main(args=None):
    rclpy.init(args=args)
    cfg_node = Node('arduino_io')   # holds the parameters + serial link
    port = cfg_node.declare_parameter('port', '/dev/ttyACM0').value
    baud = int(cfg_node.declare_parameter('baud', 115200).value)
    stale = float(cfg_node.declare_parameter('stale_s', 0.5).value)
    cfg_path = cfg_node.declare_parameter('cell_config_file', '').value
    speed = load_config(cfg_path or None)['conveyor']['speed_mm_s']
    link = ArduinoLink(port, baud, cfg_node.get_logger())
    conveyor, ir = ConveyorDriver(link, stale, speed), IRSensorDriver(link, stale)
    ex = MultiThreadedExecutor()
    for n in (cfg_node, conveyor, ir):
        ex.add_node(n)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    finally:
        link.running = False
        link.write('STOP')
        for n in (conveyor, ir, cfg_node):
            n.destroy_node()
        rclpy.try_shutdown()
