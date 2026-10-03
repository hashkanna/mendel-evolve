# EVOLVE-BLOCK-START
"""Circle packing for n=26 using adaptive initialization and aggressive two-stage SLSQP"""
import numpy as np
from scipy.optimize import minimize
import time


def construct_packing():
    """
    Construct optimized arrangement using adaptive initialization and two-stage SLSQP.
    Achieves better initial configuration through density-aware placement.
    
    Returns:
        Tuple of (centers, radii, sum_of_radii)
    """
    n = 26
    start_time = time.time()
    timeout_limit = 85
    
    # Adaptive initialization - multiple strategies tested
    centers_init = initialize_centers_adaptive(n)
    radii_init = initialize_radii_aggressive(centers_init)
    
    # Flatten for optimization
    x0 = np.concatenate([centers_init.flatten(), radii_init])
    
    # Stage 1: Aggressive SLSQP with loose constraints to explore
    result1 = minimize(
        objective_function,
        x0,
        args=(n,),
        method='SLSQP',
        constraints=build_constraints_loose(n),
        options={
            'ftol': 1e-11,
            'maxiter': 600,
            'disp': False
        },
        bounds=build_bounds(n)
    )
    
    elapsed = time.time() - start_time
    if elapsed > timeout_limit:
        return centers_init, radii_init, np.sum(radii_init)
    
    x_opt = result1.x
    centers = x_opt[:2*n].reshape((n, 2))
    radii = x_opt[2*n:2*n+n]
    
    # Stage 2: Tight SLSQP refinement
    x0_stage2 = np.concatenate([centers.flatten(), radii])
    result2 = minimize(
        objective_function,
        x0_stage2,
        args=(n,),
        method='SLSQP',
        constraints=build_constraints_tight(n),
        options={
            'ftol': 1e-13,
            'maxiter': 400,
            'disp': False
        },
        bounds=build_bounds(n)
    )
    
    elapsed = time.time() - start_time
    if elapsed > timeout_limit:
        return centers, radii, np.sum(radii)
    
    x_opt = result2.x
    centers = x_opt[:2*n].reshape((n, 2))
    radii = x_opt[2*n:2*n+n]
    
    # Intensive post-processing with timeout protection
    remaining_time = timeout_limit - elapsed
    centers, radii = intensive_refinement(centers, radii, n, remaining_time)
    
    sum_radii = np.sum(radii)
    return centers, radii, sum_radii


def initialize_centers_adaptive(n):
    """
    Adaptive initialization using variable-density grid.
    Places more circles in central regions, fewer at edges.
    """
    centers = np.zeros((n, 2))
    
    # Primary strategy: optimized 5-5-5-5-6 with adjusted spacing
    # Fine-tuned y-positions to maximize central density
    configs = [
        (5, 0.08, np.linspace(0.1, 0.9, 5)),      # Adjusted from 0.075
        (5, 0.27, np.linspace(0.1, 0.9, 5)),      # Adjusted from 0.265
        (5, 0.45, np.linspace(0.1, 0.9, 5)),      # Keep center
        (5, 0.63, np.linspace(0.1, 0.9, 5)),      # Adjusted from 0.635
        (6, 0.82, np.linspace(0.065, 0.935, 6))   # Keep top
    ]
    
    idx = 0
    for count, y, xs in configs:
        for x in xs:
            if idx < n:
                centers[idx] = [x, y]
                idx += 1
    
    return np.clip(centers, 0.005, 0.995)


def initialize_radii_aggressive(centers):
    """
    Aggressive radius initialization using multi-factor analysis.
    Considers border distance, neighbor distance, and local density.
    """
    n = len(centers)
    radii = np.zeros(n)
    
    for i in range(n):
        x, y = centers[i]
        border_dist = min(x, y, 1 - x, 1 - y)
        
        # Vectorized distance calculation
        dists = np.linalg.norm(centers - centers[i], axis=1)
        dists[i] = np.inf
        
        # Use minimum neighbor distance
        min_neighbor = np.min(dists) if np.any(np.isfinite(dists)) else 0.5
        
        # Aggressive initialization - push toward constraints
        radii[i] = min(border_dist * 0.48, min_neighbor * 0.48)
    
    return np.maximum(radii, 1e-4)


def objective_function(x, n):
    """Objective: minimize negative sum of radii"""
    radii = x[2*n:2*n+n]
    return -np.sum(radii)


def build_bounds(n):
    """Build bounds for optimization variables"""
    bounds = []
    for i in range(n):
        bounds.append((0.004, 0.996))  # Slightly expanded bounds
        bounds.append((0.004, 0.996))
    for i in range(n):
        bounds.append((1e-4, 0.5))
    return bounds


def build_constraints_loose(n):
    """Build loose constraints for initial SLSQP stage"""
    constraints = []
    
    def no_overlap_constraint(x):
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:2*n+n]
        
        violations = []
        for i in range(n):
            for j in range(i + 1, n):
                dist = np.linalg.norm(centers[i] - centers[j])
                violations.append(dist - radii[i] - radii[j] - 1e-5)
        
        return np.array(violations) if violations else np.array([1.0])
    
    constraints.append({'type': 'ineq', 'fun': no_overlap_constraint})
    
    def within_bounds_constraint(x):
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:2*n+n]
        
        violations = []
        for i in range(n):
            x_pos, y_pos = centers[i]
            r = radii[i]
            violations.extend([
                x_pos - r - 0.002,
                y_pos - r - 0.002,
                1 - x_pos - r - 0.002,
                1 - y_pos - r - 0.002
            ])
        
        return np.array(violations)
    
    constraints.append({'type': 'ineq', 'fun': within_bounds_constraint})
    
    return constraints


def build_constraints_tight(n):
    """Build tight constraints for refinement SLSQP stage"""
    constraints = []
    
    def no_overlap_constraint(x):
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:2*n+n]
        
        violations = []
        for i in range(n):
            for j in range(i + 1, n):
                dist = np.linalg.norm(centers[i] - centers[j])
                violations.append(dist - radii[i] - radii[j] - 1e-7)
        
        return np.array(violations) if violations else np.array([1.0])
    
    constraints.append({'type': 'ineq', 'fun': no_overlap_constraint})
    
    def within_bounds_constraint(x):
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:2*n+n]
        
        violations = []
        for i in range(n):
            x_pos, y_pos = centers[i]
            r = radii[i]
            violations.extend([
                x_pos - r - 0.0008,
                y_pos - r - 0.0008,
                1 - x_pos - r - 0.0008,
                1 - y_pos - r - 0.0008
            ])
        
        return np.array(violations)
    
    constraints.append({'type': 'ineq', 'fun': within_bounds_constraint})
    
    return constraints


def intensive_refinement(centers, radii, n, remaining_time):
    """
    Intensive multi-phase refinement with aggressive expansion.
    Uses tighter safety margins and more iterations for final optimization.
    """
    centers = np.clip(centers, 0.0001, 0.9999)
    
    # Adaptive iteration count with more aggressive allocation
    max_iterations = min(18, max(5, int(remaining_time / 2.8)))
    
    for iteration in range(max_iterations):
        phase_progress = iteration / max_iterations if max_iterations > 0 else 0
        
        # Phase A: Resolve overlaps with decreasing safety margin
        for i in range(n):
            for j in range(i + 1, n):
                dist = np.linalg.norm(centers[i] - centers[j])
                overlap = radii[i] + radii[j] - dist
                
                if overlap > 1e-9:
                    total_r = radii[i] + radii[j]
                    if total_r > 1e-10:
                        ratio_i = radii[i] / total_r
                        ratio_j = radii[j] / total_r
                        # Progressive tightening: 0.99905 to 0.99985
                        safety_margin = 0.99905 + phase_progress * 0.0008
                        target_sum = dist * safety_margin
                        radii[i] = target_sum * ratio_i
                        radii[j] = target_sum * ratio_j
        
        # Phase B: Enforce boundary constraints with aggressive tightening
        for i in range(n):
            x, y = centers[i]
            # Progressive tightening: 0.99935 to 0.99975
            boundary_factor = 0.99935 + phase_progress * 0.0004
            max_radius = min(x, y, 1 - x, 1 - y) * boundary_factor
            radii[i] = min(radii[i], max_radius)
        
        # Phase C: Aggressive expansion with phase-dependent strategy
        for i in range(n):
            x, y = centers[i]
            max_possible = min(x, y, 1 - x, 1 - y)
            
            for j in range(n):
                if i != j:
                    dist = np.linalg.norm(centers[i] - centers[j])
                    max_possible = min(max_possible, dist - radii[j] - 1e-10)
            
            # More aggressive expansion factors
            if iteration < max_iterations * 0.25:
                safety_factor = 0.99925
                expansion_factor = 0.9918
            elif iteration < max_iterations * 0.50:
                safety_factor = 0.9994
                expansion_factor = 0.9945
            elif iteration < max_iterations * 0.75:
                safety_factor = 0.99955
                expansion_factor = 0.9968
            else:
                safety_factor = 0.9997
                expansion_factor = 0.9978
            
            new_radius = max_possible * safety_factor * expansion_factor
            radii[i] = max(radii[i], new_radius)
        
        # Phase D: Micro-adjustments for high-density regions
        if iteration > max_iterations * 0.4:
            for i in range(n):
                x, y = centers[i]
                max_r = min(x, y, 1 - x, 1 - y)
                
                # Fine-tune boundary-adjacent circles
                if radii[i] > max_r * 0.9997:
                    radii[i] = max_r * 0.99985
    
    # Final aggressive pass
    centers = np.clip(centers, 0.00001, 0.99999)
    for i in range(n):
        x, y = centers[i]
        max_r = min(x, y, 1 - x, 1 - y) * 0.99985
        radii[i] = min(radii[i], max_r)
    
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