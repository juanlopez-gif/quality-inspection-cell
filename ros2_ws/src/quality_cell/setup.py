from glob import glob

from setuptools import find_packages, setup

package_name = 'quality_cell'

setup(
    name=package_name,
    version='1.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/web', glob('quality_cell/web/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Capstone TA',
    maintainer_email='juan.lopez@uri.edu',
    description='Quality inspection cell: supervisor, devices, simulation and dashboard',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'supervisor_node = quality_cell.nodes.supervisor_node:main',
            'conveyor_node = quality_cell.nodes.conveyor_node:main',
            'ir_sensor_node = quality_cell.nodes.ir_sensor_node:main',
            'camera_node = quality_cell.nodes.camera_node:main',
            'robot_node = quality_cell.nodes.robot_node:main',
            'world_sim_node = quality_cell.nodes.world_sim_node:main',
            'dashboard_node = quality_cell.nodes.dashboard_node:main',
            # ---- real hardware drivers (same topics as the simulated devices)
            'arduino_io_node = quality_cell.nodes.arduino_io_node:main',
            'ur7e_robot_node = quality_cell.nodes.ur7e_robot_node:main',
        ],
    },
)
