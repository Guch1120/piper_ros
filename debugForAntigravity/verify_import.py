#!/usr/bin/env python3
import sys
import rclpy

try:
    from cotyaka_omega_flexbe_behaviors.test_sm import testSM
    print("Successfully imported testSM")
except ImportError as e:
    print(f"Failed to import testSM: {e}")
    # Print sys.path to help debugging
    print("sys.path:", sys.path)
except Exception as e:
    print(f"An error occurred: {e}")
