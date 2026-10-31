"""Pure helpers for the multipoint scan-coordinate CSV format.

The CSV has ``region``, ``x (mm)`` and ``y (mm)`` columns plus an optional ``z (mm)``
column. When z is present, FOVs are loaded as ``(x, y, z)`` tuples, which the
acquisition worker honors per FOV. These helpers only build data; widgets publish the
result via ``LoadScanCoordinatesCommand`` (they never mutate backend state directly).
"""

from typing import Dict, Mapping, Sequence, Tuple

import pandas as pd

import _def

REQUIRED_COLUMNS = ("region", "x (mm)", "y (mm)")
Z_COLUMN = "z (mm)"

RegionFovCoordinates = Dict[str, Tuple[Tuple[float, ...], ...]]
RegionCenters = Dict[str, Tuple[float, float]]


def regions_from_coordinates_dataframe(df: pd.DataFrame) -> Tuple[RegionFovCoordinates, RegionCenters, bool]:
    """Parse a coordinates dataframe into region FOV tuples and region centers.

    If a ``z (mm)`` column is present and every cell parses as a number, FOVs are
    ``(x, y, z)``; otherwise ``(x, y)``. An incomplete/unparseable z column is dropped
    (all regions stay tuple-length homogeneous, NaN never reaches the stage).

    Everything is parsed before returning, so a bad cell raises before any caller
    publishes a load command (existing regions are never half-replaced).

    Returns:
        (region_fov_coordinates, region_centers, z_dropped)

    Raises:
        ValueError: on missing required columns, unparseable x/y, or z outside
            SOFTWARE_POS_LIMIT.
    """
    if not all(col in df.columns for col in REQUIRED_COLUMNS):
        raise ValueError("CSV file must contain 'region', 'x (mm)', and 'y (mm)' columns")

    has_z = Z_COLUMN in df.columns
    z_dropped = False
    z_values = None
    if has_z:
        # Coerce up front: an object-dtype column (numeric strings, stray text) would
        # make the range comparison raise TypeError.
        z_values = pd.to_numeric(df[Z_COLUMN], errors="coerce")
        if z_values.isna().any():
            has_z = False
            z_dropped = True

    if has_z:
        z_min = _def.SOFTWARE_POS_LIMIT.Z_NEGATIVE
        z_max = _def.SOFTWARE_POS_LIMIT.Z_POSITIVE
        out_of_range = z_values[(z_values < z_min) | (z_values > z_max)]
        if not out_of_range.empty:
            raise ValueError(
                f"z (mm) values outside software limits [{z_min}, {z_max}] mm: "
                f"{sorted(out_of_range.unique().tolist())}"
            )

    region_fov_coordinates: RegionFovCoordinates = {}
    region_centers: RegionCenters = {}
    for region_id in df["region"].unique():
        region_points = df[df["region"] == region_id]
        xs = [float(x) for x in region_points["x (mm)"]]
        ys = [float(y) for y in region_points["y (mm)"]]
        if has_z:
            zs = [float(z) for z in z_values.loc[region_points.index]]
            coords = tuple(zip(xs, ys, zs))
        else:
            coords = tuple(zip(xs, ys))
        region_fov_coordinates[str(region_id)] = coords
        region_centers[str(region_id)] = (sum(xs) / len(xs), sum(ys) / len(ys))

    return region_fov_coordinates, region_centers, z_dropped


def xeryon_objective_relative_z_mm(objective_name: str) -> float:
    """Relative stage-Z frame of an objective under the Xeryon 2-position switcher.

    The changer parks the stage XERYON_OBJECTIVE_SWITCHER_POS_2_OFFSET_MM lower while a
    position-2 objective is in use. 0 for position-1 objectives, unknown names, and
    machines without the switcher.
    """
    if not _def.USE_XERYON:
        return 0.0
    if _def.xeryon_objective_position(objective_name) == 2:
        return -float(_def.XERYON_OBJECTIVE_SWITCHER_POS_2_OFFSET_MM)
    return 0.0


def parfocal_adjusted_z_mm(current_objective: str, target_objective: str, z_mm: float) -> float:
    """Shift a stage z from the current objective's frame to the target objective's."""
    return z_mm + (xeryon_objective_relative_z_mm(target_objective) - xeryon_objective_relative_z_mm(current_objective))


def coordinate_rows_for_save(
    region_fov_coordinates: Mapping[str, Sequence[Sequence[float]]], z_default_mm: float
) -> pd.DataFrame:
    """Flatten region FOV coordinates into a coordinates dataframe with a z column.

    FOVs that already carry z (3-tuples) keep it; 2-tuple FOVs get ``z_default_mm``.
    """
    rows = []
    for region_id, fov_coords in region_fov_coordinates.items():
        for coord in fov_coords:
            z = float(coord[2]) if len(coord) >= 3 else float(z_default_mm)
            rows.append([region_id, float(coord[0]), float(coord[1]), z])
    return pd.DataFrame(rows, columns=["region", "x (mm)", "y (mm)", Z_COLUMN])
