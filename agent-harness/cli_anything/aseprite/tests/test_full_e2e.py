"""End-to-end tests: real CLI invocations producing real files."""

import json
import os
import struct
import subprocess
import sys
import zlib

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
TMP = os.path.join(REPO, "tests", "tmp_e2e")
os.makedirs(TMP, exist_ok=True)

CLI = shutil_which = None
for p in ("cli-anything-aseprite",
          os.path.join(os.path.dirname(sys.executable), "cli-anything-aseprite")):
    if os.path.isfile(p) or p.startswith("cli-anything"):
        CLI = p
        break


def run(*args, file=None, json_out=True):
    cmd = ["cli-anything-aseprite"]
    if file:
        cmd += ["--file", file]
    if json_out:
        cmd += ["--json"]
    cmd += list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=TMP, timeout=60)
    assert proc.returncode == 0, f"cmd failed: {cmd}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    if json_out:
        return json.loads(proc.stdout)
    return proc.stdout


@pytest.fixture(scope="module", autouse=True)
def clean_tmp():
    for f in os.listdir(TMP):
        os.remove(os.path.join(TMP, f))
    yield


def test_e2e_project_new_autosave():
    f = os.path.join(TMP, "w1.pxa")
    r = run("project", "new", "w1", "--width", "16", "--height", "16", "--palette", "pico8",
            file=f)
    assert r["name"] == "w1"
    assert os.path.isfile(f)
    doc = json.load(open(f))
    assert doc["width"] == 16 and doc["height"] == 16


def test_e2e_draw_and_export_png():
    f = os.path.join(TMP, "w2.pxa")
    run("project", "new", "w2", "--width", "16", "--height", "16", file=f)
    run("pixel", "set", "7", "7", "#ff0000", file=f)
    run("pixel", "line", "2", "14", "13", "14", "#29adff", file=f)
    run("pixel", "rect", "4", "3", "8", "8", "#ffec27", "--fill", file=f)
    out = os.path.join(TMP, "w2.png")
    r = run("export", "png", out, "--scale", "4", file=f)
    assert r["format"] == "png" and r["width"] == 64
    with open(out, "rb") as fh:
        assert fh.read(8)[:4] == b"\x89PNG"


def test_e2e_png_nearest_neighbor():
    """Upscaled preview must be crisp (nearest), not blurred."""
    from PIL import Image
    f = os.path.join(TMP, "w3.pxa")
    run("project", "new", "w3", "--width", "8", "--height", "8", file=f)
    run("pixel", "set", "0", "0", "#ff0000", file=f)
    out = os.path.join(TMP, "w3.png")
    run("export", "png", out, "--scale", "8", file=f)
    img = Image.open(out).convert("RGBA")
    assert img.getpixel((0, 0)) == (255, 0, 0, 255)
    assert img.getpixel((7, 7)) == (255, 0, 0, 255)   # block stays red
    assert img.getpixel((8, 0)) == (0, 0, 0, 0)       # next block transparent


def test_e2e_gif_animation():
    f = os.path.join(TMP, "w4.pxa")
    run("project", "new", "w4", "--width", "16", "--height", "16", file=f)
    run("pixel", "set", "1", "1", "#ff0000", file=f)
    run("frame", "add", "--duration", "120", file=f)
    run("pixel", "set", "14", "1", "#00ff00", file=f)  # second frame differs
    out = os.path.join(TMP, "w4.gif")
    r = run("export", "gif", out, file=f)
    assert r["format"] == "gif" and r["frames"] == 2
    with open(out, "rb") as fh:
        assert fh.read(3) == b"GIF"


def test_e2e_aseprite_binary_structure():
    f = os.path.join(TMP, "w5.pxa")
    run("project", "new", "w5", "--width", "8", "--height", "8", file=f)
    run("pixel", "rect", "0", "0", "8", "8", "#ff0000", "--fill", file=f)
    run("pixel", "set", "1", "1", "#00ff00", file=f)
    out = os.path.join(TMP, "w5.aseprite")
    r = run("export", "aseprite", out, file=f)
    assert r["format"] == "aseprite"
    d = open(out, "rb").read()
    file_size, magic, frames, w, h, depth = struct.unpack("<IHHHHH", d[:14])
    assert file_size == len(d)
    assert magic == 0xA5E0 and frames == 1 and w == 8 and h == 8 and depth == 32
    frame_size, frame_magic, old_chunks, duration, chunks = struct.unpack(
        "<IHHH2xI", d[128:144]
    )
    assert frame_size == len(d) - 128
    assert frame_magic == 0xF1FA and old_chunks == chunks and duration == 100
    pos, end = 144, 128 + frame_size
    seen = set()
    while pos < end:
        csize, ctype = struct.unpack("<IH", d[pos:pos + 6])
        assert csize >= 6
        seen.add(ctype)
        pos += csize
    assert pos == end
    assert 0x2004 in seen and 0x2019 in seen and 0x2005 in seen


def test_e2e_aseprite_cel_data():
    f = os.path.join(TMP, "w6.pxa")
    run("project", "new", "w6", "--width", "4", "--height", "4", file=f)
    run("pixel", "set", "0", "0", "#ff0000", file=f)
    run("pixel", "set", "3", "3", "#0000ff", file=f)
    out = os.path.join(TMP, "w6.aseprite")
    run("export", "aseprite", out, file=f)
    d = open(out, "rb").read()
    frame_size = struct.unpack("<I", d[128:132])[0]
    pos, end = 144, 128 + frame_size
    found = False
    while pos < end:
        csize, ctype = struct.unpack("<IH", d[pos:pos + 6])
        if ctype == 0x2005:
            body = d[pos + 6:pos + csize]
            layer, x, y, opacity, typ, z_index, w, h = struct.unpack(
                "<HhhBHh5xHH", body[:20]
            )
            assert (layer, x, y, opacity, typ, z_index) == (0, 0, 0, 255, 2, 0)
            raw = zlib.decompress(body[20:])
            assert len(raw) == w * h * 4
            assert raw[0:4] == bytes([255, 0, 0, 255])           # (0,0) red
            assert raw[15 * 4:15 * 4 + 4] == bytes([0, 0, 255, 255])  # (3,3) blue
            found = True
        pos += csize
    assert found


def test_e2e_aseprite_animation_and_tags():
    """Animation metadata must survive native ASE export."""
    f = os.path.join(TMP, "w11.pxa")
    run("project", "new", "w11", "--width", "4", "--height", "4", file=f)
    run("pixel", "set", "0", "0", "#ff0000", file=f)
    run("layer", "add", "fx", file=f)
    run("pixel", "set", "1", "1", "#00ff00", file=f)
    run("frame", "add", "--duration", "120", file=f)
    run("pixel", "set", "2", "2", "#0000ff", file=f)
    run("frame", "tag", "add", "cycle", "0", "1", "--color", "#ffec27", file=f)
    out = os.path.join(TMP, "w11.aseprite")
    run("export", "aseprite", out, file=f)

    d = open(out, "rb").read()
    file_size, magic, frames = struct.unpack("<IHH", d[:8])
    assert file_size == len(d) and magic == 0xA5E0 and frames == 2
    durations = []
    frame_chunks = []
    pos = 128
    for frame_index in range(frames):
        frame_start = pos
        frame_size, frame_magic, old_chunks, duration, chunks = struct.unpack(
            "<IHHH2xI", d[pos:pos + 16]
        )
        assert frame_magic == 0xF1FA and old_chunks == chunks
        durations.append(duration)
        frame_end = frame_start + frame_size
        pos += 16
        types = []
        for _ in range(chunks):
            csize, ctype = struct.unpack("<IH", d[pos:pos + 6])
            assert csize >= 6
            types.append(ctype)
            if frame_index == 0 and ctype == 0x2018:
                body = d[pos + 6:pos + csize]
                assert struct.unpack("<H", body[:2])[0] == 1
                name_len = struct.unpack("<H", body[27:29])[0]
                assert body[29:29 + name_len] == b"cycle"
            pos += csize
        assert pos == frame_end
        frame_chunks.append(types)
    assert pos == len(d)
    assert durations == [100, 120]
    assert 0x2004 in frame_chunks[0] and 0x2019 in frame_chunks[0]
    assert 0x2018 in frame_chunks[0]
    assert all(types.count(0x2005) == 2 for types in frame_chunks)


def test_e2e_undo_redo():
    f = os.path.join(TMP, "w7.pxa")
    run("project", "new", "w7", "--width", "8", "--height", "8", file=f)
    run("pixel", "set", "2", "2", "#ff0000", file=f)
    u = run("undo", file=f)
    assert u["undone"] is True
    info = run("project", "info", file=f)
    assert info["pixels"] == 0
    r = run("redo", file=f)
    assert r["redone"] is True
    info = run("project", "info", file=f)
    assert info["pixels"] == 1


def test_e2e_flood_fill():
    f = os.path.join(TMP, "w8.pxa")
    run("project", "new", "w8", "--width", "8", "--height", "8", file=f)
    run("pixel", "rect", "0", "0", "8", "8", "#ffffff", "--fill", file=f)
    run("pixel", "rect", "2", "2", "4", "4", "#000000", "--fill", file=f)
    r = run("pixel", "flood", "0", "0", "#00ff00", file=f)
    assert r["painted"] == 48
    info = run("project", "info", file=f)
    assert info["pixels"] == 64


def test_e2e_terminal_frame():
    f = os.path.join(TMP, "w9.pxa")
    run("project", "new", "w9", "--width", "8", "--height", "8", file=f)
    run("pixel", "rect", "1", "1", "4", "4", "#ff0000", "--fill", file=f)
    out = run("terminal", "--no-color", file=f, json_out=False)
    assert "##" in out or "#" in out
    assert "w9" in out  # status line carries project name
    # colored variant also works
    out2 = run("terminal", file=f, json_out=False)
    assert "\x1b[" in out2


def test_e2e_layer_merge():
    f = os.path.join(TMP, "w10.pxa")
    run("project", "new", "w10", "--width", "8", "--height", "8", file=f)
    run("layer", "add", "fg", file=f)
    run("pixel", "set", "0", "0", "#ff0000", file=f)
    run("layer", "set", "0", file=f)
    run("pixel", "set", "7", "7", "#0000ff", file=f)
    r = run("layer", "merge", file=f)
    assert len(r["remaining"]) == 1
    info = run("project", "info", file=f)
    assert info["pixels"] == 2
