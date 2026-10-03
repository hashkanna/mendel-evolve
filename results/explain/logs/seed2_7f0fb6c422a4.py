# EVOLVE-BLOCK-START
"""Circle packing for n=26 using SLSQP with explicit constraints and ultra-aggressive multi-strategy optimization"""
import numpy as np
from scipy.optimize import minimize


def construct_packing():
    """
    Construct an optimal arrangement of 26 circles in a unit square
    using scipy.optimize.minimize with SLSQP method and explicit constraints.

    Returns:
        Tuple of (centers, radii, sum_of_radii)
    """
    n = 26
    best_result = None
    best_sum = 0
    
    # Strategy 1: Optimized hexagonal layout with ultra-aggressive optimization
    centers1 = get_optimized_hexagonal_layout(n)
    radii1 = get_aggressive_initial_radii(centers1, n)
    result1 = optimize_with_explicit_constraints(centers1, radii1, n, max_iter=4000, ftol=1e-12)
    if result1 is not None and result1[2] > best_sum:
        best_result = result1
        best_sum = result1[2]
    
    # Strategy 2: Refined optimization with tighter tolerances
    if result1 is not None:
        centers2, radii2 = result1[0], result1[1]
        result2 = optimize_with_explicit_constraints(centers2, radii2, n, max_iter=3500, ftol=1e-13)
        if result2 is not None and result2[2] > best_sum:
            best_result = result2
            best_sum = result2[2]
    
    # Strategy 3: Corner-optimized layout
    centers3 = get_corner_optimized_layout(n)
    radii3 = get_aggressive_initial_radii(centers3, n)
    result3 = optimize_with_explicit_constraints(centers3, radii3, n, max_iter=3500, ftol=1e-12)
    if result3 is not None and result3[2] > best_sum:
        best_result = result3
        best_sum = result3[2]
    
    # Strategy 4: Adaptive grid with density-aware spacing
    centers4 = get_adaptive_grid_layout(n)
    radii4 = get_aggressive_initial_radii(centers4, n)
    result4 = optimize_with_explicit_constraints(centers4, radii4, n, max_iter=3500, ftol=1e-12)
    if result4 is not None and result4[2] > best_sum:
        best_result = result4
        best_sum = result4[2]
    
    # Strategy 5: Fine-tuned hexagonal variant with different spacing
    centers5 = get_fine_tuned_hexagonal_layout(n)
    radii5 = get_aggressive_initial_radii(centers5, n)
    result5 = optimize_with_explicit_constraints(centers5, radii5, n, max_iter=3500, ftol=1e-12)
    if result5 is not None and result5[2] > best_sum:
        best_result = result5
        best_sum = result5[2]
    
    # Final ultra-aggressive refinement with tightest tolerances
    if best_result is not None:
        centers_best, radii_best = best_result[0], best_result[1]
        result_final = optimize_with_explicit_constraints(
            centers_best, radii_best, n, max_iter=4500, ftol=1e-14
        )
        if result_final is not None and result_final[2] > best_sum:
            return result_final
        return best_result
    
    # Fallback
    return centers1, radii1, np.sum(radii1)


def optimize_with_explicit_constraints(initial_centers, initial_radii, n, max_iter=4000, ftol=1e-12):
    """
    Optimize circle packing using SLSQP with explicit constraint functions.
    This is mathematically superior to penalty methods for constrained optimization.
    """
    x0 = np.concatenate([initial_centers.flatten(), initial_radii])
    
    # Bounds: centers in [0.001, 0.999], radii in [0.0005, 0.5]
    bounds = [(0.001, 0.999) for _ in range(2*n)] + [(0.0005, 0.5) for _ in range(n)]
    
    def objective(x):
        """Minimize negative sum of radii (maximize sum)"""
        radii = x[2*n:]
        return -np.sum(radii)
    
    # Build constraint list with explicit functions
    constraints = []
    
    # Non-overlap constraints: dist(i,j) >= r_i + r_j for all i < j
    for i in range(n):
        for j in range(i + 1, n):
            def make_overlap_constraint(ii, jj):
                def constraint(x):
                    centers = x[:2*n].reshape((n, 2))
                    radii = x[2*n:]
                    dist = np.linalg.norm(centers[ii] - centers[jj])
                    return dist - radii[ii] - radii[jj]
                return constraint
            
            constraints.append({
                'type': 'ineq',
                'fun': make_overlap_constraint(i, j)
            })
    
    # Border constraints: for each circle i
    for i in range(n):
        def make_border_constraints(ii):
            def constraint_x_min(x):
                centers = x[:2*n].reshape((n, 2))
                radii = x[2*n:]
                return centers[ii, 0] - radii[ii]
            
            def constraint_y_min(x):
                centers = x[:2*n].reshape((n, 2))
                radii = x[2*n:]
                return centers[ii, 1] - radii[ii]
            
            def constraint_x_max(x):
                centers = x[:2*n].reshape((n, 2))
                radii = x[2*n:]
                return 1.0 - centers[ii, 0] - radii[ii]
            
            def constraint_y_max(x):
                centers = x[:2*n].reshape((n, 2))
                radii = x[2*n:]
                return 1.0 - centers[ii, 1] - radii[ii]
            
            return [constraint_x_min, constraint_y_min, constraint_x_max, constraint_y_max]
        
        border_constraints = make_border_constraints(i)
        for bc in border_constraints:
            constraints.append({
                'type': 'ineq',
                'fun': bc
            })
    
    # Optimize using SLSQP with explicit constraints
    result = minimize(
        objective,
        x0,
        method='SLSQP',
        bounds=bounds,
        constraints=constraints,
        options={
            'ftol': ftol,
            'maxiter': max_iter,
            'disp': False
        }
    )
    
    optimal_x = result.x
    centers = optimal_x[:2*n].reshape((n, 2))
    radii = np.maximum(optimal_x[2*n:], 0.0005)
    
    # Validate solution
    is_valid = validate_solution(centers, radii, n, tolerance=1e-6)
    if not is_valid:
        return None
    
    sum_radii = np.sum(radii)
    return centers, radii, sum_radii


def validate_solution(centers, radii, n, tolerance=1e-6):
    """Validate that solution satisfies all constraints"""
    # Check overlaps
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.linalg.norm(centers[i] - centers[j])
            if dist < radii[i] + radii[j] - tolerance:
                return False
    
    # Check bounds
    for i in range(n):
        x_i, y_i = centers[i]
        r_i = radii[i]
        if x_i - r_i < -tolerance or y_i - r_i < -tolerance:
            return False
        if x_i + r_i > 1 + tolerance or y_i + r_i > 1 + tolerance:
            return False
    
    return True


def get_optimized_hexagonal_layout(n):
    """
    Generate optimized hexagonal layout with better spacing for n=26.
    Uses golden ratio and careful row balancing.
    """
    centers = np.zeros((n, 2))
    
    hex_spacing = 0.195
    hex_offset = hex_spacing * np.sqrt(3) / 2
    y_center = 0.5
    
    # Carefully balanced hexagonal rows for 26 circles
    rows_config = [
        (y_center, [0.15, 0.35, 0.5, 0.65, 0.85]),                    # 5
        (y_center + hex_offset, [0.08, 0.25, 0.42, 0.58, 0.75, 0.92]),  # 6
        (y_center - hex_offset, [0.08, 0.25, 0.42, 0.58, 0.75, 0.92]),  # 6
        (y_center + 2*hex_offset, [0.15, 0.35, 0.5, 0.65, 0.85]),      # 5
        (y_center - 2*hex_offset, [0.15, 0.35, 0.5, 0.65, 0.85]),      # 5
    ]
    
    idx = 0
    for y, x_coords in rows_config:
        for x in x_coords:
            if idx < n:
                centers[idx] = [x, y]
                idx += 1
    
    # Adjust remaining circles if needed
    while idx < n:
        centers[idx] = [0.5, 0.5 + idx * 0.01]
        idx += 1
    
    return np.clip(centers, 0.001, 0.999)


def get_fine_tuned_hexagonal_layout(n):
    """
    Fine-tuned hexagonal layout with slightly different spacing.
    Explores alternative optimal configurations.
    """
    centers = np.zeros((n, 2))
    
    hex_spacing = 0.188
    hex_offset = hex_spacing * np.sqrt(3) / 2
    y_center = 0.5
    
    rows_config = [
        (y_center, [0.15, 0.35, 0.5, 0.65, 0.85]),
        (y_center + hex_offset, [0.08, 0.25, 0.42, 0.58, 0.75, 0.92]),
        (y_center - hex_offset, [0.08, 0.25, 0.42, 0.58, 0.75, 0.92]),
        (y_center + 2*hex_offset, [0.15, 0.35, 0.5, 0.65, 0.85]),
        (y_center - 2*hex_offset, [0.15, 0.35, 0.5, 0.65, 0.85]),
    ]
    
    idx = 0
    for y, x_coords in rows_config:
        for x in x_coords:
            if idx < n:
                centers[idx] = [x, y]
                idx += 1
    
    while idx < n:
        centers[idx] = [0.5, 0.5 + idx * 0.01]
        idx += 1
    
    return np.clip(centers, 0.001, 0.999)


def get_corner_optimized_layout(n):
    """
    Generate layout with strategic corner and edge optimization.
    Places larger circles at corners, medium at edges, smaller in interior.
    """
    centers = np.zeros((n, 2))
    idx = 0
    
    # Corner circles (4)
    corner_offset = 0.12
    corners = [
        (corner_offset, corner_offset),
        (1 - corner_offset, corner_offset),
        (corner_offset, 1 - corner_offset),
        (1 - corner_offset, 1 - corner_offset)
    ]
    for corner in corners:
        centers[idx] = corner
        idx += 1
    
    # Edge circles (14 circles, distributed along edges)
    edge_step = 1.0 / 4
    for i in range(1, 4):
        # Top edge
        centers[idx] = [i * edge_step, 1 - corner_offset]
        idx += 1
        # Bottom edge
        centers[idx] = [i * edge_step, corner_offset]
        idx += 1
    
    for i in range(1, 4):
        # Left edge
        centers[idx] = [corner_offset, i * edge_step]
        idx += 1
        # Right edge
        centers[idx] = [1 - corner_offset, i * edge_step]
        idx += 1
    
    # Interior circles (8)
    interior_positions = [
        (0.25, 0.25), (0.75, 0.25),
        (0.25, 0.75), (0.75, 0.75),
        (0.5, 0.35), (0.5, 0.65),
        (0.35, 0.5), (0.65, 0.5),
    ]
    for pos in interior_positions:
        if idx < n:
            centers[idx] = pos
            idx += 1
    
    return np.clip(centers, 0.001, 0.999)


def get_adaptive_grid_layout(n):
    """
    Generate adaptive grid layout with density-aware spacing.
    Denser packing in center, sparser at edges.
    """
    centers = np.zeros((n, 2))
    
    idx = 0
    
    # Create roughly 5x6 grid with adaptive spacing
    for row in range(6):
        for col in range(5):
            if idx < n:
                # Adaptive spacing: tighter in center, looser at edges
                t_x = (col + 0.5) / 5.0
                t_y = (row + 0.5) / 6.0
                
                # Apply sigmoid-like spacing to concentrate in center
                x = 0.1 + 0.8 * t_x
                y = 0.1 + 0.8 * t_y
                
                # Add density-aware jitter
                jx = x + np.random.uniform(-0.015, 0.015)
                jy = y + np.random.uniform(-0.015, 0.015)
                
                centers[idx] = [np.clip(jx, 0.001, 0.999), np.clip(jy, 0.001, 0.999)]
                idx += 1
    
    return centers


def get_aggressive_initial_radii(centers, n):
    """
    Compute aggressive initial radii using advanced heuristics.
    Larger circles at corners/edges, smaller in interior.
    Uses Voronoi-like distance analysis with multi-phase expansion.
    """
    radii = np.ones(n) * 0.001
    
    # Phase 1: Border-based initialization
    for i in range(n):
        x, y = centers[i]
        edge_dist = min(x, y, 1 - x, 1 - y)
        
        # Position-based multiplier
        corner_dist = min(
            np.sqrt(x**2 + y**2),
            np.sqrt((1-x)**2 + y**2),
            np.sqrt(x**2 + (1-y)**2),
            np.sqrt((1-x)**2 + (1-y)**2)
        )
        
        if corner_dist < 0.22:
            # Corner region: allow larger circles
            radii[i] = min(0.22, edge_dist * 0.95)
        elif edge_dist < 0.12:
            # Near edge: constrain more
            radii[i] = min(0.10, edge_dist * 0.85)
        else:
            # Interior: medium radius
            radii[i] = min(0.18, edge_dist * 0.90)
    
    # Phase 2: Nearest neighbor constraint iteration with aggressive expansion
    for iteration in range(8):
        for i in range(n):
            min_dist = float('inf')
            for j in range(n):
                if i != j:
                    dist = np.linalg.norm(centers[i] - centers[j])
                    min_dist = min(min_dist, dist)
            
            if min_dist < float('inf'):
                max_r = max(0.0005, (min_dist - 0.003) / 2.0)
                radii[i] = min(radii[i], max_r)
    
    # Phase 3: Aggressive expansion within constraints
    for i in range(n):
        x, y = centers[i]
        edge_dist = min(x, y, 1 - x, 1 - y)
        radii[i] = min(radii[i], edge_dist * 0.92)
    
    return np.clip(radii, 0.0005, 0.5)


# EVOLVE-BLOCK-END


def run_packing():
    """Run the circle packing constructor for n=26"""
    centers, radii, sum_radii = construct_packing()
    return centers, radii, sum_radii


def visualize(centers, radii):
    """Visualize the circle packing"""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.2)
    
    # Draw unit square
    ax.plot([0, 1, 1, 0, 0], [0, 0, 1, 1, 0], 'k-', linewidth=2)

    for i, (center, radius) in enumerate(zip(centers, radii)):
        circle = Circle(center, radius, alpha=0.6, edgecolor='black', linewidth=1)
        ax.add_patch(circle)
        ax.text(center[0], center[1], str(i), ha="center", va="center", fontsize=8)

    ax.set_title(f"Circle Packing (n={len(centers)}, sum={np.sum(radii):.6f})")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    centers, radii, sum_radii = run_packing()
    print(f"Sum of radii: {sum_radii:.6f}")
    print(f"Target: 2.635")
    print(f"Gap to target: {2.635 - sum_radii:.6f}")
    print(f"Validity: {validate_solution(centers, radii, 26)}")