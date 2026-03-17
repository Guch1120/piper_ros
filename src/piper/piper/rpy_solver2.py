import numpy as np
from scipy.spatial.transform import Rotation as R
import math

r_opt = -0.1066
p_opt = 0.0504
y_opt = 1.5773

print("Original optical rpy: ", r_opt, p_opt, y_opt)

R_link6_optical = R.from_euler('xyz', [r_opt, p_opt, y_opt]).as_matrix()

# Standard realsense orientation: optical frame is rotated from body frame by:
# roll = -90, pitch = 0, yaw = -90
R_body_to_optical = R.from_euler('xyz', [-math.pi/2, 0, -math.pi/2]).as_matrix()

# Thus, R_link6_optical = R_link6_body * R_body_to_optical
# Ergo, R_link6_body = R_link6_optical * R_body_to_optical.T
R_link6_body = R_link6_optical @ R_body_to_optical.T

res = R.from_matrix(R_link6_body).as_euler('xyz')
print('Standard Extrinsic XYZ:', res)

# Check equivalent sets around [3.14, -1.6, 3.14]
target = [3.14, -1.6, 3.14]
R_target = R.from_euler('xyz', target).as_matrix()

found = False
for rx in [-math.pi*2, -math.pi, 0, math.pi, math.pi*2]:
  for ry in [-math.pi*2, -math.pi, 0, math.pi, math.pi*2]:
    for rz in [-math.pi*2, -math.pi, 0, math.pi, math.pi*2]:
        shift = res + [rx, ry, rz]
        # Check if R_link6_body matches shift exactly
        diff = R_link6_body.T @ R.from_euler('xyz', shift).as_matrix()
        trace = np.clip(np.trace(diff), -1.0, 3.0)
        angle = np.arccos((trace - 1.0) / 2.0)
        
        if angle < 1e-3:
            # It's an equivalent rotation
            # Print if it's close to 3.14 -1.6 3.14
            if abs(shift[0]-3.14)<1.5 and abs(shift[1] - -1.6)<1.5 and abs(shift[2]-3.14)<1.5:
                print('Equivalent near target:', shift)
                found = True

if not found:
    print("No direct Euler match found in vicinity. This means the R_body_to_optical assumption is slightly off.")
    
    # What if the user used a different body-to-optical mapping?
    # Another common convention: Optical Z = Body X, Optical X = Body -Y, Optical Y = Body -Z
    # Which is R(y, -pi/2) * R(z, pi/2).
    # Let's test what Euler gives the right rotation.
    
    # Let's directly compute the needed body rotation
    # R_required = R_link6_optical * R_optical_body
    # We want R_required to be close to R_target = [3.14, -1.6, 3.14]
    # R_optical_body = R_link6_optical.T * R_target
    
    R_opt_body_measured = R_link6_optical.T @ R_target
    print("Implied R_optical_body to match user's visual intuition:")
    print(np.round(R_opt_body_measured, 2))
    
