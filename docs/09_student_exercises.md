# 9. Suggested exercises for students

Ordered from easy to hard. Each one touches a different part of the system.

1. **Read the graph.** Open the Architecture tab, click each node, and draw by hand the
   command/status pairs. Why is there no `/ir_sensor/command`?
2. **Follow one piece.** Place one piece and, in the Event log, identify every rule that
   fires (R4, R2, R8, R6, R9, R10, R5). Compare with `docs/03_state_machines.md` §3.6.
3. **Change the tolerance** to ±1 mm in `cell_config.yaml`, relaunch, and verify with
   pieces of 41 and 43.5 mm.
4. **Add a color.** Accept yellow pieces: add a hue window, two good bins (where?), and
   make sure `classifier.py` and the tests still pass. What else must change?
5. **Fail-safe test.** While the belt runs, kill the IR sensor (`Ctrl+C` on it or
   `ros2 lifecycle`/`kill`). What does the supervisor do? Which rule? How fast?
6. **Noise.** Increase `size_noise_std_mm` to 1.5. How many good pieces are now rejected?
   Compute the false-reject rate with 30 pieces. What tolerance would you choose?
7. **Missed marks.** Set `mark_detection_probability: 0.8`. What happens in the bins?
   How would you detect this in production?
8. **New rule: max pieces on the belt.** If more than 4 pieces are in transport, raise a
   `/supervisor/status` warning. (Write the test first.)
9. **Move the routing decision to the supervisor**: the camera only reports measurements;
   the supervisor applies `classifier.py`. Discuss pros/cons (single source of truth vs.
   camera knowing its own limits).
10. **Robot error handling.** (UR7e: also try a protective stop in `robot:=ur7e`.) Move a bin out of reach and see the `ERROR` state. Add a rule
    that sends `RESET` + puts the cell in `FAULT_ROBOT` and requires an operator button.
11. **Real perception**: implement `OpenCVPerception` (see `docs/05`) and test it with
    photos of the real pieces.
12. **Throughput.** Measure pieces/minute with `Batch of 6`. Which parameter limits it?
    Propose a rule change that improves it without breaking R2.
13. **Vision tuning.** Set `camera.render.noise_std: 15` and `light_gradient: 0.5`. Which
    test cases fail (`./test.sh`)? Which `camera.vision` parameters fix them?
14. **Mark type.** Extend `vision.py` to tell a DOT from a line-shaped mark (CROSS /
    SCRATCH / GROOVE) using the shape of the mark components.
15. **Real camera.** Calibrate the real camera, measure 10 good pieces with a caliper and
    with the camera, compute the mean error and the standard deviation, and set
    `size_correction_mm`.
