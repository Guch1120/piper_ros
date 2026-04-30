import numpy as np
from scipy.spatial.transform import Rotation as R
import math

# We know the user's manual "rough" guess that looks correct in RViz:
# 3.14 -1.6 3.14
rough_rpy = [3.14, -1.6, 3.14]
R_rough = R.from_euler('xyz', rough_rpy).as_matrix()

# During the calibration, we measured the *actual* optical orientation:
# Let's say Pattern A gave: Calculated URDF RPY (radians): Roll=-0.1066, Pitch=0.0504, Yaw=1.5773
# The "ideal" optical orientation if the camera was perfectly straight down (Z up, Y forward in camera view relative to base) 
# would be Roll=0, Pitch=0, Yaw=1.57 (90 deg).
# The *difference* is the slight mounting tilt:
# Tilt Roll = -0.1066 - 0 = -0.1066 rad (approx -6 deg)
# Tilt Pitch = 0.0504 - 0 = +0.0504 rad (approx +3 deg)
# Tilt Yaw = 1.5773 - 1.5708 = 0.0065 rad (approx +0.4 deg)

tilt_roll = -0.1066
tilt_pitch = 0.0504
tilt_yaw = 1.5773 - (math.pi / 2)

print(f"Measured Tilt: Roll={np.degrees(tilt_roll):.2f}deg, Pitch={np.degrees(tilt_pitch):.2f}deg, Yaw={np.degrees(tilt_yaw):.2f}deg")

# We want to mathematically apply this small tilt to the rough_rpy without causing Euler flips.
# Since the rough_rpy is defined in the link6 frame, we should probably apply the tilt rotation
# to the base matrix in the child frame.
# R_final = R_rough * R_tilt

# The tilt was measured in the optical frame's parent (link6), but the optical frame itself has Z-forward.
# Actually, the simplest way to avoid aliasing is to see how the user's manual RPY needs to change.
# If they look down, Pitch corresponds to looking up/down. Roll is tilting left/right.

# Let's apply standard rotations.
R_tilt = R.from_euler('xyz', [tilt_roll, tilt_pitch, tilt_yaw]).as_matrix()

R_new = R_rough @ R_tilt

new_rpy = R.from_matrix(R_new).as_euler('xyz')

print(f"Original Rough RPY: {rough_rpy}")
print(f"Corrected RPY: {new_rpy[0]:.4f} {new_rpy[1]:.4f} {new_rpy[2]:.4f}")

# Let's test a few combinations to see which is closest to the 3.14 -1.6 3.14 format
import itertools
for rx in [-math.pi, 0, math.pi]:
    for ry in [-math.pi, 0, math.pi]:
        for rz in [-math.pi, 0, math.pi]:
             shifted = new_rpy + [rx, ry, rz]
             # check if equivalent
             diff_R = R_new.T @ R.from_euler('xyz', shifted).as_matrix()
             angle = np.arccos(np.clip((np.trace(diff_R) - 1) / 2, -1.0, 1.0))
             if angle < 1e-4:
                 print(f"Valid Equivalent RPY: {shifted[0]:.4f}  {shifted[1]:.4f}  {shifted[2]:.4f}")

