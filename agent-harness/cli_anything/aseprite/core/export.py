"""Aseprite CLI - Export pipeline.

Exports a document to PNG (still), GIF (animation), sprite-sheet PNG+JSON,
and native .aseprite binary files (writer implemented from the public
ASE file format spec). If a real `aseprite` binary is available, it is
used for advanced conversion (see utils/aseprite_backend.py).
"""

import io
import json
import os
import struct
import zlib
from typing import Any, Dict, List, Optional

from .model import get_frame, hex_to_rgba, render_canvas

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from ..utils.aseprite_backend import find_aseprite, run_batch
    HAS_BACKEND = True
except Exception:
    HAS_BACKEND = False


def _grid_to_pil(doc, frame_id=None):
    if not HAS_PIL:
        raise RuntimeError("Pillow is required for raster export (pip install pillow)")
    grid = render_canvas(doc, frame_id)
    w, h = doc["width"], doc["height"]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = grid[y][x]
    return img


def export_png(doc, path: str, scale: int = 1, frame_id=None) -> dict:
    scale = max(1, int(scale))
    img = _grid_to_pil(doc, frame_id)
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    img.save(path, "PNG")
    return {"path": os.path.abspath(path), "width": img.width, "height": img.height,
            "scale": scale, "format": "png"}


def export_gif(doc, path: str, scale: int = 1, loop: int = 0) -> dict:
    if not HAS_PIL:
        raise RuntimeError("Pillow is required for GIF export (pip install pillow)")
    scale = max(1, int(scale))
    frames = []
    durations = []
    for frame in doc["frames"]:
        img = _grid_to_pil(doc, frame["id"])
        if scale > 1:
            img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
        frames.append(img.convert("RGBA"))
        durations.append(max(10, frame["duration"]))
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=durations, loop=loop, disposal=2)
    return {"path": os.path.abspath(path), "frames": len(frames),
            "scale": scale, "format": "gif"}


def export_spritesheet(doc, path: str, data_path: Optional[str] = None,
                       direction: str = "horizontal", scale: int = 1) -> dict:
    """Export all frames into one sprite sheet + JSON metadata (aseprite-style)."""
    scale = max(1, int(scale))
    frames = doc["frames"]
    fw, fh = doc["width"] * scale, doc["height"] * scale
    if direction == "horizontal":
        sheet = Image.new("RGBA", (fw * len(frames), fh), (0, 0, 0, 0))
    elif direction == "vertical":
        sheet = Image.new("RGBA", (fw, fh * len(frames)), (0, 0, 0, 0))
    else:
        raise ValueError("direction must be horizontal or vertical")
    meta = {"frames": {}, "meta": {
        "app": "cli-anything-aseprite", "version": "1.0.0",
        "image": os.path.basename(path),
        "size": {"w": sheet.width, "h": sheet.height}, "scale": str(scale),
        "frameTags": [{"name": "all", "from": 0, "to": len(frames) - 1}],
    }}
    for i, frame in enumerate(frames):
        img = _grid_to_pil(doc, frame["id"])
        if scale > 1:
            img = img.resize((fw, fh), Image.NEAREST)
        if direction == "horizontal":
            x, y = i * fw, 0
        else:
            x, y = 0, i * fh
        sheet.paste(img, (x, y), img)
        meta["frames"][f"frame{i}"] = {
            "frame": {"x": x, "y": y, "w": fw, "h": fh},
            "duration": frame["duration"],
        }
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    sheet.save(path, "PNG")
    if data_path:
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    return {"path": os.path.abspath(path), "data_path": os.path.abspath(data_path) if data_path else None,
            "frames": len(frames), "sheet_w": sheet.width, "sheet_h": sheet.height}


# ---------------------------------------------------------------------------
# .aseprite binary writer (ASE file format spec)
# ---------------------------------------------------------------------------

def _pack_string(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<H", len(b)) + b


def _pack_chunk(chunk_type: int, body: bytes) -> bytes:
    """Pack an ASE chunk; its size includes the 6-byte chunk header."""
    return struct.pack("<IH", len(body) + 6, chunk_type) + body


def _pack_palette_chunk(doc) -> bytes:
    pal = doc["palette"]
    body = struct.pack("<III", len(pal), 0, max(0, len(pal) - 1))
    body += b"\x00" * 8
    for c in pal:
        flags = 1 if c.get("name") else 0
        r, g, b, a = hex_to_rgba(c["color"])
        body += struct.pack("<HBBBB", flags, r, g, b, a)
        if flags:
            body += _pack_string(c["name"])
    return body


def _pack_layer_chunk(layer: dict) -> bytes:
    flags = 2  # editable
    if layer.get("visible", True):
        flags |= 1
    if layer.get("reference", False):
        flags |= 64
    opacity = max(0, min(255, int(layer.get("opacity", 255))))
    body = struct.pack("<HHHHHHB3x", flags, 0, 0, 0, 0, 0, opacity)
    return body + _pack_string(layer["name"])


def _pack_cel_chunk(doc, frame_id: int, layer: dict) -> Optional[bytes]:
    frame = get_frame(doc, frame_id)
    cel = frame["cels"].get(str(layer["id"]), {})
    if not cel:
        return None
    w, h = doc["width"], doc["height"]
    # ASE RGBA pixels are stored row-by-row in red, green, blue, alpha order.
    raw = bytearray()
    for y in range(h):
        for x in range(w):
            color = cel.get(f"{x},{y}")
            if color:
                r, g, b, a = hex_to_rgba(color)
            else:
                r = g = b = a = 0
            raw += struct.pack("<BBBB", r, g, b, a)
    compressed = zlib.compress(bytes(raw), 9)
    layer_index = doc["layers"].index(layer)
    body = struct.pack("<HhhBHh5xHH", layer_index, 0, 0, 255, 2, 0, w, h)
    return body + compressed


def _pack_frame_tags_chunk(doc) -> bytes:
    tags = doc.get("frame_tags", [])
    if not tags:
        return None
    body = struct.pack("<H", len(tags))
    body += b"\x00" * 8
    for tag in tags:
        r, g, b, _ = hex_to_rgba(tag.get("color", "#42bce8"))
        body += struct.pack(
            "<HHBH6xBBBB",
            int(tag["from"]), int(tag["to"]), 0, 0, r, g, b, 0,
        )
        body += _pack_string(tag["name"])
    return body


def export_aseprite(doc, path: str) -> dict:
    """Write the document as a native .aseprite file (ASE spec)."""
    w, h = doc["width"], doc["height"]
    frames = doc["frames"]
    if not frames or len(frames) > 0xFFFF:
        raise ValueError(".aseprite export requires 1..65535 frames")

    palette_chunk = _pack_chunk(0x2019, _pack_palette_chunk(doc))
    tags_body = _pack_frame_tags_chunk(doc)
    frames_bytes = b""
    for frame_index, frame in enumerate(frames):
        chunks = []
        if frame_index == 0:
            chunks.extend(
                _pack_chunk(0x2004, _pack_layer_chunk(layer))
                for layer in doc["layers"]
            )
            chunks.append(palette_chunk)
            if tags_body:
                chunks.append(_pack_chunk(0x2018, tags_body))
        for layer in doc["layers"]:
            cel_body = _pack_cel_chunk(doc, frame["id"], layer)
            if cel_body is not None:
                chunks.append(_pack_chunk(0x2005, cel_body))
        chunk_data = b"".join(chunks)
        chunk_count = len(chunks)
        duration = max(1, min(0xFFFF, int(frame.get("duration", 100))))
        frame_size = 16 + len(chunk_data)
        frame_header = struct.pack(
            "<IHHH2xI", frame_size, 0xF1FA,
            min(chunk_count, 0xFFFF), duration, chunk_count,
        )
        frames_bytes += frame_header + chunk_data

    file_size = 128 + len(frames_bytes)
    speed = max(1, min(0xFFFF, int(frames[0].get("duration", 100))))
    color_count = min(len(doc.get("palette", [])), 0xFFFF)
    header = struct.pack(
        "<IHHHHHIHII",
        file_size, 0xA5E0, len(frames), w, h, 32, 1, speed, 0, 0,
    )
    header += struct.pack("<B3xHBBhhHH84x", 0, color_count, 1, 1, 0, 0, 0, 0)
    assert len(header) == 128

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(header + frames_bytes)
    size = os.path.getsize(path)
    return {"path": os.path.abspath(path), "format": "aseprite",
            "frames": len(frames), "layers": len(doc["layers"]),
            "bytes": size}


def export(doc, path: str, scale: int = 1, spritesheet: bool = False,
           direction: str = "horizontal", data_path: Optional[str] = None) -> dict:
    """Dispatch export by file extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png" and spritesheet:
        return export_spritesheet(doc, path, data_path, direction, scale)
    if ext == ".png":
        return export_png(doc, path, scale)
    if ext == ".gif":
        return export_gif(doc, path, scale)
    if ext == ".aseprite":
        return export_aseprite(doc, path)
    if ext == ".ase":
        return export_aseprite(doc, path)
    raise ValueError(f"unsupported export format: {ext} (png/gif/aseprite)")


def supported_formats() -> dict:
    return {"formats": ["png", "gif", "aseprite"], "requires_pillow": not HAS_PIL}


def export_png_sequence(doc, directory: str, scale: int = 1,
                        filename: str = "frame") -> dict:
    """Export every frame as its own PNG (Aseprite File > Export > PNG file)."""
    scale = max(1, int(scale))
    os.makedirs(directory, exist_ok=True)
    paths = []
    for frame in doc["frames"]:
        p = os.path.join(directory, f"{filename}{frame['id']:03d}.png")
        export_png(doc, p, scale, frame_id=frame["id"]) if False else None
        img = _grid_to_pil(doc, frame["id"])
        if scale > 1:
            img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
        img.save(p, "PNG")
        paths.append(os.path.abspath(p))
    return {"directory": os.path.abspath(directory), "frames": len(paths),
            "files": paths, "scale": scale, "format": "png-sequence"}
