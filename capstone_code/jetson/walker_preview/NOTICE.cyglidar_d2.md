# CygLiDAR D2 SDK provenance

Copyright (c) 2024, CygLiDAR_ROS. BSD-3-Clause, see LICENSE.

The lens tables in `jetson/walker_preview/d2_lens.json` are copied from
`sdk/include/distortion_table.h` of https://github.com/CygLiDAR-ROS/cyglidar_d2,
commit `2d3b702706c5d0865ce246296e0e64b86fe261e8`.

The display-only Python port in `jetson/walker_preview/d2_usb.py` follows
`cygbot_parser.cpp`, `distance_processor.cpp`, `distortion_table.cpp`,
`mapping_point_cloud.cpp` and `serial_uart.cpp` at that same commit.
The vendor default lens model is used, without per-device calibration.
