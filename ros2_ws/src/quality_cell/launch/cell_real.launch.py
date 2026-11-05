"""REAL CELL: Arduino (conveyor + IR sensor) + Universal Robots UR7e + vacuum.

    ros2 launch quality_cell cell_real.launch.py port:=/dev/ttyACM0 ur_ip:=192.168.1.102
    ros2 launch quality_cell cell_real.launch.py robot_dry_run:=true    # without the robot
    ros2 launch quality_cell cell_real.launch.py camera_source:=/dev/video2 camera_calibration:=/abs/cal.yaml

Same supervisor, same topics as in simulation. world_sim is NOT started.

    supervisor        quality_cell/nodes/supervisor_node.py        (unchanged)
    conveyor+ir_sensor quality_cell/nodes/arduino_io_node.py       (one process, two ROS nodes)
    robot             quality_cell/nodes/ur7e_robot_node.py
    camera            camera_node, backend opencv on the USB camera
                      (calibrate first: tools/calibrate_camera.py, see docs/14)
    cell_dashboard    monitoring (placing virtual pieces does nothing here)

See docs/13_hardware_arduino_ur7e.md before running this.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_cfg = os.path.join(get_package_share_directory('quality_cell'),
                               'config', 'cell_config.yaml')
    cfg = LaunchConfiguration('config')
    p = {'cell_config_file': cfg}

    def node(executable, name, extra=None):
        return Node(package='quality_cell', executable=executable, name=name,
                    output='screen', emulate_tty=True, parameters=[dict(p, **(extra or {}))])

    return LaunchDescription([
        DeclareLaunchArgument('config', default_value=default_cfg),
        DeclareLaunchArgument('port', default_value='/dev/ttyACM0',
                              description='Arduino serial port'),
        DeclareLaunchArgument('ur_ip', default_value='192.168.1.102'),
        DeclareLaunchArgument('robot_dry_run', default_value='false'),
        DeclareLaunchArgument('camera_source', default_value='0',
                              description='camera index, /dev/videoN or URL'),
        DeclareLaunchArgument('camera_calibration',
                              default_value=os.path.expanduser('~/Desktop/quality_inspection_cell/camera_calibration.yaml')),
        DeclareLaunchArgument('dashboard_port', default_value='8080'),

        node('supervisor_node', 'supervisor'),
        # conveyor + ir_sensor (the node names /conveyor and /ir_sensor are set inside)
        # NO `name=` here: it would rename ALL nodes of the process (/conveyor and /ir_sensor)
        Node(package='quality_cell', executable='arduino_io_node',
             output='screen', emulate_tty=True,
             parameters=[dict(p, port=LaunchConfiguration('port'))]),
        node('ur7e_robot_node', 'robot', {'ur_ip': LaunchConfiguration('ur_ip'),
                                          'dry_run': ParameterValue(LaunchConfiguration('robot_dry_run'), value_type=bool)}),
        # Real camera: OpenCV pipeline on the USB camera, needs the calibration file
        node('camera_node', 'camera', {
            'backend': 'opencv',
            'source': ParameterValue(LaunchConfiguration('camera_source'), value_type=str),
            'calibration_file': LaunchConfiguration('camera_calibration')}),
        node('dashboard_node', 'cell_dashboard', {'port': LaunchConfiguration('dashboard_port')}),
    ])
