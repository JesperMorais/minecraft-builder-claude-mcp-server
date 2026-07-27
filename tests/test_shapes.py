"""Tests for the geometry primitives."""

import pytest

from minecraft_builder import shapes


def test_cuboid_counts_and_bounds():
    coords = set(shapes.cuboid((0, 0, 0), (2, 1, 3)))
    assert len(coords) == 3 * 2 * 4
    assert (0, 0, 0) in coords and (2, 1, 3) in coords


def test_cuboid_accepts_reversed_corners():
    a = set(shapes.cuboid((2, 1, 3), (0, 0, 0)))
    b = set(shapes.cuboid((0, 0, 0), (2, 1, 3)))
    assert a == b


def test_hollow_box_is_a_shell():
    solid = set(shapes.cuboid((0, 0, 0), (4, 4, 4)))
    shell = set(shapes.hollow_box((0, 0, 0), (4, 4, 4)))
    assert shell < solid
    # The dead centre must be empty in a full shell.
    assert (2, 2, 2) not in shell
    # Every face voxel is present.
    assert (0, 2, 2) in shell and (4, 2, 2) in shell


def test_hollow_box_toggle_faces():
    no_ceiling = set(shapes.hollow_box((0, 0, 0), (4, 4, 4), ceiling=False))
    assert not any(y == 4 and 0 < x < 4 and 0 < z < 4 for (x, y, z) in no_ceiling)
    # Floor still present.
    assert (2, 0, 2) in no_ceiling


def test_sphere_radius_membership():
    coords = set(shapes.sphere((0, 0, 0), 3))
    for (x, y, z) in coords:
        assert x * x + y * y + z * z <= 9
    assert (3, 0, 0) in coords
    assert (0, 0, 0) in coords


def test_hollow_sphere_has_empty_core():
    solid = set(shapes.sphere((0, 0, 0), 4))
    hollow = set(shapes.sphere((0, 0, 0), 4, hollow=True))
    assert hollow < solid
    assert (0, 0, 0) not in hollow


def test_cylinder_axes_and_height():
    cyl = set(shapes.cylinder((0, 0, 0), 2, 5, axis="y"))
    ys = {y for (_, y, _) in cyl}
    assert ys == {0, 1, 2, 3, 4}
    # Along x the height runs on the x axis instead.
    cyl_x = set(shapes.cylinder((0, 0, 0), 2, 5, axis="x"))
    xs = {x for (x, _, _) in cyl_x}
    assert xs == {0, 1, 2, 3, 4}


def test_line_endpoints_and_continuity():
    coords = list(shapes.line((0, 0, 0), (5, 3, 2)))
    assert coords[0] == (0, 0, 0)
    assert coords[-1] == (5, 3, 2)
    # Consecutive voxels never jump more than one step on any axis.
    for (a, b) in zip(coords, coords[1:], strict=False):
        assert all(abs(a[i] - b[i]) <= 1 for i in range(3))


def test_line_single_point():
    assert list(shapes.line((1, 1, 1), (1, 1, 1))) == [(1, 1, 1)]


def test_pyramid_narrows_to_apex():
    p = set(shapes.pyramid((0, 0, 0), 3))
    base_layer = {(x, z) for (x, y, z) in p if y == 0}
    apex_layer = {(x, z) for (x, y, z) in p if y == 3}
    assert len(base_layer) == 7 * 7
    assert apex_layer == {(0, 0)}


def test_dome_is_upper_hemisphere():
    d = set(shapes.dome((0, 0, 0), 5))
    assert all(y >= 0 for (_, y, _) in d)      # never below the base
    assert (0, 5, 0) in d and (5, 0, 0) in d   # apex and base rim
    # It is exactly the top half of the equivalent sphere.
    sphere_top = {c for c in shapes.sphere((0, 0, 0), 5) if c[1] >= 0}
    assert d == sphere_top


def test_hollow_dome_is_open_shell():
    solid = set(shapes.dome((0, 0, 0), 6))
    hollow = set(shapes.dome((0, 0, 0), 6, hollow=True))
    assert hollow < solid
    assert (0, 0, 0) not in hollow   # base is open (no floor disk)
    assert (0, 6, 0) in hollow       # apex is on the shell
    assert (6, 0, 0) in hollow       # base rim is on the shell


def test_cone_narrows_over_height():
    c = set(shapes.cone((0, 0, 0), 5, 6))
    assert {y for (_, y, _) in c} == {0, 1, 2, 3, 4, 5}
    base = {(x, z) for (x, y, z) in c if y == 0}
    apex = {(x, z) for (x, y, z) in c if y == 5}
    assert len(base) > len(apex)
    assert apex == {(0, 0)}


def test_cone_axis_x():
    c = set(shapes.cone((0, 0, 0), 4, 5, axis="x"))
    assert {x for (x, _, _) in c} == {0, 1, 2, 3, 4}


def test_ellipsoid_respects_each_semi_axis():
    e = set(shapes.ellipsoid((0, 0, 0), 6, 3, 4))
    assert (6, 0, 0) in e and (0, 3, 0) in e and (0, 0, 4) in e
    assert (0, 4, 0) not in e   # beyond ry
    assert (7, 0, 0) not in e   # beyond rx
    for (x, y, z) in e:
        assert (x / 6) ** 2 + (y / 3) ** 2 + (z / 4) ** 2 <= 1.0 + 1e-9


def test_hollow_ellipsoid_has_empty_core():
    solid = set(shapes.ellipsoid((0, 0, 0), 5, 5, 5))
    hollow = set(shapes.ellipsoid((0, 0, 0), 5, 5, 5, hollow=True))
    assert hollow < solid
    assert (0, 0, 0) not in hollow


def test_torus_has_empty_hole_and_expected_reach():
    t = set(shapes.torus((0, 0, 0), 8, 2))
    assert (0, 0, 0) not in t          # the hole
    assert (8, 0, 0) in t              # tube centre on the major ring
    assert all(y in range(-2, 3) for (_, y, _) in t)  # tube spans ±minor on axis y


def test_torus_axis_changes_symmetry_plane():
    ty = set(shapes.torus((0, 0, 0), 6, 2, axis="y"))
    tx = set(shapes.torus((0, 0, 0), 6, 2, axis="x"))
    assert ty != tx
    # With axis=x the tube spans ±minor along x instead of y.
    assert all(x in range(-2, 3) for (x, _, _) in tx)


def test_new_shapes_reject_bad_input():
    with pytest.raises(ValueError):
        list(shapes.cone((0, 0, 0), 3, 3, axis="q"))
    with pytest.raises(ValueError):
        list(shapes.torus((0, 0, 0), 5, 2, axis="q"))
    with pytest.raises(ValueError):
        list(shapes.ellipsoid((0, 0, 0), 0, 3, 3))
    with pytest.raises(ValueError):
        list(shapes.cone((0, 0, 0), 3, 0))  # height must be >= 1
