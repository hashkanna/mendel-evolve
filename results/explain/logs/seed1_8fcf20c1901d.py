# EVOLVE-BLOCK-START
"""Constructor-based circle packing for n=26 using scipy joint optimization of centers and radii"""
import numpy as np
from scipy.optimize import minimize


def construct_packing():
    """
    Construct 26 circles in unit square using joint scipy optimization
    of both center positions and radii for maximum sum.
    
    Returns:
        Tuple of (centers, radii, sum_of_radii)
    """
    n = 26
    
    # Phase 1: Initialize with proven hybrid layout
    centers_init = initialize_proven_layout(n)
    centers_init = np.clip(centers_init, 0.001, 0.999)
    
    # Phase 2: Quick aggressive radius computation for warm start
    radii_init = compute_max_radii_aggressive(centers_init)
    
    # Phase 3: Joint optimization of centers and radii using scipy
    centers, radii = optimize_joint_scipy(centers_init, radii_init)
    
    sum_radii = np.sum(radii)
    return centers, radii, sum_radii


def initialize_proven_layout(n):
    """
    Initialize with the proven hybrid layout.
    5x5 core grid (25 circles) + 1 strategic bottom-center placement.
    """
    centers = np.zeros((n, 2))
    
    # Core: 5x5 grid with optimal spacing of 0.18
    grid_size = 5
    spacing = 0.18
    grid_width = (grid_size - 1) * spacing
    start_x = 0.5 - grid_width / 2
    start_y = 0.5 - grid_width / 2
    
    idx = 0
    for row in range(grid_size):
        for col in range(grid_size):
            x = start_x + col * spacing
            y = start_y + row * spacing
            centers[idx] = [x, y]
            idx += 1
    
    # 26th circle: Strategic bottom-center placement
    centers[idx] = [0.5, 0.08]
    
    return centers


def compute_max_radii_aggressive(centers):
    """
    Quick aggressive radius computation for warm start.
    """
    n = centers.shape[0]
    
    # Precompute all pairwise distances
    distances = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.linalg.norm(centers[i] - centers[j])
            distances[i, j] = dist
            distances[j, i] = dist
    
    # Precompute border constraints
    border_dists = np.array([
        min(centers[i, 0], centers[i, 1], 1 - centers[i, 0], 1 - centers[i, 1])
        for i in range(n)
    ])
    
    # Initialize radii
    radii = border_dists.copy()
    
    # Phase 1: Overlap resolution
    for iteration in range(35):
        radii_old = radii.copy()
        
        violations = []
        for i in range(n):
            for j in range(i + 1, n):
                dist = distances[i, j]
                if dist < 1e-10:
                    radii[i] *= 0.1
                    radii[j] *= 0.1
                    continue
                
                overlap = radii[i] + radii[j] - dist
                if overlap > 1e-15:
                    violations.append((overlap / dist, i, j, dist))
        
        if not violations:
            break
        
        violations.sort(reverse=True)
        processed = set()
        
        for violation, i, j, dist in violations:
            if i in processed and j in processed:
                continue
            
            total = radii[i] + radii[j]
            if iteration < 10:
                safety = 0.9997
            elif iteration < 20:
                safety = 0.99985
            else:
                safety = 0.999925
            
            scale = (dist * safety) / total
            radii[i] *= scale
            radii[j] *= scale
            processed.add(i)
            processed.add(j)
        
        radii = np.minimum(radii, border_dists)
        
        if np.allclose(radii, radii_old, rtol=1e-12, atol=1e-14):
            break
    
    # Phase 2: Growth
    for growth_iter in range(100):
        radii_old = radii.copy()
        growth_made = False
        
        for i in range(n):
            max_r = border_dists[i]
            
            for j in range(n):
                if i != j and distances[i, j] > 1e-11:
                    max_r = min(max_r, distances[i, j] - radii[j] - 1e-13)
            
            if max_r > radii[i] + 1e-14:
                if growth_iter < 30:
                    safety = 0.99998
                else:
                    safety = 0.999985
                
                radii[i] = max_r * safety
                growth_made = True
        
        radii = np.minimum(radii, border_dists)
        
        if not growth_made or np.allclose(radii, radii_old, rtol=1e-14, atol=1e-16):
            break
    
    return np.maximum(radii, 1e-12)


def optimize_joint_scipy(centers_init, radii_init):
    """
    Joint optimization of both center positions and radii using scipy SLSQP.
    This is the key breakthrough - optimizing layout AND sizes together.
    """
    n = centers_init.shape[0]
    
    # Flatten: [x1, y1, x2, y2, ..., xn, yn, r1, r2, ..., rn]
    x0 = np.concatenate([centers_init.flatten(), radii_init])
    
    def objective(x):
        """Minimize negative sum of radii (maximize sum)"""
        radii = x[2*n:]
        return -np.sum(radii)
    
    def constraint_border(x, i):
        """Each radius must not exceed distance to border"""
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:]
        border_dist = min(centers[i, 0], centers[i, 1], 
                         1 - centers[i, 0], 1 - centers[i, 1])
        return border_dist - radii[i] + 1e-13
    
    def constraint_no_overlap(x, i, j):
        """Circles i and j must not overlap"""
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:]
        dist = np.linalg.norm(centers[i] - centers[j])
        return dist - radii[i] - radii[j] + 1e-13
    
    def constraint_bounds(x, i):
        """Each center coordinate must be in [0.01, 0.99]"""
        centers = x[:2*n].reshape((n, 2))
        return min(centers[i, 0] - 0.01, centers[i, 1] - 0.01,
                   0.99 - centers[i, 0], 0.99 - centers[i, 1])
    
    # Build constraints list
    constraints = []
    
    # Border constraints for each circle
    for i in range(n):
        constraints.append({
            'type': 'ineq',
            'fun': lambda x, i=i: constraint_border(x, i)
        })
    
    # Non-overlapping constraints for all pairs
    for i in range(n):
        for j in range(i + 1, n):
            constraints.append({
                'type': 'ineq',
                'fun': lambda x, i=i, j=j: constraint_no_overlap(x, i, j)
            })
    
    # Bound constraints for centers
    for i in range(n):
        constraints.append({
            'type': 'ineq',
            'fun': lambda x, i=i: constraint_bounds(x, i)
        })
    
    # Bounds for optimization variables
    bounds = []
    # Center coordinates: [0.01, 0.99]
    for i in range(n):
        bounds.append((0.01, 0.99))  # x coordinate
        bounds.append((0.01, 0.99))  # y coordinate
    # Radii: [1e-12, 0.5]
    for i in range(n):
        bounds.append((1e-12, 0.5))
    
    # Run optimization with aggressive settings
    result = minimize(
        objective,
        x0,
        method='SLSQP',
        bounds=bounds,
        constraints=constraints,
        options={
            'maxiter': 500,
            'ftol': 1e-12,
            'iprint': 0,
            'disp': False
        }
    )
    
    # Extract optimized centers and radii
    x_opt = result.x
    centers_opt = x_opt[:2*n].reshape((n, 2))
    radii_opt = x_opt[2*n:]
    
    # Post-process: ensure validity
    centers_opt = np.clip(centers_opt, 0.01, 0.99)
    radii_opt = np.maximum(radii_opt, 1e-12)
    
    # Quick final validation pass
    radii_opt = validate_and_tighten(centers_opt, radii_opt)
    
    return centers_opt, radii_opt


def validate_and_tighten(centers, radii):
    """
    Final validation and tightening of radii to ensure all constraints.
    """
    n = centers.shape[0]
    
    # Precompute distances
    distances = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.linalg.norm(centers[i] - centers[j])
            distances[i, j] = dist
            distances[j, i] = dist
    
    # Border constraints
    border_dists = np.array([
        min(centers[i, 0], centers[i, 1], 1 - centers[i, 0], 1 - centers[i, 1])
        for i in range(n)
    ])
    
    # Enforce border constraints
    radii = np.minimum(radii, border_dists)
    
    # Enforce non-overlapping constraints
    for i in range(n):
        for j in range(n):
            if i != j and distances[i, j] > 1e-11:
                radii[i] = min(radii[i], distances[i, j] - radii[j] - 1e-14)
    
    return np.maximum(radii, 1e-12)


# EVOLVE-BLOCK-END


# This part remains fixed (not evolved)
def run_packing():
    """Run the circle packing constructor for n=26"""
    centers, radii, sum_radii = construct_packing()
    return centers, radii, sum_radii


def visualize(centers, radii):
    """
    Visualize the circle packing

    Args:
        centers: np.array of shape (n, 2) with (x, y) coordinates
        radii: np.array of shape (n) with radius of each circle
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    fig, ax = plt.subplots(figsize=(8, 8))

    # Draw unit square
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.grid(True)

    # Draw circles
    for i, (center, radius) in enumerate(zip(centers, radii)):
        circle = Circle(center, radius, alpha=0.5)
        ax.add_patch(circle)
        ax.text(center[0], center[1], str(i), ha="center", va="center")

    plt.title(f"Circle Packing (n={len(centers)}, sum={sum(radii):.6f})")
    plt.show()


if __name__ == "__main__":
    centers, radii, sum_radii = run_packing()
    print(f"Sum of radii: {sum_radii}")

    # Uncomment to visualize:
    # visualize(centers, radii)