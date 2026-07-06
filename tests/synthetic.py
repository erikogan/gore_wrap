"""Synthetic point clouds with analytically known gore dimensions.

Used by the geometry tests so assertions can compare against closed-form
answers rather than golden files.
"""

import numpy as np


def cylinder_with_hemisphere(radius=40.0, height=100.0, center=(0.0, 0.0),
                             n=40000, seed=0):
    """Surface points of a vertical cylinder capped by a hemisphere.

    The cylinder spans z in [0, height] at constant `radius`; the hemisphere
    of the same radius sits on top, apex at z = height + radius. Returned as
    an (n, 3) array. Meridian arc length from base to apex is
    height + pi*radius/2; circumference at any cylinder height is 2*pi*radius.
    """
    rng = np.random.default_rng(seed)
    cx, cy = center
    # Split points between the wall and the cap in proportion to their areas.
    wall_area = 2 * np.pi * radius * height
    cap_area = 2 * np.pi * radius * radius
    n_wall = int(round(n * wall_area / (wall_area + cap_area)))
    n_cap = n - n_wall

    theta = rng.uniform(0, 2 * np.pi, n_wall)
    z = rng.uniform(0, height, n_wall)
    wall = np.column_stack([cx + radius * np.cos(theta),
                            cy + radius * np.sin(theta), z])

    # Uniform over the hemisphere: polar angle from apex, area weight sin(phi).
    phi = np.arccos(rng.uniform(0, 1, n_cap))  # 0..pi/2 from the pole
    theta_c = rng.uniform(0, 2 * np.pi, n_cap)
    r_ring = radius * np.sin(phi)
    cap = np.column_stack([cx + r_ring * np.cos(theta_c),
                           cy + r_ring * np.sin(theta_c),
                           height + radius * np.cos(phi)])
    return np.vstack([wall, cap])


def tapered_cone(r_bottom=40.0, r_top=30.0, height=100.0, center=(0.0, 0.0),
                 n=40000, seed=1):
    """Surface points of a truncated cone, wider at the bottom.

    Radius varies linearly from `r_bottom` at z=0 to `r_top` at z=height.
    """
    rng = np.random.default_rng(seed)
    cx, cy = center
    z = rng.uniform(0, height, n)
    r = r_bottom + (r_top - r_bottom) * (z / height)
    theta = rng.uniform(0, 2 * np.pi, n)
    return np.column_stack([cx + r * np.cos(theta),
                            cy + r * np.sin(theta), z])
