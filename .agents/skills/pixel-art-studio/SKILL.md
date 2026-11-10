---
name: pixel-art-studio
description: Create, edit, animate, inspect, and export pixel-art sprites, icons, tiles, portraits, and game assets with cli-anything-aseprite. Use when the user wants a pixel-art deliverable or work on a .pxa project; do not use for general raster illustration, photo editing, or merely discussing pixel-art theory.
---

# Pixel Art Studio

Use `cli-anything-aseprite` as a stateful drawing tool. Produce the artwork, inspect it visually, revise visible problems, and return usable files. Do not stop after proposing commands.

## Tool Setup

On Windows, invoke [`scripts/invoke_cli.ps1`](scripts/invoke_cli.ps1). It resolves the installed CLI even when Python's Scripts directory is absent from `PATH`:

```powershell
$runner = Resolve-Path "<skill-dir>/scripts/invoke_cli.ps1"
& $runner --help
```

On macOS/Linux, invoke `cli-anything-aseprite` directly. If the executable is unavailable, check for this repository's `agent-harness` and install it with `python -m pip install -e <agent-harness>` only when package installation is within the user's requested scope. Otherwise report the exact prerequisite.

Read [references/cli-reference.md](references/cli-reference.md) when constructing commands or using layers, selections, animation, canvas modes, or exports. Do not guess command syntax.

## Decide The Deliverable

Honor explicit size, palette, format, animation, and output-location requests. When omitted, infer them from the intended use:

- icon or inventory item: 16x16
- character or object sprite: 32x32
- avatar: 64x64
- portrait: 128x128
- tile or texture: requested engine size; otherwise 16x16 or 32x32
- palette: `pico8` for high-contrast retro work, `db16` for muted or moody work, `sweetie16` for bright work, `na16` for earthy work

Default to a transparent background unless the request implies a scene or opaque tile. Use the user's output directory; otherwise create `artwork/<slug>/` below the current working directory. Keep these artifacts together:

- `<slug>.pxa`: editable source of truth
- `<slug>.png`: canonical 1x PNG
- `<slug>@8x.png`: nearest-neighbor viewing copy
- `<slug>-preview.png`: checkerboard review image; remove it only if it is not useful to the user
- animation outputs such as GIF, sprite sheet, and frame PNGs when requested

Do not overwrite an unrelated existing project. Open an existing `.pxa` when the user asks to revise it. The harness cannot import PNG or `.aseprite` files into an editable project; state that limitation instead of pretending an import succeeded.

## Draw In Passes

Plan the coordinate geometry and a small color hierarchy before mutating the canvas. Use 3-6 functional colors first: outline, deepest shadow, base, light, highlight, and optional accent. Prefer palette colors and large primitives over scattered individual pixels.

1. Create or inspect the project. Use absolute paths for the `.pxa` file across separate CLI calls.
2. Block the silhouette with filled rectangles, ellipses, and lines. Judge recognizability at 1x before adding detail.
3. Establish a one-pixel outline and base-color regions. Keep interior clusters connected and intentional.
4. Add shadows on one consistent side and highlights on the opposite side. Avoid pillow shading and isolated noise pixels.
5. Add focal details with individual pixels. Use selection operations for repeated regions and symmetry or tiled mode only when they serve the requested form.
6. For animation, duplicate a strong key frame, change only what must move, set deliberate frame durations, and inspect the exported GIF.
7. Quantize only when off-palette colors were intentionally used and snapping them will not destroy desired color nuance.

After each logical pass, render a checkerboard preview at 8x and inspect it with the image-viewing tool. Use `terminal` for a quick structural check when useful. Do not emit a user-facing update for every primitive; summarize each completed pass.

## Visual Review

Treat visual inspection as part of creation, not optional verification. Check:

- silhouette reads at native resolution
- light direction and contrast are consistent
- outline does not swallow thin features
- curves use deliberate pixel stair-steps rather than accidental bumps
- no unintended holes, stray pixels, clipped edges, or filled transparent areas
- repeated tiles meet cleanly at all four edges
- animation loops without a positional jump and preserves volume

When a problem is visible, use `undo` or targeted region/pixel edits, regenerate the preview, and inspect again. Do not declare success from a zero exit code alone.

## Validate And Export

Before delivery:

1. Run `project info` with `--json` and confirm dimensions, frame count, layer count, palette, and nonzero pixel count.
2. Export the canonical 1x PNG and an 8x nearest-neighbor PNG. For animation, also export GIF and preferably a sprite sheet with JSON metadata. Export native `.aseprite` when requested.
3. Open the final PNG with the image-viewing tool. Open the GIF or representative frames when animation is involved.
4. When delivering `.aseprite` and a real Aseprite executable is available, batch-load the file with Aseprite and round-trip it to PNG or GIF. Compare dimensions, frame count, durations, and rendered pixels with the CLI exports; the writer returning success is not sufficient validation. If Aseprite is unavailable, state that the native file was not externally validated.
5. Confirm all reported output paths exist and no temporary `.tmp` files remain.

Return the result first, then list the editable source and exported files, dimensions, palette, frame count, and the visual checks performed. Mention limitations only when they affect the delivered result.
