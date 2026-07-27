"""Tests for the ASCII preview and stats."""

from minecraft_builder import preview
from minecraft_builder.schema import MinecraftStructure


def test_is_air_variants():
    assert preview.is_air("air")
    assert preview.is_air("minecraft:air")
    assert preview.is_air("cave_air")
    assert not preview.is_air("stone")
    assert not preview.is_air("minecraft:oak_log[axis=y]")


def test_structure_stats_counts_and_fill():
    s = MinecraftStructure(name="s", operations=[
        {"op": "cuboid", "start": [0, 0, 0], "end": [2, 0, 2], "block": "stone"},   # 9 solid
        {"op": "block", "pos": [1, 0, 1], "block": "air"},                          # carve 1
    ])
    stats = preview.structure_stats(s.expand())
    assert (stats["width"], stats["height"], stats["length"]) == (3, 1, 3)
    assert stats["placed"] == 9
    assert stats["solid"] == 8
    assert stats["air"] == 1
    assert stats["counts"]["stone"] == 8
    assert 0.0 < stats["fill_ratio"] <= 1.0


def test_structure_stats_empty():
    assert preview.structure_stats({})["empty"] is True


def test_legend_orders_by_frequency():
    counts = {"stone": 100, "glass": 5, "air": 3}
    legend = preview.build_legend(counts)
    assert legend["stone"] == "A"   # most common first
    assert legend["glass"] == "B"
    assert "air" not in legend      # air is never in the legend


def test_render_preview_shows_layers_and_carved_air():
    s = MinecraftStructure(name="hut", operations=[
        {"op": "hollow_box", "start": [0, 0, 0], "end": [4, 3, 4], "block": "stone", "ceiling": False},
        {"op": "cuboid", "start": [2, 1, 0], "end": [2, 2, 0], "block": "air"},  # doorway
    ])
    text = preview.render_preview(s)
    assert "Preview: hut" in text
    assert "Legend:" in text
    assert "y=0:" in text and "y=3:" in text
    # The doorway carves the front wall — a '.' must appear inside a wall row.
    assert "." in text


def test_render_preview_large_footprint_is_stats_only():
    s = MinecraftStructure(name="plaza", operations=[
        {"op": "cuboid", "start": [0, 0, 0], "end": [80, 0, 80], "block": "stone"},
    ])
    text = preview.render_preview(s)
    assert "too large to draw" in text
    assert "y=0:" not in text  # no grid drawn


def test_render_preview_tall_structure_samples_layers():
    s = MinecraftStructure(name="pillar", operations=[
        {"op": "cuboid", "start": [0, 0, 0], "end": [0, 60, 0], "block": "stone"},
    ])
    text = preview.render_preview(s)
    assert "sampled layers" in text
    # Never more than the cap.
    assert text.count("y=") <= preview.MAX_LAYERS + 1


def test_render_preview_empty():
    text = preview.render_preview(MinecraftStructure(name="void"))
    assert "empty" in text
