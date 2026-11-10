# TEST.md — cli-anything-aseprite Test Plan

## 1. Test Inventory Plan

| File | Planned | Purpose |
|------|---------|---------|
| `test_core.py` | 32 unit tests | Core modules in isolation (model, canvas, palette, layers, frames, session, export internals) |
| `test_full_e2e.py` | 11 E2E tests | Real CLI invocations producing real files (.pxa, PNG, GIF, .aseprite) |

## 2. Unit Test Plan

### model.py (10 tests)
- `new_document` defaults: size, layers, frames, palette, current pointers
- dimension validation (0 and 1025 rejected)
- `set_pixel` / `pixel_at` round-trip
- `normalize_color` accepts #rgb/#rrggbb/#rrggbbaa/css names; rejects garbage
- `hex_to_rgba` / `rgba_to_hex` round-trip
- snapshot/restore round-trip
- `add_layer` / `add_frame` increment ids and set current
- `render_canvas` composites layer opacity and alpha

### canvas.py (12 tests)
- `_stroke_points` Bresenham endpoints + count
- `draw_pixel` out-of-bounds rejected
- `draw_line` paints expected count on 5x5
- `draw_rect` outline vs fill pixel counts
- `draw_ellipse` center present, bounds within rx/ry
- `flood_fill` bounded region, stops at boundary color
- `flood_fill` tolerance merging similar colors
- `erase` removes pixels
- `get_region` returns composited grid
- `invert_region` inverts rgb, keeps alpha
- `transform` flip-h/flip-v/rotate-90 preserve pixel count
- `transform` invalid op raises

### palette.py (4 tests)
- `apply_palette` replaces palette with 16 colors
- `add_color` / duplicate name rejected
- `nearest_color` picks exact match
- `quantize_canvas` snaps off-palette colors

### layers.py (3 tests)
- add/remove/set/current behavior
- last layer cannot be removed
- duplicate copies cels

### animation.py (3 tests)
- add frame copies previous cels; `--blank` gives empty
- remove last frame rejected
- set duration clamps to >= 1

## 3. E2E Test Plan

Real CLI invocations via subprocess (`cli-anything-aseprite --json`), producing files:

1. `project new` + autosave to --file → .pxa exists, JSON valid
2. Draw a smiley (pixels + lines + rects) → PNG export exists, dimensions 16x16*scale
3. PNG preview upscale is NEAREST (no blur: sample corner pixel)
4. GIF animation export: 2 frames → file exists, first bytes "GIF"
5. .aseprite export → parse header: magic 0xA5E0, frames, size, depth 32
6. .aseprite cel chunk zlib-decompress matches model pixels
7. .aseprite animation frames, layers, durations, and frame tags
8. undo/redo via CLI JSON output
9. flood fill via CLI changes region
10. terminal render returns ANSI/plain frame containing '##'
11. multi-layer merge via CLI

## 4. Realistic Workflow Scenarios

- **Workflow A (sprite hero)**: new 16x16 → palette pico8 → rect body → line arms →
  flood background → export png + aseprite. Verified: PNG/ASE sizes and pixel probes.
- **Workflow B (animation blink)**: new 32x32 → frame add (copy) → modify eye →
  export gif. Verified: GIF has 2 frames (disposal ok).
- **Workflow C (watch-the-AI)**: every mutation followed by `terminal --no-color`
  frame; assert frame contains only canvas rows + status line.
