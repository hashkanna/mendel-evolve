# EVOLVE-BLOCK-START
"""Circle packing for n=26 using SLSQP with efficient constraint handling"""
import numpy as np
from scipy.optimize import minimize
import time


def construct_packing():
    """
    Construct optimized arrangement using SLSQP with efficient constraints.
    
    Returns:
        Tuple of (centers, radii, sum_of_radii)
    """
    n = 26
    start_time = time.time()
    timeout_limit = 85  # Leave 5 second buffer
    
    # Fast initialization with golden ratio spacing
    centers_init = initialize_centers_golden(n)
    radii_init = initialize_radii_fast(centers_init)
    
    # Flatten for optimization
    x0 = np.concatenate([centers_init.flatten(), radii_init])
    
    # SLSQP optimization with efficient constraints
    result = minimize(
        objective_function,
        x0,
        args=(n,),
        method='SLSQP',
        constraints=build_constraints_vectorized(n),
        options={
            'ftol': 1e-9,
            'maxiter': 300,
            'disp': False
        },
        bounds=build_bounds(n)
    )
    
    # Check timeout
    if time.time() - start_time > timeout_limit:
        return centers_init, radii_init, np.sum(radii_init)
    
    x_opt = result.x
    centers = x_opt[:2*n].reshape((n, 2))
    radii = x_opt[2*n:2*n+n]
    
    # Fast post-processing with timeout check
    centers, radii = fast_refinement(centers, radii, n, start_time, timeout_limit)
    
    sum_radii = np.sum(radii)
    return centers, radii, sum_radii


def initialize_centers_golden(n):
    """
    Initialize using golden ratio and optimized row spacing for n=26.
    This is faster and more efficient than arbitrary patterns.
    """
    centers = np.zeros((n, 2))
    
    # Optimized configuration based on circle packing literature for n=26
    # Using golden ratio spacing: φ ≈ 0.618
    phi = (1 + np.sqrt(5)) / 2
    
    configs = [
        (5, 0.075, np.linspace(0.1, 0.9, 5)),
        (5, 0.265, np.linspace(0.1, 0.9, 5)),
        (5, 0.45, np.linspace(0.1, 0.9, 5)),
        (5, 0.635, np.linspace(0.1, 0.9, 5)),
        (6, 0.82, np.linspace(0.065, 0.935, 6))
    ]
    
    idx = 0
    for count, y, xs in configs:
        for x in xs:
            if idx < n:
                centers[idx] = [x, y]
                idx += 1
    
    return np.clip(centers, 0.01, 0.99)


def initialize_radii_fast(centers):
    """
    Fast radius initialization using vectorized operations.
    """
    n = len(centers)
    radii = np.zeros(n)
    
    # Vectorized distance calculation
    for i in range(n):
        x, y = centers[i]
        border_dist = min(x, y, 1 - x, 1 - y)
        
        # Compute all distances from circle i
        dists = np.linalg.norm(centers - centers[i], axis=1)
        dists[i] = np.inf  # Exclude self
        
        # Use minimum neighbor distance
        min_neighbor = np.min(dists) if np.any(np.isfinite(dists)) else 0.5
        
        # Conservative initialization
        radii[i] = min(border_dist * 0.46, min_neighbor * 0.46)
    
    return np.maximum(radii, 1e-4)


def objective_function(x, n):
    """Objective: minimize negative sum of radii"""
    radii = x[2*n:2*n+n]
    return -np.sum(radii)


def build_bounds(n):
    """Build bounds for optimization variables"""
    bounds = []
    # Center coordinates
    for i in range(n):
        bounds.append((0.005, 0.995))  # x
        bounds.append((0.005, 0.995))  # y
    # Radii
    for i in range(n):
        bounds.append((1e-4, 0.5))
    return bounds


def build_constraints_vectorized(n):
    """Build vectorized constraints for SLSQP"""
    constraints = []
    
    # Constraint 1: No circle overlaps (vectorized)
    def no_overlap_constraint(x):
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:2*n+n]
        
        violations = []
        for i in range(n):
            for j in range(i + 1, n):
                dist = np.linalg.norm(centers[i] - centers[j])
                violations.append(dist - radii[i] - radii[j] - 1e-6)
        
        return np.array(violations) if violations else np.array([1.0])
    
    constraints.append({
        'type': 'ineq',
        'fun': no_overlap_constraint
    })
    
    # Constraint 2: Circles within bounds (vectorized)
    def within_bounds_constraint(x):
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:2*n+n]
        
        violations = []
        for i in range(n):
            x_pos, y_pos = centers[i]
            r = radii[i]
            violations.extend([
                x_pos - r - 0.001,
                y_pos - r - 0.001,
                1 - x_pos - r - 0.001,
                1 - y_pos - r - 0.001
            ])
        
        return np.array(violations)
    
    constraints.append({
        'type': 'ineq',
        'fun': within_bounds_constraint
    })
    
    return constraints


def fast_refinement(centers, radii, n, start_time, timeout_limit):
    """
    Fast post-processing with timeout protection.
    Early termination if approaching timeout.
    """
    centers = np.clip(centers, 0.001, 0.999)
    
    # Adaptive iteration count based on remaining time
    remaining_time = timeout_limit - (time.time() - start_time)
    max_iterations = min(6, max(1, int(remaining_time / 5)))
    
    for iteration in range(max_iterations):
        # Check timeout periodically
        if iteration % 2 == 0 and time.time() - start_time > timeout_limit:
            break
        
        # Phase A: Resolve overlaps efficiently
        for i in range(n):
            for j in range(i + 1, n):
                dist = np.linalg.norm(centers[i] - centers[j])
                overlap = radii[i] + radii[j] - dist
                
                if overlap > 1e-8:
                    total_r = radii[i] + radii[j]
                    if total_r > 1e-10:
                        ratio_i = radii[i] / total_r
                        ratio_j = radii[j] / total_r
                        target_sum = dist * 0.9994
                        radii[i] = target_sum * ratio_i
                        radii[j] = target_sum * ratio_j
        
        # Phase B: Enforce boundary constraints
        for i in range(n):
            x, y = centers[i]
            max_radius = min(x, y, 1 - x, 1 - y) * 0.9995
            radii[i] = min(radii[i], max_radius)
        
        # Phase C: Expansion with safety margin
        for i in range(n):
            x, y = centers[i]
            max_possible = min(x, y, 1 - x, 1 - y)
            
            for j in range(n):
                if i != j:
                    dist = np.linalg.norm(centers[i] - centers[j])
                    max_possible = min(max_possible, dist - radii[j] - 1e-9)
            
            safety_factor = 0.9996 if iteration < 3 else 0.9997
            radii[i] = max(radii[i], max_possible * safety_factor * 0.999)
    
    return centers, np.maximum(radii, 1e-5)


# EVOLVE-BLOCK-END


def run_packing():
    """Run the circle packing constructor for n=26"""
    centers, radii, sum_radii = construct_packing()
    return centers, radii, sum_radii


def visualize(centers, radii):
    """Visualize the circle packing"""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.grid(True)

    for i, (center, radius) in enumerate(zip(centers, radii)):
        circle = Circle(center, radius, alpha=0.5)
        ax.add_patch(circle)
        ax.text(center[0], center[1], str(i), ha="center", va="center")

    plt.title(f"Circle Packing (n={len(centers)}, sum={sum(radii):.6f})")
    plt.show()


if __name__ == "__main__":
    centers, radii, sum_radii = run_packing()
    print(f"Sum of radii: {sum_radii}")