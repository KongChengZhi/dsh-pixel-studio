"""Unit tests for cli-anything-aseprite core modules."""

import json
import os
import sys
import struct
import zlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli_anything.aseprite.core import model, canvas, palette, layers, animation, session
from cli_anything.aseprite.core.session import Session
from cli_anything.aseprite.utils.io import load_json, locked_save_json


def test_locked_save_json_create_and_overwrite(tmp_path):
    path = tmp_path / "project.pxa"

    locked_save_json(str(path), {"version": 1})
    assert load_json(str(path)) == {"version": 1}

    locked_save_json(str(path), {"version": 2})
    assert load_json(str(path)) == {"version": 2}
    assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# model.py
# ---------------------------------------------------------------------------

class TestModel:
    def test_new_document_defaults(self):
        doc = model.new_document(16, 16, "test")
        assert doc["width"] == 16 and doc["height"] == 16
        assert len(doc["layers"]) == 1
        assert len(doc["frames"]) == 1
        assert len(doc["palette"]) == 16
        assert doc["current_layer"] == 0
        assert doc["current_frame"] == 0

    def test_new_document_validation(self):
        with pytest.raises(ValueError):
            model.new_document(0, 16)
        with pytest.raises(ValueError):
            model.new_document(16, 2000)

    def test_pixel_roundtrip(self):
        doc = model.new_document(8, 8)
        assert model.set_pixel(doc, 3, 4, "#ff0000")
        assert model.pixel_at(doc, 3, 4) == "#ff0000ff"
        assert not model.set_pixel(doc, 3, 4, "#ff0000")  # no change
        assert model.set_pixel(doc, 3, 4, None)  # erase
        assert model.pixel_at(doc, 3, 4) is None

    def test_pixel_out_of_bounds(self):
        doc = model.new_document(8, 8)
        with pytest.raises(ValueError):
            model.set_pixel(doc, 8, 0, "#fff")

    def test_normalize_color(self):
        assert model.normalize_color("#f00") == "#ff0000ff"
        assert model.normalize_color("#ff0000") == "#ff0000ff"
        assert model.normalize_color("#ff000080") == "#ff000080"
        assert model.normalize_color("red") == "#ff0000ff"
        assert model.normalize_color("WHITE") == "#ffffffff"
        with pytest.raises(ValueError):
            model.normalize_color("#12")
        with pytest.raises(ValueError):
            model.normalize_color("notacolor")

    def test_hex_rgba_roundtrip(self):
        assert model.hex_to_rgba("#1d2b53ff") == (0x1D, 0x2B, 0x53, 0xFF)
        assert model.rgba_to_hex(0x1D, 0x2B, 0x53, 0xFF) == "#1d2b53ff"

    def test_snapshot_restore(self):
        doc = model.new_document(8, 8)
        model.set_pixel(doc, 1, 1, "#fff")
        snap = model.snapshot(doc)
        model.set_pixel(doc, 2, 2, "#000")
        model.restore(doc, snap)
        assert model.pixel_at(doc, 2, 2) is None
        assert model.pixel_at(doc, 1, 1) == "#ffffffff"

    def test_add_layer_frame(self):
        doc = model.new_document(8, 8)
        layer = model.add_layer(doc, "shade")
        assert layer["id"] == 1
        assert doc["current_layer"] == 1
        frame = model.add_frame(doc, 200)
        assert frame["id"] == 1
        assert doc["current_frame"] == 1
        assert frame["duration"] == 200

    def test_render_canvas_opacity(self):
        doc = model.new_document(4, 4)
        model.set_pixel(doc, 0, 0, "#ff0000")
        grid = model.render_canvas(doc)
        assert grid[0][0] == (255, 0, 0, 255)
        # 50% opacity layer
        layers.set_layer_property(doc, 0, "opacity", 128)
        grid = model.render_canvas(doc)
        assert grid[0][0][3] == 128

    def test_modified_timestamp(self):
        doc = model.new_document(4, 4)
        t0 = doc["modified"]
        model.set_pixel(doc, 0, 0, "#fff")
        assert doc["modified"] >= t0


# ---------------------------------------------------------------------------
# canvas.py
# ---------------------------------------------------------------------------

class TestCanvas:
    def test_stroke_points_line(self):
        pts = canvas._stroke_points(0, 0, 4, 0)
        assert pts == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
        pts = canvas._stroke_points(0, 0, 0, 3)
        assert len(pts) == 4

    def test_draw_pixel(self):
        doc = model.new_document(8, 8)
        r = canvas.draw_pixel(doc, 2, 2, "#fff")
        assert r["changed"] and r["pixels"] == 1
        assert model.pixel_at(doc, 2, 2) == "#ffffffff"

    def test_draw_line(self):
        doc = model.new_document(8, 8)
        r = canvas.draw_line(doc, 1, 1, 6, 1, "#fff")
        assert r["painted"] == 6
        assert model.pixel_at(doc, 6, 1) == "#ffffffff"

    def test_draw_rect_outline_vs_fill(self):
        doc = model.new_document(8, 8)
        r1 = canvas.draw_rect(doc, 1, 1, 4, 4, "#fff", fill=False)
        assert r1["painted"] == 12  # perimeter of 4x4
        doc2 = model.new_document(8, 8)
        r2 = canvas.draw_rect(doc2, 1, 1, 4, 4, "#fff", fill=True)
        assert r2["painted"] == 16

    def test_draw_ellipse(self):
        doc = model.new_document(16, 16)
        r = canvas.draw_ellipse(doc, 8, 8, 4, 3, "#fff", fill=False)
        assert r["painted"] > 0
        # center of filled ellipse present
        doc2 = model.new_document(16, 16)
        canvas.draw_ellipse(doc2, 8, 8, 4, 3, "#fff", fill=True)
        assert model.pixel_at(doc2, 8, 8) == "#ffffffff"

    def test_flood_fill_region(self):
        doc = model.new_document(8, 8)
        canvas.draw_rect(doc, 0, 0, 8, 8, "#fff", fill=True)
        canvas.draw_rect(doc, 2, 2, 4, 4, "#000", fill=True)
        r = canvas.flood_fill(doc, 0, 0, "#00ff00")
        assert r["painted"] == 48  # 64 - 16 inner
        assert model.pixel_at(doc, 0, 0) == "#00ff00ff"
        assert model.pixel_at(doc, 3, 3) == "#000000ff"

    def test_flood_fill_already(self):
        doc = model.new_document(8, 8)
        r = canvas.flood_fill(doc, 0, 0, "#ffffff")
        assert r["painted"] == 64
        r2 = canvas.flood_fill(doc, 0, 0, "#ffffff")
        assert r2["already"]

    def test_flood_fill_tolerance(self):
        doc = model.new_document(4, 4)
        model.set_pixel(doc, 0, 0, "#ff0000")
        model.set_pixel(doc, 1, 0, "#fe0000")
        r = canvas.flood_fill(doc, 0, 0, "#0000ff", tolerance=5)
        assert r["painted"] == 2

    def test_erase(self):
        doc = model.new_document(8, 8)
        canvas.draw_rect(doc, 0, 0, 8, 8, "#fff", fill=True)
        r = canvas.erase(doc, 4, 4, radius=1)
        assert r["erased"] == 9
        assert model.pixel_at(doc, 4, 4) is None

    def test_get_region(self):
        doc = model.new_document(8, 8)
        model.set_pixel(doc, 2, 3, "#ff0000")
        reg = canvas.get_region(doc, 0, 0, 8, 8)
        assert len(reg["rows"]) == 8 and len(reg["rows"][0]) == 8
        assert reg["rows"][3][2] == "#ff0000ff"

    def test_invert_region(self):
        doc = model.new_document(8, 8)
        model.set_pixel(doc, 1, 1, "#ff0000")
        r = canvas.invert_region(doc, 0, 0, 8, 8)
        assert r["inverted"] == 1
        assert model.pixel_at(doc, 1, 1) == "#00ffffff"

    def test_transform_flip(self):
        doc = model.new_document(8, 8)
        canvas.draw_pixel(doc, 1, 2, "#fff")
        r = canvas.transform(doc, "flip-h")
        assert r["pixels"] == 1
        assert model.pixel_at(doc, 6, 2) == "#ffffffff"
        assert model.pixel_at(doc, 1, 2) is None

    def test_transform_rotate90(self):
        doc = model.new_document(8, 8)
        canvas.draw_pixel(doc, 2, 1, "#fff")
        canvas.transform(doc, "rotate-90")
        assert model.pixel_at(doc, 6, 2) == "#ffffffff"

    def test_transform_invalid(self):
        doc = model.new_document(8, 8)
        with pytest.raises(ValueError):
            canvas.transform(doc, "skew")


# ---------------------------------------------------------------------------
# palette.py
# ---------------------------------------------------------------------------

class TestPalette:
    def test_apply_palette(self):
        doc = model.new_document(8, 8)
        r = palette.apply_palette(doc, "pico8")
        assert r["colors"] == 16
        assert doc["palette"][0]["color"] == "#000000ff"

    def test_add_color_duplicate(self):
        doc = model.new_document(8, 8)
        palette.add_color(doc, "gold", "#ffd700")
        assert len(doc["palette"]) == 17
        with pytest.raises(ValueError):
            palette.add_color(doc, "gold", "#ffffff")

    def test_nearest_color(self):
        doc = model.new_document(8, 8)
        palette.apply_palette(doc, "pico8")
        r = palette.nearest_color(doc, "#ffec27")
        assert r["nearest"] == "yellow"

    def test_quantize(self):
        doc = model.new_document(8, 8)
        palette.apply_palette(doc, "pico8")
        canvas.draw_rect(doc, 0, 0, 8, 8, "#ffec28", fill=True)  # off-by-one yellow
        r = palette.quantize_canvas(doc)
        assert r["quantized"] == 64
        assert model.pixel_at(doc, 0, 0) == "#ffec27ff"


# ---------------------------------------------------------------------------
# layers.py
# ---------------------------------------------------------------------------

class TestLayers:
    def test_add_remove_set(self):
        doc = model.new_document(8, 8)
        layers.add_layer(doc, "shade")
        assert doc["current_layer"] == 1
        r = layers.set_layer(doc, 0)
        assert doc["current_layer"] == 0
        r = layers.remove_layer(doc, 1)
        assert len(doc["layers"]) == 1

    def test_cannot_remove_last(self):
        doc = model.new_document(8, 8)
        with pytest.raises(ValueError):
            layers.remove_layer(doc, 0)

    def test_duplicate_copies_cels(self):
        doc = model.new_document(8, 8)
        model.set_pixel(doc, 1, 1, "#fff")
        r = layers.duplicate_layer(doc)
        assert r["id"] == 1
        assert model.pixel_at(doc, 1, 1, layer_id=1) == "#ffffffff"


# ---------------------------------------------------------------------------
# animation.py
# ---------------------------------------------------------------------------

class TestAnimation:
    def test_add_frame_copies(self):
        doc = model.new_document(8, 8)
        model.set_pixel(doc, 1, 1, "#fff")
        f = animation.add_frame(doc, 100, copy=True)
        assert f["id"] == 1
        assert model.pixel_at(doc, 1, 1) == "#ffffffff"  # copied cel

    def test_add_frame_blank(self):
        doc = model.new_document(8, 8)
        model.set_pixel(doc, 1, 1, "#fff")
        animation.add_frame(doc, 100, copy=False)
        assert model.pixel_at(doc, 1, 1) is None

    def test_remove_last_rejected(self):
        doc = model.new_document(8, 8)
        with pytest.raises(ValueError):
            animation.remove_frame(doc)

    def test_duration_clamp(self):
        doc = model.new_document(8, 8)
        animation.set_duration(doc, 0, 0)
        assert doc["frames"][0]["duration"] == 1


# ---------------------------------------------------------------------------
# session.py
# ---------------------------------------------------------------------------

class TestSession:
    def test_undo_redo(self):
        s = Session()
        doc = model.new_document(8, 8)
        s.set_document(doc)
        s.push_undo()
        model.set_pixel(doc, 1, 1, "#fff")
        assert model.pixel_at(doc, 1, 1) is not None
        u = s.undo()
        assert model.pixel_at(doc, 1, 1) is None
        r = s.redo()
        assert model.pixel_at(doc, 1, 1) == "#ffffffff"

    def test_undo_empty(self):
        s = Session()
        doc = model.new_document(8, 8)
        s.set_document(doc)
        with pytest.raises(ValueError):
            s.undo()

    def test_status_counts(self):
        s = Session()
        doc = model.new_document(8, 8)
        s.set_document(doc)
        st = s.status()
        assert st["open"] and st["size"] == "8x8" and st["frames"] == 1

    def test_undo_cap(self):
        s = Session()
        doc = model.new_document(8, 8)
        s.set_document(doc)
        for _ in range(session.MAX_HISTORY + 20):
            s.push_undo()
        assert len(s.undo_stack) == session.MAX_HISTORY


# ---------------------------------------------------------------------------
# region (selection) operations + rgb16 + presets
# ---------------------------------------------------------------------------

class TestRegionOps:
    def test_region_fill(self):
        doc = model.new_document(8, 8)
        r = canvas.region_fill(doc, 1, 1, 3, 3, "#ff0000")
        assert r["painted"] == 9
        assert model.pixel_at(doc, 2, 2) == "#ff0000ff"
        assert model.pixel_at(doc, 4, 4) is None

    def test_region_clear(self):
        doc = model.new_document(8, 8)
        canvas.region_fill(doc, 0, 0, 8, 8, "#ffffff")
        r = canvas.region_clear(doc, 2, 2, 4, 4)
        assert r["cleared"] == 16
        assert model.pixel_at(doc, 2, 2) is None
        assert model.pixel_at(doc, 1, 1) == "#ffffffff"

    def test_region_copy_paste(self):
        doc = model.new_document(8, 8)
        canvas.region_fill(doc, 1, 1, 2, 2, "#00ff00")
        r = canvas.region_copy(doc, 1, 1, 2, 2)
        assert r["copied"] == 4
        r = canvas.region_paste(doc, 4, 4)
        assert r["pasted"] == 4
        assert model.pixel_at(doc, 4, 4) == "#00ff00ff"
        # paste with transparent holes erases target
        canvas.region_copy(doc, 0, 0, 4, 4)  # region has transparent cells
        r = canvas.region_paste(doc, 0, 0)
        assert model.pixel_at(doc, 1, 1) == "#00ff00ff"

    def test_region_paste_empty_clipboard(self):
        doc = model.new_document(8, 8)
        import cli_anything.aseprite.core.canvas as C
        C._clipboard["rows"] = []
        with pytest.raises(ValueError):
            canvas.region_paste(doc, 0, 0)

    def test_region_move(self):
        doc = model.new_document(8, 8)
        canvas.region_fill(doc, 1, 1, 3, 3, "#ff0000")
        r = canvas.region_move(doc, 1, 1, 3, 3, 3, 3)
        assert r["moved"] == 9
        assert model.pixel_at(doc, 1, 1) is None
        assert model.pixel_at(doc, 4, 4) == "#ff0000ff"


class TestRgb16:
    def test_rgb16_normalize(self):
        assert model.normalize_color("rgb16:15,0,0") == "#ff0000ff"
        assert model.normalize_color("rgb16:0,15,0") == "#00ff00ff"
        assert model.normalize_color("rgb16:0,0,15") == "#0000ffff"
        assert model.normalize_color("rgb16:8,8,8") == "#888888ff"
        assert model.normalize_color("rgb16:7,7,7") == "#777777ff"

    def test_rgb16_invalid(self):
        with pytest.raises(ValueError):
            model.normalize_color("rgb16:16,0,0")
        with pytest.raises(ValueError):
            model.normalize_color("rgb16:1,2")

    def test_rgb16_draw(self):
        doc = model.new_document(8, 8)
        canvas.draw_pixel(doc, 0, 0, "rgb16:5,10,15")
        assert model.pixel_at(doc, 0, 0) == "#55aaffff"


class TestPresets:
    def test_preset_sizes(self):
        assert model.CANVAS_PRESETS["icon"] == (16, 16)
        assert model.CANVAS_PRESETS["sprite"] == (32, 32)
        assert model.CANVAS_PRESETS["max"] == (1024, 1024)

    def test_1024_canvas(self):
        doc = model.new_document(1024, 1024, "big")
        assert doc["width"] == 1024 and doc["height"] == 1024
        model.set_pixel(doc, 1023, 1023, "#fff")
        assert model.pixel_at(doc, 1023, 1023) == "#ffffffff"


# ---------------------------------------------------------------------------
# Aseprite-parity features: symmetry / tiled / gradient / stroke / resize /
# tags / reference layers / png sequence / onion skin
# ---------------------------------------------------------------------------

class TestSymmetryTiled:
    def teardown_method(self):
        canvas.set_symmetry(None)
        canvas.set_tiled(False)

    def test_symmetry_h(self):
        doc = model.new_document(16, 16)
        canvas.set_symmetry('h')
        r = canvas.draw_pixel(doc, 2, 3, "#ff0000")
        assert r["pixels"] == 2
        assert model.pixel_at(doc, 2, 3) == "#ff0000ff"
        assert model.pixel_at(doc, 13, 3) == "#ff0000ff"  # mirrored

    def test_symmetry_both(self):
        doc = model.new_document(16, 16)
        canvas.set_symmetry('both')
        r = canvas.draw_pixel(doc, 2, 3, "#ff0000")
        assert r["pixels"] == 4
        assert model.pixel_at(doc, 13, 12) == "#ff0000ff"

    def test_tiled_wrap(self):
        doc = model.new_document(8, 8)
        canvas.set_tiled(True)
        r = canvas.draw_pixel(doc, 8, 0, "#ff0000")  # x wraps to 0
        assert model.pixel_at(doc, 0, 0) == "#ff0000ff"

    def test_modes_persistence(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "m.pxa")
            canvas.set_symmetry('v')
            canvas.set_tiled(True)
            canvas.save_modes(p)
            canvas.set_symmetry(None)
            canvas.set_tiled(False)
            canvas.load_modes(p)
            assert canvas.get_symmetry() == 'v'
            assert canvas.get_tiled() is True


class TestGradient:
    def test_line_gradient(self):
        doc = model.new_document(16, 16)
        r = canvas.gradient(doc, 0, 8, 15, 8, "#ff0000", "#0000ff")
        assert r["painted"] == 16
        assert model.pixel_at(doc, 0, 8) == "#ff0000ff"
        assert model.pixel_at(doc, 15, 8) == "#0000ffff"
        mid = model.pixel_at(doc, 7, 8)
        assert mid is not None and mid != "#ff0000ff"  # interpolated

    def test_gradient_rgb16(self):
        doc = model.new_document(8, 8)
        canvas.gradient(doc, 0, 0, 7, 0, "rgb16:15,0,0", "rgb16:0,15,0")
        assert model.pixel_at(doc, 7, 0) == "#00ff00ff"

    def test_vertical_gradient(self):
        doc = model.new_document(8, 8)
        r = canvas.gradient(doc, 0, 0, 7, 7, "#ffffff", "#000000", direction="vertical")
        assert r["painted"] == 64


class TestRegionStroke:
    def test_stroke(self):
        doc = model.new_document(8, 8)
        r = canvas.region_stroke(doc, 1, 1, 4, 4, "#ff0000")
        assert r["stroked"] == 12
        assert model.pixel_at(doc, 1, 1) == "#ff0000ff"
        assert model.pixel_at(doc, 2, 2) is None  # interior untouched


class TestResize:
    def test_resize_center(self):
        doc = model.new_document(8, 8)
        canvas.draw_pixel(doc, 4, 4, "#ff0000")
        r = canvas.resize_canvas(doc, 12, 12, anchor="c")
        assert doc["width"] == 12
        assert model.pixel_at(doc, 6, 6) == "#ff0000ff"  # shifted by +2

    def test_resize_se(self):
        doc = model.new_document(8, 8)
        canvas.draw_pixel(doc, 7, 7, "#ff0000")
        canvas.resize_canvas(doc, 10, 10, anchor="se")
        assert model.pixel_at(doc, 9, 9) == "#ff0000ff"

    def test_rescale_nearest(self):
        doc = model.new_document(4, 4)
        canvas.draw_pixel(doc, 0, 0, "#ff0000")
        canvas.rescale(doc, 8, 8)
        assert model.pixel_at(doc, 0, 0) == "#ff0000ff"
        assert model.pixel_at(doc, 1, 1) == "#ff0000ff"  # nearest block


class TestTagsReference:
    def test_tag_crud(self):
        doc = model.new_document(8, 8)
        model.add_frame(doc, 100)
        model.add_frame(doc, 100)
        model.add_tag(doc, "run", 0, 2)
        tags = model.list_tags(doc)["tags"]
        assert tags[0]["name"] == "run" and tags[0]["from"] == 0
        model.remove_tag(doc, "run")
        assert model.list_tags(doc)["count"] == 0

    def test_tag_invalid_range(self):
        doc = model.new_document(8, 8)
        with pytest.raises(ValueError):
            model.add_tag(doc, "bad", 0, 5)  # only 1 frame

    def test_reference_layer_skipped_in_render(self):
        doc = model.new_document(8, 8)
        model.set_pixel(doc, 1, 1, "#ff0000")
        model.set_layer_reference(doc, 0, True)
        grid = model.render_canvas(doc)
        assert grid[1][1] == (0, 0, 0, 0)  # reference layer not rendered
