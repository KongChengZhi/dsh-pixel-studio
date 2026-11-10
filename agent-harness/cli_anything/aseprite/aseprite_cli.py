"""cli-anything-aseprite: CLI harness for Aseprite pixel-art editor.

Turns the Aseprite pixel-art workflow into an agent-usable CLI:
one-shot subcommands (--json for machines) plus an interactive REPL,
with real-time ANSI terminal rendering of the canvas so a human can
watch the AI draw, stroke by stroke.

Both the state model (project files) and the native .aseprite binary
format are fully handled in Python, so no GUI or binary is required;
when a real `aseprite` executable exists, it is used for advanced
batch conversion (sprite sheets, palettes, dithering).
"""

import json
import os
import sys
import shutil
import functools

import click

from .core import model
from .core.session import Session
from .core import canvas, layers, palette, animation, export
from .utils.terminal import render_terminal, render_preview_png
from .utils import aseprite_backend

__version__ = "1.0.0"

PROJECT_EXT = ".pxa"  # cli-anything aseprite project (JSON document)

_session = Session()
_state_file = None


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _echo_terminal(frame: str) -> None:
    """Print a terminal frame without failing on legacy Windows code pages."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        frame.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        frame = frame.replace("\u2580", "#").replace("\u2584", "#")
        frame = frame.encode(encoding, errors="replace").decode(encoding)
    click.echo(frame, color=True)

def _output(data: dict, ctx: click.Context) -> None:
    if ctx.obj.get("json"):
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, (dict, list)):
                    click.echo(f"  {key}: {json.dumps(val, ensure_ascii=False, default=str)}")
                else:
                    click.echo(f"  {key}: {val}")


def _need_doc(ctx: click.Context):
    if _session.doc is None:
        click.echo(json.dumps({"error": "no project open (use 'project new' or 'project open')"})
                   if ctx.obj.get("json") else "Error: no project open (use 'project new' or 'project open')")
        ctx.exit(1)


def _autosave(ctx: click.Context) -> None:
    """Persist document + undo/redo stacks (single-command mode)."""
    if _session.doc is not None and _state_file:
        model_json = json.loads(json.dumps(_session.doc))
        from .utils.io import locked_save_json
        locked_save_json(_state_file, model_json)
        _session.save_state(_state_file)


def handle_error(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context()
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if ctx.obj.get("json"):
                click.echo(json.dumps({"error": str(exc), "type": type(exc).__name__}))
            else:
                click.echo(f"Error: {exc}", err=True)
            ctx.exit(1)
    return wrapper


def mutation(fn):
    """Decorator: push undo snapshot before mutation, print + autosave + log after."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context()
        _need_doc(ctx)
        _session.push_undo()
        result = fn(*args, **kwargs)
        _output(result, ctx)
        _session.log(result.get("op", fn.__name__), result.get("detail", ""),
                     result.get("pixels", 0))
        _autosave(ctx)
        return result
    return wrapper


# ---------------------------------------------------------------------------
# Project management
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.option("--json", "json_flag", is_flag=True, help="Machine-readable JSON output")
@click.option("--file", "file", type=click.Path(), default=None, help="Project file (.pxa)")
@click.pass_context
def cli(ctx, json_flag, file):
    """Aseprite pixel-art harness. With no subcommand, starts the REPL."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_flag
    global _state_file
    _state_file = file
    if file and os.path.isfile(file) and _session.doc is None:
        try:
            from .utils.io import load_json
            doc = load_json(file)
            _session.set_document(doc, file, record=False)
            _session.load_state(file)
            canvas.load_clipboard(file)
            canvas.load_modes(file)
        except Exception as exc:
            click.echo(f"Warning: could not load {file}: {exc}", err=True)
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


@cli.group()
def project():
    """Project lifecycle: new, open, save, info, close."""


@project.command("new")
@click.argument("name", default="untitled")
@click.option("--width", default=None, type=int, help="Canvas width in px (1..1024)")
@click.option("--height", default=None, type=int, help="Canvas height in px (1..1024)")
@click.option("--preset", default=None, type=click.Choice(list(model.CANVAS_PRESETS.keys())),
              help="Preset size: icon16/sprite32/avatar64/portrait128/scene256/wide512/max1024")
@click.option("--palette", "palette_name", default=None, help="Classic palette name (pico8/db16/sweetie16/na16)")
@click.option("--save", "save_path", type=click.Path(), default=None, help="Immediately save to path")
@click.pass_context
@handle_error
def project_new(ctx, name, width, height, preset, palette_name, save_path):
    """Create a new sprite project (any size up to 1024x1024)."""
    global _state_file
    if preset:
        width, height = model.CANVAS_PRESETS[preset]
    if width is None:
        width = 32
    if height is None:
        height = width
    doc = model.new_document(width, height, name)
    if palette_name:
        palette.apply_palette(doc, palette_name)
    _session.set_document(doc, save_path)
    result = {"op": "project new", "detail": name, "name": name,
              "width": width, "height": height,
              "preset": preset or "custom",
              "palette": palette_name or "default"}
    _output(result, ctx)
    if save_path:
        _state_file = save_path
    if _state_file:
        _autosave(ctx)


@project.command("open")
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
@handle_error
def project_open(ctx, path):
    """Open a .pxa project or exported .aseprite/.png file."""
    from .utils.io import load_json
    ext = os.path.splitext(path)[1].lower()
    if ext in (".pxa", ".json"):
        doc = load_json(path)
        _session.set_document(doc, path)
        result = {"op": "project open", "detail": path, "name": doc["name"],
                  "width": doc["width"], "height": doc["height"],
                  "frames": len(doc["frames"]), "layers": len(doc["layers"])}
    elif ext == ".aseprite":
        raise ValueError("importing .aseprite binary is not supported yet; "
                         "use export to produce it, or open a .pxa file")
    elif ext == ".png":
        raise ValueError("importing PNG is not supported yet; create a new project "
                         "and use pixel commands, or export to PNG")
    else:
        raise ValueError(f"unsupported project file: {ext}")
    _output(result, ctx)


@project.command("save")
@click.option("--as", "save_as", type=click.Path(), default=None, help="Save as new path")
@click.pass_context
@handle_error
def project_save(ctx, save_as):
    """Save the current project."""
    _need_doc(ctx)
    global _state_file
    if save_as:
        _state_file = save_as
        _session.path = save_as
    if not _state_file:
        _state_file = f"{_session.doc['name']}{PROJECT_EXT}"
        _session.path = _state_file
    from .utils.io import locked_save_json
    locked_save_json(_state_file, _session.doc)
    _output({"op": "project save", "detail": _state_file, "path": os.path.abspath(_state_file)}, ctx)


@project.command("info")
@click.pass_context
@handle_error
def project_info(ctx):
    """Show project status (size, frames, layers, palette, pixels)."""
    _need_doc(ctx)
    _output(_session.status(), ctx)


@project.command("close")
@click.pass_context
@handle_error
def project_close(ctx):
    """Close the current project."""
    _need_doc(ctx)
    _session.set_document(None, None)
    _output({"op": "project close", "detail": "closed"}, ctx)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

@cli.group()
def pixel():
    """Pixel-level drawing primitives."""


@pixel.command("set")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("color")
@click.pass_context
@handle_error
@mutation
def pixel_set(ctx, x, y, color):
    """Set one pixel at (x,y) to COLOR (#rgb/#rrggbb/#rrggbbaa or css name)."""
    return {**canvas.draw_pixel(_session.doc, x, y, color),
            "op": "pixel set", "detail": f"({x},{y}) {color}"}


@pixel.command("line")
@click.argument("x0", type=int)
@click.argument("y0", type=int)
@click.argument("x1", type=int)
@click.argument("y1", type=int)
@click.argument("color")
@click.pass_context
@handle_error
@mutation
def pixel_line(ctx, x0, y0, x1, y1, color):
    """Draw a line from (x0,y0) to (x1,y1)."""
    return {**canvas.draw_line(_session.doc, x0, y0, x1, y1, color),
            "op": "pixel line", "detail": f"({x0},{y0})->({x1},{y1}) {color}"}


@pixel.command("rect")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("w", type=int)
@click.argument("h", type=int)
@click.argument("color")
@click.option("--fill", is_flag=True, help="Filled rectangle")
@click.pass_context
@handle_error
@mutation
def pixel_rect(ctx, x, y, w, h, color, fill):
    """Draw a rectangle outline (or --fill) at (x,y) w x h."""
    return {**canvas.draw_rect(_session.doc, x, y, w, h, color, fill),
            "op": "pixel rect", "detail": f"({x},{y}) {w}x{h} {'fill ' if fill else ''}{color}"}


@pixel.command("ellipse")
@click.argument("cx", type=int)
@click.argument("cy", type=int)
@click.argument("rx", type=int)
@click.argument("ry", type=int)
@click.argument("color")
@click.option("--fill", is_flag=True, help="Filled ellipse")
@click.pass_context
@handle_error
@mutation
def pixel_ellipse(ctx, cx, cy, rx, ry, color, fill):
    """Draw an ellipse centered at (cx,cy) with radii rx,ry."""
    return {**canvas.draw_ellipse(_session.doc, cx, cy, rx, ry, color, fill),
            "op": "pixel ellipse", "detail": f"({cx},{cy}) rx{rx} ry{ry} {color}"}


@pixel.command("flood")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("color")
@click.option("--tolerance", default=0, show_default=True, help="Color similarity tolerance 0..255")
@click.pass_context
@handle_error
@mutation
def pixel_flood(ctx, x, y, color, tolerance):
    """Flood-fill the connected region starting at (x,y)."""
    return {**canvas.flood_fill(_session.doc, x, y, color, tolerance),
            "op": "pixel flood", "detail": f"({x},{y}) {color}"}


@pixel.command("erase")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.option("--radius", default=0, show_default=True, help="Erase radius (square brush)")
@click.pass_context
@handle_error
@mutation
def pixel_erase(ctx, x, y, radius):
    """Erase pixel(s) at (x,y)."""
    return {**canvas.erase(_session.doc, x, y, radius),
            "op": "pixel erase", "detail": f"({x},{y}) r{radius}"}


@pixel.command("symmetry")
@click.argument("mode", type=click.Choice(["h", "v", "both", "off"]))
@click.pass_context
@handle_error
def pixel_symmetry(ctx, mode):
    """Enable symmetry drawing: h / v / both / off (Aseprite Symmetry)."""
    _output(canvas.set_symmetry(None if mode == "off" else mode), ctx)
    if _state_file:
        canvas.save_modes(_state_file)


@pixel.command("tiled")
@click.argument("state", type=click.Choice(["on", "off"]))
@click.pass_context
@handle_error
def pixel_tiled(ctx, state):
    """Toggle tiled mode: drawing wraps around edges (seamless textures)."""
    _output(canvas.set_tiled(state == "on"), ctx)
    if _state_file:
        canvas.save_modes(_state_file)


@pixel.command("gradient")
@click.argument("x0", type=int)
@click.argument("y0", type=int)
@click.argument("x1", type=int)
@click.argument("y1", type=int)
@click.argument("color0")
@click.argument("color1")
@click.option("--direction", type=click.Choice(["line", "horizontal", "vertical"]), default="line")
@click.pass_context
@handle_error
@mutation
def pixel_gradient(ctx, x0, y0, x1, y1, color0, color1, direction):
    """Gradient between two colors (supports rgb16)."""
    return {**canvas.gradient(_session.doc, x0, y0, x1, y1, color0, color1, direction),
            "op": "pixel gradient", "detail": f"({x0},{y0})->({x1},{y1})"}


@pixel.command("get")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.pass_context
@handle_error
def pixel_get(ctx, x, y):
    """Read the composited color at (x,y)."""
    _need_doc(ctx)
    color = canvas.get_region(_session.doc, x, y, 1, 1)["rows"][0][0]
    _output({"x": x, "y": y, "color": color or "transparent"}, ctx)


@cli.group()
def region():
    """Region operations (rectangular areas)."""


@region.command("get")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("w", type=int)
@click.argument("h", type=int)
@click.pass_context
@handle_error
def region_get(ctx, x, y, w, h):
    """Read a region as a grid of colors (for AI planning)."""
    _need_doc(ctx)
    _output(canvas.get_region(_session.doc, x, y, w, h), ctx)


@region.command("invert")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("w", type=int)
@click.argument("h", type=int)
@click.pass_context
@handle_error
@mutation
def region_invert(ctx, x, y, w, h):
    """Invert colors in a region."""
    return {**canvas.invert_region(_session.doc, x, y, w, h),
            "op": "region invert", "detail": f"({x},{y}) {w}x{h}"}


@region.command("fill")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("w", type=int)
@click.argument("h", type=int)
@click.argument("color")
@click.pass_context
@handle_error
@mutation
def region_fill(ctx, x, y, w, h, color):
    """Fill a rectangular selection with COLOR (Aseprite marquee + bucket)."""
    return {**canvas.region_fill(_session.doc, x, y, w, h, color),
            "op": "region fill", "detail": f"({x},{y}) {w}x{h} {color}"}


@region.command("clear")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("w", type=int)
@click.argument("h", type=int)
@click.pass_context
@handle_error
@mutation
def region_clear(ctx, x, y, w, h):
    """Clear a rectangular selection to transparency (Aseprite ClearRect)."""
    return {**canvas.region_clear(_session.doc, x, y, w, h),
            "op": "region clear", "detail": f"({x},{y}) {w}x{h}"}


@region.command("stroke")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("w", type=int)
@click.argument("h", type=int)
@click.argument("color")
@click.pass_context
@handle_error
@mutation
def region_stroke(ctx, x, y, w, h, color):
    """Stroke a rectangular selection border (Aseprite Stroke)."""
    return {**canvas.region_stroke(_session.doc, x, y, w, h, color),
            "op": "region stroke", "detail": f"({x},{y}) {w}x{h} {color}"}


@region.command("copy")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("w", type=int)
@click.argument("h", type=int)
@click.pass_context
@handle_error
def region_copy(ctx, x, y, w, h):
    """Copy a rectangular selection to the in-memory clipboard."""
    _need_doc(ctx)
    result = canvas.region_copy(_session.doc, x, y, w, h)
    if _state_file:
        canvas.save_clipboard(_state_file)
    _output({**result, "op": "region copy", "detail": f"({x},{y}) {w}x{h}"}, ctx)


@region.command("paste")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.pass_context
@handle_error
@mutation
def region_paste(ctx, x, y):
    """Paste the clipboard at (x,y), overwriting pixels."""
    return {**canvas.region_paste(_session.doc, x, y),
            "op": "region paste", "detail": f"({x},{y})"}


@region.command("move")
@click.argument("x", type=int)
@click.argument("y", type=int)
@click.argument("w", type=int)
@click.argument("h", type=int)
@click.argument("dx", type=int)
@click.argument("dy", type=int)
@click.pass_context
@handle_error
@mutation
def region_move(ctx, x, y, w, h, dx, dy):
    """Move selection content by (dx,dy); source region is cleared."""
    return {**canvas.region_move(_session.doc, x, y, w, h, dx, dy),
            "op": "region move", "detail": f"({x},{y}) {w}x{h} +({dx},{dy})"}


@cli.group()
def canvas_cmd():
    """Canvas sizing (Aseprite Sprite > Canvas Size / Sprite Size)."""


@canvas_cmd.command("resize")
@click.argument("width", type=int)
@click.argument("height", type=int)
@click.option("--anchor", type=click.Choice(["nw", "n", "ne", "w", "c", "e", "sw", "s", "se"]), default="c")
@click.option("--scale", is_flag=True, help="Rescale content instead of moving it")
@click.pass_context
@handle_error
@mutation
def canvas_resize(ctx, width, height, anchor, scale):
    """Resize the canvas (anchor keeps content position; --scale rescales)."""
    return {**canvas.resize_canvas(_session.doc, width, height, anchor, scale),
            "op": "canvas resize", "detail": f"{width}x{height} anchor={anchor}"}


@canvas_cmd.command("rescale")
@click.argument("width", type=int)
@click.argument("height", type=int)
@click.pass_context
@handle_error
@mutation
def canvas_rescale(ctx, width, height):
    """Rescale sprite content to new dimensions (nearest neighbor)."""
    return {**canvas.rescale(_session.doc, width, height),
            "op": "canvas rescale", "detail": f"{width}x{height}"}


@cli.group()
def transform():
    """Whole-layer transforms."""


@transform.command("apply")
@click.argument("op", type=click.Choice(["flip-h", "flip-v", "rotate-90", "rotate-180", "rotate-270"]))
@click.pass_context
@handle_error
@mutation
def transform_apply(ctx, op):
    """flip-h | flip-v | rotate-90 | rotate-180 | rotate-270"""
    return {**canvas.transform(_session.doc, op),
            "op": "transform", "detail": op}


# ---------------------------------------------------------------------------
# Palette / Layers / Frames
# ---------------------------------------------------------------------------

@cli.group()
def palette_cmd():
    """Palette management."""


@palette_cmd.command("list")
@click.option("--classic", is_flag=True, help="List built-in classic palettes")
@click.pass_context
@handle_error
def palette_list(ctx, classic):
    if classic:
        _output(palette.list_palettes(), ctx)
        return
    _need_doc(ctx)
    _output({"palette": _session.doc["palette"]}, ctx)


@palette_cmd.command("apply")
@click.argument("name")
@click.pass_context
@handle_error
@mutation
def palette_apply(ctx, name):
    """Apply a classic palette: pico8, db16, sweetie16, na16."""
    return {**palette.apply_palette(_session.doc, name), "op": "palette apply", "detail": name}


@palette_cmd.command("add")
@click.argument("name")
@click.argument("color")
@click.pass_context
@handle_error
@mutation
def palette_add(ctx, name, color):
    """Add a named color to the palette."""
    return {**palette.add_color(_session.doc, name, color), "op": "palette add", "detail": name}


@palette_cmd.command("nearest")
@click.argument("color")
@click.pass_context
@handle_error
def palette_nearest(ctx, color):
    """Map a color to the nearest palette entry."""
    _need_doc(ctx)
    _output(palette.nearest_color(_session.doc, color), ctx)


@palette_cmd.command("quantize")
@click.pass_context
@handle_error
@mutation
def palette_quantize(ctx):
    """Snap all pixels to the nearest palette color."""
    return {**palette.quantize_canvas(_session.doc), "op": "palette quantize", "detail": ""}


@cli.group()
def layer():
    """Layer management."""


@layer.command("list")
@click.pass_context
@handle_error
def layer_list(ctx):
    _need_doc(ctx)
    _output(layers.list_layers(_session.doc), ctx)


@layer.command("add")
@click.argument("name", default="layer")
@click.pass_context
@handle_error
@mutation
def layer_add(ctx, name):
    return {**layers.add_layer(_session.doc, name), "op": "layer add", "detail": name}


@layer.command("remove")
@click.option("--id", "layer_id", type=int, default=None)
@click.pass_context
@handle_error
@mutation
def layer_remove(ctx, layer_id):
    return {**layers.remove_layer(_session.doc, layer_id), "op": "layer remove", "detail": str(layer_id)}


@layer.command("set")
@click.argument("layer_id", type=int)
@click.pass_context
@handle_error
@mutation
def layer_set(ctx, layer_id):
    return {**layers.set_layer(_session.doc, layer_id), "op": "layer set", "detail": str(layer_id)}


@layer.command("property")
@click.argument("layer_id", type=int)
@click.argument("prop", type=click.Choice(["name", "visible", "opacity", "reference"]))
@click.argument("value")
@click.pass_context
@handle_error
@mutation
def layer_property(ctx, layer_id, prop, value):
    return {**layers.set_layer_property(_session.doc, layer_id, prop, value),
            "op": "layer property", "detail": f"{layer_id}.{prop}={value}"}


@layer.command("duplicate")
@click.option("--id", "layer_id", type=int, default=None)
@click.option("--name", default=None)
@click.pass_context
@handle_error
@mutation
def layer_duplicate(ctx, layer_id, name):
    return {**layers.duplicate_layer(_session.doc, layer_id, name), "op": "layer duplicate", "detail": ""}


@layer.command("merge")
@click.pass_context
@handle_error
@mutation
def layer_merge(ctx):
    return {**layers.merge_visible(_session.doc), "op": "layer merge", "detail": ""}


@cli.group()
def frame():
    """Animation frames."""


@frame.command("list")
@click.pass_context
@handle_error
def frame_list(ctx):
    _need_doc(ctx)
    _output(animation.list_frames(_session.doc), ctx)


@frame.command("add")
@click.option("--duration", default=100, show_default=True, help="Frame duration in ms")
@click.option("--blank", is_flag=True, help="Add a blank frame instead of copying")
@click.pass_context
@handle_error
@mutation
def frame_add(ctx, duration, blank):
    return {**animation.add_frame(_session.doc, duration, copy=not blank),
            "op": "frame add", "detail": f"dur={duration}"}


@frame.command("set")
@click.argument("frame_id", type=int)
@click.pass_context
@handle_error
@mutation
def frame_set(ctx, frame_id):
    return {**animation.set_frame(_session.doc, frame_id), "op": "frame set", "detail": str(frame_id)}


@frame.command("remove")
@click.option("--id", "frame_id", type=int, default=None)
@click.pass_context
@handle_error
@mutation
def frame_remove(ctx, frame_id):
    return {**animation.remove_frame(_session.doc, frame_id), "op": "frame remove", "detail": ""}


@frame.command("duration")
@click.argument("frame_id", type=int)
@click.argument("duration", type=int)
@click.pass_context
@handle_error
@mutation
def frame_duration(ctx, frame_id, duration):
    return {**animation.set_duration(_session.doc, frame_id, duration), "op": "frame duration", "detail": ""}


@frame.command("tag")
@click.argument("action", type=click.Choice(["add", "list", "remove"]))
@click.argument("name", required=False)
@click.argument("from_frame", type=int, required=False)
@click.argument("to_frame", type=int, required=False)
@click.option("--color", default="#42bce8")
@click.pass_context
@handle_error
@mutation
def frame_tag(ctx, action, name, from_frame, to_frame, color):
    """Frame tags (named animation ranges): add/list/remove."""
    if action == "list":
        return {**model.list_tags(_session.doc), "op": "frame tag list"}
    if action == "add":
        if not name or from_frame is None or to_frame is None:
            raise ValueError("usage: frame tag add NAME FROM TO [--color #hex]")
        return {**model.add_tag(_session.doc, name, from_frame, to_frame, color),
                "op": "frame tag add", "detail": name}
    if not name:
        raise ValueError("usage: frame tag remove NAME")
    return {**model.remove_tag(_session.doc, name),
            "op": "frame tag remove", "detail": name}


@frame.command("duplicate")
@click.option("--id", "frame_id", type=int, default=None)
@click.pass_context
@handle_error
@mutation
def frame_duplicate(ctx, frame_id):
    return {**animation.duplicate_frame(_session.doc, frame_id), "op": "frame duplicate", "detail": ""}


# ---------------------------------------------------------------------------
# Undo / redo / status
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
@handle_error
def undo(ctx):
    """Undo the last mutation (REPL sessions keep a full stack)."""
    _need_doc(ctx)
    result = _session.undo()
    _autosave(ctx)
    _output({"op": "undo", **result}, ctx)


@cli.command()
@click.pass_context
@handle_error
def redo(ctx):
    """Redo the last undone mutation."""
    _need_doc(ctx)
    result = _session.redo()
    _autosave(ctx)
    _output({"op": "redo", **result}, ctx)


@cli.command()
@click.pass_context
@handle_error
def status(ctx):
    """Show session status."""
    _need_doc(ctx)
    _output(_session.status(), ctx)


@cli.command("history")
@click.pass_context
@handle_error
def history_cmd(ctx):
    """Show operation history."""
    _need_doc(ctx)
    _output(_session.history_json(), ctx)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@cli.group()
def export_cmd():
    """Export the artwork."""


@export_cmd.command("png")
@click.argument("path", type=click.Path())
@click.option("--scale", default=1, show_default=True, help="Nearest-neighbor upscale factor")
@click.pass_context
@handle_error
def export_png(ctx, path, scale):
    _need_doc(ctx)
    _output(export.export_png(_session.doc, path, scale), ctx)


@export_cmd.command("gif")
@click.argument("path", type=click.Path())
@click.option("--scale", default=1, show_default=True)
@click.option("--loop", default=0, show_default=True)
@click.pass_context
@handle_error
def export_gif(ctx, path, scale, loop):
    _need_doc(ctx)
    _output(export.export_gif(_session.doc, path, scale, loop), ctx)


@export_cmd.command("spritesheet")
@click.argument("path", type=click.Path())
@click.option("--data", "data_path", type=click.Path(), default=None, help="JSON metadata path")
@click.option("--direction", type=click.Choice(["horizontal", "vertical"]), default="horizontal")
@click.option("--scale", default=1, show_default=True)
@click.pass_context
@handle_error
def export_sheet(ctx, path, data_path, direction, scale):
    _need_doc(ctx)
    _output(export.export_spritesheet(_session.doc, path, data_path, direction, scale), ctx)


@export_cmd.command("aseprite")
@click.argument("path", type=click.Path())
@click.pass_context
@handle_error
def export_aseprite(ctx, path):
    """Export native .aseprite binary (opens in the real Aseprite editor)."""
    _need_doc(ctx)
    _output(export.export_aseprite(_session.doc, path), ctx)


@export_cmd.command("pngs")
@click.argument("directory", type=click.Path())
@click.option("--scale", default=1, show_default=True)
@click.option("--filename", default="frame", show_default=True)
@click.pass_context
@handle_error
def export_pngs(ctx, directory, scale, filename):
    """Export every frame as its own PNG (Aseprite PNG sequence)."""
    _need_doc(ctx)
    _output(export.export_png_sequence(_session.doc, directory, scale, filename), ctx)


@export_cmd.command("formats")
@click.pass_context
@handle_error
def export_formats(ctx):
    _output(export.supported_formats(), ctx)


# ---------------------------------------------------------------------------
# Terminal rendering (real-time human feedback)
# ---------------------------------------------------------------------------

@cli.command("terminal")
@click.option("--scale", default=1, show_default=True, help="Canvas px per character cell")
@click.option("--no-color", is_flag=True, help="Plain text output")
@click.option("--frame", "frame_id", type=int, default=None)
@click.option("--onion", default=0, show_default=True, help="Onion-skin ghost frames (Aseprite parity)")
@click.pass_context
@handle_error
def terminal_render(ctx, scale, no_color, frame_id, onion):
    """Render the canvas as an ANSI terminal frame (human-watchable)."""
    _need_doc(ctx)
    frame = render_terminal(_session.doc, scale=scale, frame_id=frame_id,
                            color=not no_color, onion=onion)
    if ctx.obj.get("json"):
        _output({"frame": frame, "width": _session.doc["width"],
                 "height": _session.doc["height"], "ansi": not no_color}, ctx)
    else:
        _echo_terminal(frame)


@cli.command("preview")
@click.argument("path", type=click.Path())
@click.option("--scale", default=8, show_default=True)
@click.pass_context
@handle_error
def preview_png(ctx, path, scale):
    """Render a preview PNG of the canvas (checkerboard background)."""
    _need_doc(ctx)
    p = render_preview_png(_session.doc, path, scale)
    _output({"path": os.path.abspath(p)}, ctx)


@cli.command("grid")
@click.option("--frame", "frame_id", type=int, default=None)
@click.option("--scale", "gs", default=1, show_default=True,
              help="Downsample factor (every N-th pixel) for large canvases")
@click.pass_context
@handle_error
def grid_cmd(ctx, frame_id, gs):
    """Dump the composited canvas as compact base64 RGBA (for UI rendering)."""
    import base64 as _b64
    _need_doc(ctx)
    grid = model.render_canvas(_session.doc, frame_id)
    w, h = _session.doc["width"], _session.doc["height"]
    gs = max(1, int(gs))
    if gs > 1:
        sw = (w + gs - 1) // gs
        sh = (h + gs - 1) // gs
        raw = bytearray()
        for y in range(0, h, gs):
            for x in range(0, w, gs):
                r, g, b, a = grid[y][x]
                raw += bytes((r, g, b, a))
        _output({"width": sw, "height": sh, "scale": gs,
                 "data": _b64.b64encode(bytes(raw)).decode("ascii")}, ctx)
    else:
        raw = bytearray()
        for y in range(h):
            for x in range(w):
                r, g, b, a = grid[y][x]
                raw += bytes((r, g, b, a))
        _output({"width": w, "height": h, "scale": 1,
                 "data": _b64.b64encode(bytes(raw)).decode("ascii")}, ctx)


# ---------------------------------------------------------------------------
# Backend (real aseprite binary)
# ---------------------------------------------------------------------------

@cli.group()
def backend():
    """Integration with the real aseprite binary (optional)."""


@backend.command("info")
@click.pass_context
@handle_error
def backend_info(ctx):
    _output(aseprite_backend.get_version(), ctx)


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

COMMANDS = {
    "new": "project new --width W --height H NAME",
    "open": "project open FILE.pxa",
    "save": "project save",
    "info": "project info",
    "set": "pixel set X Y COLOR",
    "line": "pixel line X0 Y0 X1 Y1 COLOR",
    "rect": "pixel rect X Y W H COLOR [--fill]",
    "ellipse": "pixel ellipse CX CY RX RY COLOR [--fill]",
    "flood": "pixel flood X Y COLOR [--tolerance N]",
    "erase": "pixel erase X Y [--radius N]",
    "undo": "undo", "redo": "redo",
    "palette": "palette list|apply NAME|add NAME COLOR",
    "layer": "layer list|add NAME|set ID|property ID PROP VAL",
    "frame": "frame list|add|set ID|duplicate",
    "export": "export png|gif|aseprite|spritesheet PATH",
    "terminal": "terminal [--scale N]",
    "help": "show this help", "quit": "exit the REPL",
}


@cli.command()
@click.pass_context
@handle_error
def repl(ctx):
    """Interactive REPL mode (default)."""
    from .utils.repl_skin import ReplSkin
    skin = ReplSkin("aseprite", version=__version__)
    skin.print_banner()
    click.echo("Type 'help' for commands, 'quit' to exit. Canvas is re-rendered "
               "after every operation so you can watch the AI draw live.")
    while True:
        try:
            line = input("aseprite> ").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            break
        if line == "help":
            for cmd, usage in COMMANDS.items():
                skin.status(cmd, usage)
            continue
        args = line.split()
        if args[0] == "new":
            name = args[1] if len(args) > 1 else "untitled"
            doc = model.new_document(32, 32, name)
            _session.set_document(doc, None)
            skin.success(f"New project '{name}' 32x32")
            _echo_terminal(render_terminal(doc))
            continue
        if args[0] == "open" and len(args) > 1:
            from .utils.io import load_json
            doc = load_json(args[1])
            _session.set_document(doc, args[1])
            skin.success(f"Opened {args[1]}")
            _echo_terminal(render_terminal(doc))
            continue
        if args[0] == "terminal":
            _need_doc(ctx)
            _echo_terminal(render_terminal(_session.doc))
            continue
        # Execute the line through the real Click CLI (session state is module-global)
        try:
            from click.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(cli, args, obj={"json": False})
            if result.exception:
                skin.error(f"{type(result.exception).__name__}: {result.exception}")
            elif result.output:
                click.echo(result.output.rstrip())
        except Exception as exc:
            skin.error(str(exc))
    skin.print_goodbye()


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
