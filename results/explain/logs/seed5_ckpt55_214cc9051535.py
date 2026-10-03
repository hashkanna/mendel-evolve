# EVOLVE-BLOCK-START
"""Enhanced scipy-optimized circle packing with multi-start and adaptive constraints"""
import numpy as np
from scipy.optimize import minimize, differential_evolution


def construct_packing():
    """
    Construct an optimized arrangement of 26 circles in a unit square
    using scipy.optimize with multi-start strategy and adaptive refinement.

    Returns:
        Tuple of (centers, radii, sum_of_radii)
    """
    n = 26
    
    # Try multiple initialization strategies and keep the best
    best_sum = 0
    best_centers = None
    best_radii = None
    
    # Strategy 1: Hexagonal with local optimization
    centers_hex = get_initial_hexagonal_centers(n)
    radii_hex = get_initial_radii(centers_hex)
    sum1 = optimize_packing(centers_hex, radii_hex, n, method='local')
    if sum1[2] > best_sum:
        best_sum = sum1[2]
        best_centers, best_radii = sum1[0], sum1[1]
    
    # Strategy 2: Grid-based with adaptive spacing
    centers_grid = get_grid_centers(n)
    radii_grid = get_initial_radii(centers_grid)
    sum2 = optimize_packing(centers_grid, radii_grid, n, method='local')
    if sum2[2] > best_sum:
        best_sum = sum2[2]
        best_centers, best_radii = sum2[0], sum2[1]
    
    # Strategy 3: Random seed with global optimization
    centers_rand = get_random_centers(n)
    radii_rand = get_initial_radii(centers_rand)
    sum3 = optimize_packing(centers_rand, radii_rand, n, method='global')
    if sum3[2] > best_sum:
        best_sum = sum3[2]
        best_centers, best_radii = sum3[0], sum3[1]
    
    # Final refinement with tighter constraints
    final_result = optimize_packing(best_centers, best_radii, n, method='refine')
    
    return final_result[0], final_result[1], final_result[2]


def get_initial_hexagonal_centers(n):
    """Generate initial hexagonal arrangement with strategic positioning"""
    centers = np.zeros((n, 2))
    
    # 5-layer hexagonal pattern (4-5-6-6-5=26)
    y_positions = [0.108, 0.268, 0.428, 0.588, 0.748]
    layer_sizes = [4, 5, 6, 6, 5]
    x_ranges = [(0.18, 0.82), (0.12, 0.88), (0.08, 0.92), (0.08, 0.92), (0.12, 0.88)]
    
    idx = 0
    for layer, size in enumerate(layer_sizes):
        y = y_positions[layer]
        x_min, x_max = x_ranges[layer]
        x_pos = np.linspace(x_min, x_max, size)
        for x in x_pos:
            centers[idx] = [x, y]
            idx += 1
    
    return np.clip(centers, 0.01, 0.99)


def get_grid_centers(n):
    """Generate grid-based arrangement"""
    side = int(np.ceil(np.sqrt(n)))
    centers = np.zeros((n, 2))
    spacing = 1.0 / (side + 1)
    
    idx = 0
    for i in range(side):
        for j in range(side):
            if idx < n:
                centers[idx] = [spacing * (i + 1), spacing * (j + 1)]
                idx += 1
    
    return np.clip(centers, 0.01, 0.99)


def get_random_centers(n):
    """Generate random centers with minimum separation"""
    np.random.seed(42)
    centers = np.random.uniform(0.05, 0.95, (n, 2))
    
    # Enforce minimum separation through relaxation
    min_dist = 0.08
    for _ in range(10):
        for i in range(n):
            for j in range(i + 1, n):
                dist = np.linalg.norm(centers[i] - centers[j])
                if dist < min_dist:
                    direction = (centers[i] - centers[j]) / (dist + 1e-8)
                    centers[i] += direction * (min_dist - dist) * 0.5
                    centers[j] -= direction * (min_dist - dist) * 0.5
                    centers[i] = np.clip(centers[i], 0.01, 0.99)
                    centers[j] = np.clip(centers[j], 0.01, 0.99)
    
    return centers


def get_initial_radii(centers):
    """Initialize radii based on distance to boundaries and neighbors"""
    n = centers.shape[0]
    radii = np.zeros(n)
    
    for i in range(n):
        x, y = centers[i]
        radii[i] = min(x, y, 1 - x, 1 - y) * 0.95
    
    # Reduce based on neighbor distances
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.linalg.norm(centers[i] - centers[j])
            if dist > 0:
                max_sum = dist * 0.98
                radii[i] = min(radii[i], max_sum / 2)
                radii[j] = min(radii[j], max_sum / 2)
    
    return np.maximum(radii, 0.01)


def optimize_packing(centers_init, radii_init, n, method='local'):
    """Optimize packing using specified method"""
    x0 = np.concatenate([centers_init.flatten(), radii_init])
    
    if method == 'global':
        # Use differential evolution for global search
        bounds = get_optimization_bounds(n)
        result = differential_evolution(
            lambda x: objective_function(x, n),
            bounds,
            maxiter=500,
            popsize=15,
            seed=42,
            atol=1e-9,
            tol=1e-9
        )
    else:
        # Use SLSQP for local optimization
        options = {'maxiter': 2000, 'ftol': 1e-10}
        if method == 'refine':
            options['maxiter'] = 3000
            options['ftol'] = 1e-12
        
        result = minimize(
            objective_function,
            x0,
            args=(n,),
            method='SLSQP',
            bounds=get_optimization_bounds(n),
            constraints=get_adaptive_constraints(n, centers_init, radii_init, method),
            options=options
        )
    
    # Extract optimized solution
    x_opt = result.x
    centers = x_opt[:2*n].reshape((n, 2))
    radii = x_opt[2*n:3*n]
    
    # Ensure validity
    centers = np.clip(centers, 0.001, 0.999)
    for i in range(n):
        x, y = centers[i]
        radii[i] = min(radii[i], min(x, y, 1 - x, 1 - y))
    radii = np.maximum(radii, 0.0001)
    
    return centers, radii, np.sum(radii)


def objective_function(x, n):
    """Objective: minimize negative sum of radii"""
    radii = x[2*n:3*n]
    return -np.sum(radii)


def get_optimization_bounds(n):
    """Define bounds for optimization variables"""
    bounds = []
    for i in range(n):
        bounds.append((0.001, 0.999))  # x
        bounds.append((0.001, 0.999))  # y
    for i in range(n):
        bounds.append((0.0001, 0.5))   # radius
    return bounds


def get_adaptive_constraints(n, centers_init, radii_init, method):
    """Define adaptive constraints based on method"""
    constraints = []
    
    # Boundary constraints
    for i in range(n):
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i: x[2*i] - x[2*n + i]})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i: x[2*i + 1] - x[2*n + i]})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i: 1 - x[2*i] - x[2*n + i]})
        constraints.append({'type': 'ineq', 'fun': lambda x, i=i: 1 - x[2*i + 1] - x[2*n + i]})
    
    # Non-overlap constraints with adaptive margins
    margin = 1e-6 if method == 'refine' else 1e-5
    for i in range(n):
        for j in range(i + 1, n):
            constraints.append({
                'type': 'ineq',
                'fun': lambda x, i=i, j=j, m=margin: (
                    np.sqrt((x[2*i] - x[2*j])**2 + (x[2*i+1] - x[2*j+1])**2) - 
                    x[2*n + i] - x[2*n + j] - m
                )
            })
    
    return constraints


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