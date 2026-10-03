"""The decomposed program: initial_program.py and evolved_program.py as one parameterised constructor.

    construct(cfg, n, seed) -> (centers, radii)

Stages, each behind its own switch (off = initial program, on = evolved program):
    row_layout             ring layout                -> five-row layout
    neighbor_radii         pairwise proportional radii -> fraction of nearest-neighbour / wall distance
    slsqp_optimizer        (nothing)                  -> SLSQP on all centres and radii
    refine_shrink          (nothing)                  -> refinement phases A and B (resolve overlaps, walls)
    refine_expand          (nothing)                  -> refinement phase C (grow radii into free space)
"""
import numpy as np


def construct(cfg, n, seed):
    # Starting centres
    if cfg["row_layout"]:
        centers_init = initialize_centers_golden(cfg, n)
    else:
        centers_init = initialize_centers_rings(cfg, n)

    # Starting radii
    if cfg["neighbor_radii"]:
        radii_init = initialize_radii_fast(cfg, centers_init)
    else:
        radii_init = compute_max_radii(centers_init)

    centers, radii = centers_init, radii_init

    if cfg["slsqp_optimizer"]:
        from scipy.optimize import minimize

        # Flatten for optimization
        x0 = np.concatenate([centers_init.flatten(), radii_init])

        # SLSQP optimization with efficient constraints
        result = minimize(
            objective_function,
            x0,
            args=(n,),
            method='SLSQP',
            constraints=build_constraints_vectorized(cfg, n),
            options={
                'ftol': cfg["slsqp_ftol"],
                'maxiter': int(cfg["slsqp_maxiter"]),
                'disp': False
            },
            bounds=build_bounds(n)
        )

        x_opt = result.x
        centers = x_opt[:2*n].reshape((n, 2))
        radii = x_opt[2*n:2*n+n]

    if cfg["refine_shrink"] or cfg["refine_expand"]:
        centers, radii = fast_refinement(cfg, centers, radii, n)

    return centers, radii


# ---------------------------------------------------------------- initial program

def initialize_centers_rings(cfg, n):
    """Layout of the initial program: one centre circle, a ring of 8, a ring of 16 (written for 26)."""
    centers = np.zeros((n, 2))

    # First, place a large circle in the center
    if n > 0:
        centers[0] = [0.5, 0.5]

    # Place 8 circles around it in a ring
    r_in = cfg["ring_inner_radius"]
    for i in range(8):
        angle = 2 * np.pi * i / 8
        if i + 1 < n:
            centers[i + 1] = [0.5 + r_in * np.cos(angle), 0.5 + r_in * np.sin(angle)]

    # Place 16 more circles in an outer ring
    r_out = cfg["ring_outer_radius"]
    for i in range(16):
        angle = 2 * np.pi * i / 16
        if i + 9 < n:
            centers[i + 9] = [0.5 + r_out * np.cos(angle), 0.5 + r_out * np.sin(angle)]

    # Clip to ensure everything is inside the unit square
    centers = np.clip(centers, cfg["clip_margin"], 1 - cfg["clip_margin"])
    return centers


def compute_max_radii(centers):
    """
    Compute the maximum possible radii for each circle position
    such that they don't overlap and stay within the unit square.
    """
    n = centers.shape[0]
    radii = np.ones(n)

    # First, limit by distance to square borders
    for i in range(n):
        x, y = centers[i]
        # Distance to borders
        radii[i] = min(x, y, 1 - x, 1 - y)

    # Then, limit by distance to other circles
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.sqrt(np.sum((centers[i] - centers[j]) ** 2))

            # If current radii would cause overlap
            if radii[i] + radii[j] > dist:
                # Scale both radii proportionally
                scale = dist / (radii[i] + radii[j])
                radii[i] *= scale
                radii[j] *= scale

    return radii


# ---------------------------------------------------------------- evolved program

def initialize_centers_golden(cfg, n):
    """Layout of the evolved program: four rows of 5 and one row of 6 (written for 26)."""
    centers = np.zeros((n, 2))

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

    return np.clip(centers, cfg["clip_margin"], 1 - cfg["clip_margin"])


def initialize_radii_fast(cfg, centers):
    """Radius = a fixed fraction of the distance to the nearest wall / nearest neighbour."""
    n = len(centers)
    radii = np.zeros(n)
    frac = cfg["init_radius_fraction"]

    for i in range(n):
        x, y = centers[i]
        border_dist = min(x, y, 1 - x, 1 - y)

        # Compute all distances from circle i
        dists = np.linalg.norm(centers - centers[i], axis=1)
        dists[i] = np.inf  # Exclude self

        # Use minimum neighbor distance
        min_neighbor = np.min(dists) if np.any(np.isfinite(dists)) else 0.5

        # Conservative initialization
        radii[i] = min(border_dist * frac, min_neighbor * frac)

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


def build_constraints_vectorized(cfg, n):
    """Build constraints for SLSQP"""
    constraints = []
    overlap_margin = cfg["slsqp_overlap_margin"]
    wall_margin = cfg["slsqp_wall_margin"]

    # Constraint 1: No circle overlaps
    def no_overlap_constraint(x):
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:2*n+n]

        violations = []
        for i in range(n):
            for j in range(i + 1, n):
                dist = np.linalg.norm(centers[i] - centers[j])
                violations.append(dist - radii[i] - radii[j] - overlap_margin)

        return np.array(violations) if violations else np.array([1.0])

    constraints.append({
        'type': 'ineq',
        'fun': no_overlap_constraint
    })

    # Constraint 2: Circles within bounds
    def within_bounds_constraint(x):
        centers = x[:2*n].reshape((n, 2))
        radii = x[2*n:2*n+n]

        violations = []
        for i in range(n):
            x_pos, y_pos = centers[i]
            r = radii[i]
            violations.extend([
                x_pos - r - wall_margin,
                y_pos - r - wall_margin,
                1 - x_pos - r - wall_margin,
                1 - y_pos - r - wall_margin
            ])

        return np.array(violations)

    constraints.append({
        'type': 'ineq',
        'fun': within_bounds_constraint
    })

    return constraints


def fast_refinement(cfg, centers, radii, n):
    """
    Post-processing of the evolved program. refine_shrink runs phases A and B, refine_expand phase C;
    the centre clip, the loop and the final radius floor are shared by both.
    """
    do_shrink = cfg["refine_shrink"]
    do_expand = cfg["refine_expand"]
    pair_shrink = cfg["refine_pair_shrink"]
    wall_shrink = cfg["refine_wall_shrink"]
    expand_factor = cfg["refine_expand_factor"]

    centers = np.clip(centers, 0.001, 0.999)

    # The original derives this from the remaining time: min(6, max(1, int(remaining / 5))) = 6
    max_iterations = int(cfg["refine_iterations"])

    for iteration in range(max_iterations):
        if do_shrink:
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
                            target_sum = dist * pair_shrink
                            radii[i] = target_sum * ratio_i
                            radii[j] = target_sum * ratio_j

            # Phase B: Enforce boundary constraints
            for i in range(n):
                x, y = centers[i]
                max_radius = min(x, y, 1 - x, 1 - y) * wall_shrink
                radii[i] = min(radii[i], max_radius)

        if do_expand:
            # Phase C: Expansion with safety margin
            for i in range(n):
                x, y = centers[i]
                max_possible = min(x, y, 1 - x, 1 - y)

                for j in range(n):
                    if i != j:
                        dist = np.linalg.norm(centers[i] - centers[j])
                        max_possible = min(max_possible, dist - radii[j] - 1e-9)

                safety_factor = 0.9996 if iteration < 3 else 0.9997
                radii[i] = max(radii[i], max_possible * safety_factor * expand_factor)

    return centers, np.maximum(radii, 1e-5)
