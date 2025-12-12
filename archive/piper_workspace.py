import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from scipy.optimize import minimize
from scipy.spatial.transform import Rotation as R
import time

# --- Robot Parameters (Extracted from Xacro) ---
# Joint limits
LIMITS = [
    (-2.618, 2.618),  # Joint 1
    (0.0, 3.14),      # Joint 2
    (-2.967, 0.0),    # Joint 3
    (-1.745, 1.745),  # Joint 4
    (-1.22, 1.22),    # Joint 5
    (-2.0944, 2.0944) # Joint 6
]

# Fixed transforms (Origin xyz, rpy)
# Format: [x, y, z, r, p, y]
JOINT_ORIGINS = [
    [0, 0, 0.123, 0, 0, 0],                         # Joint 1 (Base -> Link1)
    [0, 0, 0, 1.5708, -0.1359, -3.1416],            # Joint 2 (Link1 -> Link2)
    [0.28503, 0, 0, 0, 0, -1.7939],                 # Joint 3 (Link2 -> Link3)
    [-0.021984, -0.25075, 0, 1.5708, 0, 0],         # Joint 4 (Link3 -> Link4)
    [0, 0, 0, -1.5708, 0, 0],                       # Joint 5 (Link4 -> Link5)
    [8.8259E-05, -0.091, 0, 1.5708, 0, 0]           # Joint 6 (Link5 -> Link6)
]

def get_transform_matrix(x, y, z, r, p, yaw):
    """Generates a homogeneous transformation matrix from xyz and rpy."""
    rot = R.from_euler('xyz', [r, p, yaw], degrees=False).as_matrix()
    T = np.eye(4)
    T[:3, :3] = rot
    T[:3, 3] = [x, y, z]
    return T

# Precompute fixed transforms to speed up FK
FIXED_TRANSFORMS = [get_transform_matrix(*params) for params in JOINT_ORIGINS]

def forward_kinematics(q):
    """
    Computes the end-effector pose for given joint angles q.
    Returns: T_ee (4x4 matrix)
    """
    T = np.eye(4)
    
    for i, (fixed_T, angle) in enumerate(zip(FIXED_TRANSFORMS, q)):
        # Rotate about Z axis by joint angle
        c, s = np.cos(angle), np.sin(angle)
        R_z = np.array([
            [c, -s, 0, 0],
            [s, c, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
        
        # Apply fixed transform then joint rotation
        # Note: In URDF, the joint frame is defined relative to parent, 
        # then rotation happens in that frame.
        T = T @ fixed_T @ R_z
        
    return T

def inverse_kinematics(target_pos, target_rot_matrix, seed_q=None):
    """
    Numerical IK to find joint angles that match target position and orientation.
    """
    if seed_q is None:
        seed_q = np.array([(l+h)/2 for l, h in LIMITS]) # Middle of range
        
    def objective(q):
        # FK
        T_curr = forward_kinematics(q)
        pos_curr = T_curr[:3, 3]
        rot_curr = T_curr[:3, :3]
        
        # Position error constraint (L2 norm)
        pos_err = np.linalg.norm(pos_curr - target_pos)
        
        # Orientation error (using rotation difference)
        # diff_R = R_curr * R_target^T, should be Identity
        # We minimize trace distance or angle difference
        
        # Simple approach: Frobenius norm of difference
        rot_err = np.linalg.norm(rot_curr - target_rot_matrix)
        
        # Weighted sum
        return pos_err + 0.5 * rot_err

    # Joint limits
    bnds = LIMITS
    
    res = minimize(
        objective, 
        seed_q, 
        method='SLSQP', 
        bounds=bnds, 
        tol=1e-4,
        options={'maxiter': 100}
    )
    
    return res.success, res.x, res.fun

def generate_workspace(num_samples=1000, fixed_rpy=[0, 1.57, 0]):
    """
    Samples points in a box and checks reachability with fixed orientation.
    fixed_rpy: desired [roll, pitch, yaw] of end-effector.
    """
    
    # Define search space (Box)
    x_range = [-0.5, 0.5]
    y_range = [-0.5, 0.5]
    z_range = [0.0, 0.6]
    
    target_rot = R.from_euler('xyz', fixed_rpy).as_matrix()
    
    valid_points = []
    
    print(f"Starting sampling... Target samples: {num_samples}")
    start_time = time.time()
    
    # We sample more candidates because many will be unreachable
    attempts = 0
    max_attempts = num_samples * 50 
    
    while len(valid_points) < num_samples and attempts < max_attempts:
        attempts += 1
        
        # Random position
        x = np.random.uniform(*x_range)
        y = np.random.uniform(*y_range)
        z = np.random.uniform(*z_range)
        target_pos = np.array([x, y, z])
        
        if np.linalg.norm(target_pos) > 0.8: # Optimization: Skip points clearly out of reach
            continue
            
        # Use a random valid pose as seed if possible, or random seed to escape local minima
        seed = np.random.uniform([l for l, h in LIMITS], [h for l, h in LIMITS])
        
        success, q_sol, error = inverse_kinematics(target_pos, target_rot, seed)
        
        if success and error < 1e-3:
            valid_points.append([x, y, z])
            if len(valid_points) % 100 == 0:
                print(f"Found {len(valid_points)} points...")
    
    elapsed = time.time() - start_time
    print(f"Finished. Found {len(valid_points)} points in {elapsed:.2f}s. Efficiency: {len(valid_points)/attempts*100:.2f}%")
    
    return np.array(valid_points)

def save_html_plot(points):
    """Generates a self-contained HTML file with Plotly visualization."""
    
    # Extract coordinates
    x = points[:, 0].tolist()
    y = points[:, 1].tolist()
    z = points[:, 2].tolist()
    
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Piper Robot Workspace</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ margin: 0; padding: 0; font-family: sans-serif; }}
        #plot {{ width: 100vw; height: 100vh; }}
        .info {{ position: absolute; top: 10px; left: 10px; background: rgba(255,255,255,0.8); padding: 10px; z-index: 100; }}
    </style>
</head>
<body>
    <div class="info">
        <h3>Piper Robot Fixed-Orientation Workspace</h3>
        <p>Total Points: {len(points)}</p>
        <p>Orientation: Fixed (Home Pose)</p>
    </div>
    <div id="plot"></div>
    <script>
        var trace1 = {{
            x: {x},
            y: {y},
            z: {z},
            mode: 'markers',
            marker: {{
                size: 2,
                color: '#1f77b4',
                opacity: 0.6
            }},
            type: 'scatter3d',
            name: 'Reachable Points'
        }};
        
        var trace2 = {{
            x: [0],
            y: [0],
            z: [0],
            mode: 'markers',
            marker: {{
                size: 10,
                color: 'red',
                symbol: 'circle'
            }},
            type: 'scatter3d',
            name: 'Base'
        }};

        var trace3 = {{
            x: {x},
            y: {y},
            z: {z},
            alphahull: 7,
            opacity: 0.3,
            color: '#1f77b4',
            type: 'mesh3d',
            name: 'Workspace Surface'
        }};

        var data = [trace1, trace2, trace3];

        var layout = {{
            margin: {{l: 0, r: 0, b: 0, t: 0}},
            scene: {{
                xaxis: {{title: 'X [m]'}},
                yaxis: {{title: 'Y [m]'}},
                zaxis: {{title: 'Z [m]'}},
                aspectmode: 'data'
            }}
        }};

        Plotly.newPlot('plot', data, layout);
    </script>
</body>
</html>
    """
    
    with open('workspace_viewer.html', 'w') as f:
        f.write(html_content)
    print("Saved interactive plot to workspace_viewer.html")

def plot_workspace(points):
    # Save to JSON/HTML
    save_html_plot(points)

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')
    
    if len(points) > 0:
        ax.scatter(points[:, 0], points[:, 1], points[:, 2], s=1, c='b', alpha=0.5, label='Reachable')
    
    # Plot origin
    ax.scatter([0], [0], [0], s=50, c='r', marker='o', label='Base')
    
    ax.set_xlabel('X [m]')
    ax.set_ylabel('Y [m]')
    ax.set_zlabel('Z [m]')
    ax.set_title('Piper Robot Fixed-Orientation Workspace')
    ax.legend()
    
    # Set equal aspect ratio (hack for matplotlib 3d)
    # Create cubic bounding box for equal aspect ratio
    max_range = np.array([points[:,0].max()-points[:,0].min(), 
                          points[:,1].max()-points[:,1].min(), 
                          points[:,2].max()-points[:,2].min()]).max() / 2.0
    
    mid_x = (points[:,0].max()+points[:,0].min()) * 0.5
    mid_y = (points[:,1].max()+points[:,1].min()) * 0.5
    mid_z = (points[:,2].max()+points[:,2].min()) * 0.5
    
    ax.set_xlim(mid_x - max_range, mid_x + max_range)
    ax.set_ylim(mid_y - max_range, mid_y + max_range)
    ax.set_zlim(mid_z - max_range, mid_z + max_range)
    
    plt.savefig('workspace_plot.png')
    print("Plot saved to workspace_plot.png")

if __name__ == "__main__":
    # Define a fixed orientation: Pointing forward (or down)
    # Let's try pointing DOWN: Pitch = 90 deg?
    # Xacro shows complex chain.
    # Let's try to match "Home" orientation first to be safe, or just fixed identity?
    # Prompt says "Fixed posture". I will pick [0, 0, 0] relative to Base Frame for simplicity,
    # or better, let's find the orientation at q=0 and keep THAT fixed.
    
    # Check orientation at home
    T_home = forward_kinematics([0]*6)
    r_home = R.from_matrix(T_home[:3, :3]).as_euler('xyz')
    print(f"Home Pose Orientation (RPY): {r_home}")
    
    # Use Home orientation as the fixed target
    print("Using Home Orientation as fixed constraint.")
    
    points = generate_workspace(num_samples=2000, fixed_rpy=r_home)
    plot_workspace(points)
