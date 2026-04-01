#!/bin/bash
# Mock detect_jetson_board.sh — reads from environment variables set by the test runner.
#   TEST_BOARD_SHORT    → value returned by --short
#   TEST_CAMERA_PORTS   → value returned by --camera-ports
case "$1" in
    --short)         echo "${TEST_BOARD_SHORT:-unknown}" ;;
    --camera-ports)  echo "${TEST_CAMERA_PORTS:-2}" ;;
    *)               echo "${TEST_BOARD_SHORT:-unknown}" ;;
esac
