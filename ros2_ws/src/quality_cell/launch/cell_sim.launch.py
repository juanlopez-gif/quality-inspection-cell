"""Launch the whole simulated quality inspection cell.

    ros2 launch quality_cell cell_sim.launch.py
    ros2 launch quality_cell cell_sim.launch.py dashboard_port:=8081
    ros2 launch quality_cell cell_sim.launch.py config:=/path/to/my_cell_config.yaml

    ros2 launch quality_cell cell_sim.launch.py robot:=ur7e_dry    # real UR7e driver code, no robot
    ros2 launch quality_cell cell_sim.launch.py camera_backend:=sim  # ground-truth camera (no images, light CPU)
    ros2 launch quality_cell cell_sim.launch.py robot:=ur7e ur_ip:=192.168.1.102
        ^ hardware-in-the-loop: the REAL UR7e picks VIRTUAL pieces (no piece needed,
          vacuum switches for real). Clear the space above the belt first!

Then open http://localhost:8080
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import EqualsSubstitution, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_cfg = os.path.join(get_package_share_directory('quality_cell'),
                               'config', 'cell_config.yaml')
    cfg = LaunchConfiguration('config')
    port = LaunchConfiguration('dashboard_port')
    params = [{'cell_config_file': cfg}]

    def node(executable, name, extra=None, condition=None):
        return Node(package='quality_cell', executable=executable, name=name,
                    output='screen', emulate_tty=True, condition=condition,
                    parameters=params + ([extra] if extra else []))

    robot = LaunchConfiguration('robot')

    return LaunchDescription([
        DeclareLaunchArgument('config', default_value=default_cfg,
                              description='Shared cell configuration YAML'),
        DeclareLaunchArgument('dashboard_port', default_value='8080'),
        DeclareLaunchArgument('robot', default_value='sim',
                              description='sim | ur7e_dry | ur7e'),
        DeclareLaunchArgument('ur_ip', default_value='192.168.1.102'),
        DeclareLaunchArgument('camera_backend', default_value='',
                              description='sim | opencv (empty = cell_config.yaml)'),
        DeclareLaunchArgument('camera_source', default_value='',
                              description='sim_render | 0 | /dev/video2 ... (empty = config)'),
        # ---- the brain
        node('supervisor_node', 'supervisor'),
        # ---- devices (simulated drivers)
        node('conveyor_node', 'conveyor'),
        node('ir_sensor_node', 'ir_sensor'),
        node('camera_node', 'camera', {'backend': LaunchConfiguration('camera_backend'),
                                       'source': ParameterValue(LaunchConfiguration('camera_source'), value_type=str)}),
        node('robot_node', 'robot', condition=IfCondition(EqualsSubstitution(robot, 'sim'))),
        node('ur7e_robot_node', 'robot', {'dry_run': True},
             condition=IfCondition(EqualsSubstitution(robot, 'ur7e_dry'))),
        node('ur7e_robot_node', 'robot', {'dry_run': False, 'ur_ip': LaunchConfiguration('ur_ip')},
             condition=IfCondition(EqualsSubstitution(robot, 'ur7e'))),
        # ---- simulation only
        node('world_sim_node', 'world_sim'),
        # ---- visualisation / operator panel
        node('dashboard_node', 'cell_dashboard', {'port': port}),
    ])
