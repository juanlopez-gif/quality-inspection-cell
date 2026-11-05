"""Pure-Python logic (no ROS imports) so it can be unit-tested and reused.

    cell_config  - loads config/cell_config.yaml, frame transforms
    classifier   - colour / size / defect classification and bin routing
    perception   - simulated camera (replace with OpenCV / ML for the real cell)
    supervisor_rules - the supervisor rule engine (the "brain" of the cell)
    geometry     - small helpers (footprints, interpolation)
"""
