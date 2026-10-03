# EVOLVE-BLOCK-START
"""Circle packing for n=26 using adaptive constraint optimization with smart refinement"""
import numpy as np
from scipy.optimize import minimize


def construct_packing():
    """
    Construct an arrangement of 26 circles in a unit square using adaptive
    constraint optimization with intelligent refinement.

    Returns:
        Tuple of (centers, radii, sum_of_radii)
    """
    n = 26
    
    # Best initialization strategy based on performance history
    centers, radii = generate_smart_initial(n)
    
    # Optimize with adaptive constraints
    centers, radii = adaptive_optimize(centers, radii, n)
    
    # Aggressive post-processing refinement
    centers, radii = aggressive_refinement(centers, radii, n)
    
    sum_radii = np.sum(radii)
    return centers, radii, sum_radii


def generate_smart_initial(n):
    """Smart initialization combining proven patterns."""
    centers = np.zeros((n, 2))
    radii = np.zeros(n)
    
    # Core: 5x5 grid (25 circles) + 1 center
    spacing = 0.19
    start = 0.5 - 2 * spacing
    
    idx = 0
    for row in range(5):
        for col in range(5):
            x = start + col * spacing
            y = start + row * spacing
            centers[idx] = [np.clip(x, 0.02, 0.98), np.clip(y, 0.02, 0.98)]
            
            # Variable radius: larger in center, smaller at edges
            dist = np.sqrt((col - 2)**2 + (row - 2)**2)
            radii[idx] = 0.050 - 0.006 * dist
            idx += 1
    
    if idx < n:
        centers[idx] = [0.5, 0.5]
        radii[idx] = 0.055
    
    return centers, radii


def adaptive_optimize(centers, radii, n):
    """Optimize using adaptive constraint density."""
    x0 = np.concatenate([centers.flatten(), radii])
    
    # Phase 1: Relaxed optimization with sparse constraints
    constraints = get_adaptive_constraints(n, sparse=True)
    
    result1 = minimize(
        lambda x: -np.sum(x[2*n:]),
        x0,
        method='SLSQP',
        constraints=constraints,
        options={'maxiter': 500, 'ftol': 1e-11, 'iprint': 0}
    )
    
    if not result1.success and result1.fun >= 0:
        return centers, radii
    
    x1 = result1.x
    
    # Phase 2: Dense optimization with all constraints
    constraints = get_adaptive_constraints(n, sparse=False)
    
    result2 = minimize(
        lambda x: -np.sum(x[2*n:]),
        x1,
        method='SLSQP',
        constraints=constraints,
        options={'maxiter': 700, 'ftol': 1e-13, 'iprint': 0}
    )
    
    optimized = result2.x
    centers = optimized[:2*n].reshape(n, 2)
    radii = optimized[2*n:]
    
    centers = np.clip(centers, 0.0001, 0.9999)
    radii = np.clip(radii, 0.00001, 0.5)
    
    return centers, radii


def get_adaptive_constraints(n, sparse=False):
    """Generate constraints adaptively based on optimization phase."""
    constraints = []
    
    # Boundary constraints (always included)
    for i in range(n):
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i: x[2*i] - 0.0001})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i: 0.9999 - x[2*i]})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i: x[2*i + 1] - 0.0001})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i: 0.9999 - x[2*i + 1]})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i, n=n: x[n*2 + i] - 0.00001})
    
    # Circle boundary constraints
    for i in range(n):
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i, n=n: x[2*i] - x[n*2 + i]})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i, n=n: x[2*i + 1] - x[n*2 + i]})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i, n=n: 1.0 - x[2*i] - x[n*2 + i]})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i, n=n: 1.0 - x[2*i + 1] - x[n*2 + i]})
    
    # Pairwise overlap constraints
    if sparse:
        # Only nearest neighbors during coarse phase
        for i in range(n):
            for j in range(i + 1, min(i + 8, n)):
                constraints.append({
                    'type': 'ineq',
                    'fun': lambda x, i=i, j=j, n=n: circle_distance(x, i, j, n)
                })
    else:
        # All pairs during fine phase
        for i in range(n):
            for j in range(i + 1, n):
                constraints.append({
                    'type': 'ineq',
                    'fun': lambda x, i=i, j=j, n=n: circle_distance(x, i, j, n)
                })
    
    return constraints


def circle_distance(x, i, j, n):
    """Distance constraint between circles i and j."""
    xi, yi = x[2*i], x[2*i + 1]
    xj, yj = x[2*j], x[2*j + 1]
    ri, rj = x[n*2 + i], x[n*2 + j]
    
    dist = np.sqrt((xi - xj)**2 + (yi - yj)**2)
    return dist - (ri + rj) - 1e-10


def aggressive_refinement(centers, radii, n):
    """Aggressive post-optimization refinement."""
    centers = centers.copy()
    radii = radii.copy()
    
    # Phase 1: Maximize radii aggressively (40 iterations)
    for iteration in range(40):
        for i in range(n):
            cx, cy = centers[i]
            # Maximum possible radius from boundaries
            max_r = min(cx, cy, 1.0 - cx, 1.0 - cy) * 0.99999
            
            # Constrain by all other circles
            for j in range(n):
                if i != j:
                    dist = np.linalg.norm(centers[i] - centers[j])
                    max_r = min(max_r, max(0, dist - radii[j] - 1e-13))
            
            radii[i] = min(radii[i], max_r)
    
    # Phase 2: Fine position adjustments with multiple scales
    for scale in [0.02, 0.01, 0.005, 0.002, 0.001, 0.0005]:
        for _ in range(12):
            for i in range(n):
                best_pos = centers[i].copy()
                best_r = radii[i]
                
                # Try 9 nearby positions
                for dx in [-scale, 0, scale]:
                    for dy in [-scale, 0, scale]:
                        test_pos = best_pos + np.array([dx, dy])
                        test_pos = np.clip(test_pos, 0.00001, 0.99999)
                        
                        cx, cy = test_pos
                        test_r = min(cx, cy, 1.0 - cx, 1.0 - cy) * 0.99999
                        
                        # Check against all other circles
                        for j in range(n):
                            if i != j:
                                dist = np.linalg.norm(test_pos - centers[j])
                                test_r = min(test_r, max(0, dist - radii[j] - 1e-13))
                        
                        if test_r > best_r + 1e-15:
                            best_r = test_r
                            best_pos = test_pos
                
                centers[i] = best_pos
                radii[i] = best_r
    
    # Phase 3: Final radius maximization pass
    for _ in range(50):
        for i in range(n):
            cx, cy = centers[i]
            max_r = min(cx, cy, 1.0 - cx, 1.0 - cy) * 0.99999999
            
            for j in range(n):
                if i != j:
                    dist = np.linalg.norm(centers[i] - centers[j])
                    max_r = min(max_r, max(0, dist - radii[j] - 1e-14))
            
            radii[i] = min(radii[i], max_r)
    
    return centers, np.clip(radii, 0.00001, 0.5)


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
        ax.text(center[0], center[1], str(i), ha="center", va="center", fontsize=8)

    plt.title(f"Circle Packing (n={len(centers)}, sum={sum(radii):.6f})")
    plt.show()


if __name__ == "__main__":
    centers, radii, sum_radii = run_packing()
    print(f"Sum of radii: {sum_radii}")
    print(f"Number of circles: {len(centers)}")
# EVOLVE-BLOCK-END