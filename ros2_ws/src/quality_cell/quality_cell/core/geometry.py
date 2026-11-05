"""Small geometry helpers shared by the simulated sensors."""
import math


def half_extent_x(shape, size_mm, yaw_deg):
    """Half of the piece footprint measured along the X axis (belt direction)."""
    if shape == 'CIRCLE':
        return size_mm / 2.0
    a = math.radians(yaw_deg)
    return size_mm / 2.0 * (abs(math.cos(a)) + abs(math.sin(a)))


def crosses_line_x(x_center, shape, size_mm, yaw_deg, x_line):
    """True if the footprint of the piece crosses the vertical line x = x_line."""
    h = half_extent_x(shape, size_mm, yaw_deg)
    return (x_center - h) <= x_line <= (x_center + h)


def inside_box(x, y, box):
    return box['x_min'] <= x <= box['x_max'] and box['y_min'] <= y <= box['y_max']
