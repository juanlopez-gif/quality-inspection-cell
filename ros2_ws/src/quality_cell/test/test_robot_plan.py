"""Unit tests of the pick-and-place plan shared by the simulated and the real UR7e robot."""
import os

import pytest

from quality_cell.core.cell_config import FrameTransform, load_config
from quality_cell.core.robot_plan import PlanError, build_pick_place_plan

CFG = load_config(os.path.join(os.path.dirname(__file__), '..', 'config', 'cell_config.yaml'))
TF = FrameTransform(CFG)


def test_plan_states_in_order():
    plan = build_pick_place_plan(CFG, TF, (-20.0, -250.0, 6.0), 'BIN_RED_CIRCLE')
    states = [s for s, *_ in plan]
    assert states[0] == 'PICKING_CONVEYOR' and states[-1] == 'RETURNING_HOME'
    assert [d for _, k, d, _ in plan if k == 'vacuum'] == [True, False]   # ON then OFF


def test_unknown_bin():
    with pytest.raises(PlanError):
        build_pick_place_plan(CFG, TF, (0.0, -250.0, 6.0), 'BIN_NOPE')


def test_out_of_reach():
    with pytest.raises(PlanError):
        build_pick_place_plan(CFG, TF, (0.0, -2000.0, 6.0), 'BIN_RED_CIRCLE')
