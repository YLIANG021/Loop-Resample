"""Public core API for Loop Resample."""

from .attributes import (
    apply_path_edge_attributes,
    apply_path_point_attributes,
    apply_region_edge_attributes,
    region_outer_parameters,
)
from .planner import (
    build_ordered_strip_plan,
    frozen_ladder,
    outer_boundary_order,
)
from .rebuild import (
    apply_ordered_strip_plan,
    cleanup_detached_edges,
    detach_adjacent_strips,
    rebuild_detached_path,
    rebuild_ngon_cap,
    rebuild_triangle_fan,
    region_rungs,
)
from .seams import (
    apply_region_seams,
    paint_path_seam_jogs,
    region_seam_rungs,
    region_seam_waypoints,
)
from .surface import apply_region_faces


__all__ = (
    "apply_ordered_strip_plan",
    "apply_path_edge_attributes",
    "apply_path_point_attributes",
    "apply_region_edge_attributes",
    "apply_region_faces",
    "apply_region_seams",
    "build_ordered_strip_plan",
    "cleanup_detached_edges",
    "detach_adjacent_strips",
    "frozen_ladder",
    "outer_boundary_order",
    "paint_path_seam_jogs",
    "rebuild_detached_path",
    "rebuild_ngon_cap",
    "rebuild_triangle_fan",
    "region_outer_parameters",
    "region_rungs",
    "region_seam_rungs",
    "region_seam_waypoints",
)
