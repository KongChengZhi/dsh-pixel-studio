# CLI Reference

Use this reference for exact `cli-anything-aseprite` syntax. Put global options before the command group:

```text
cli-anything-aseprite --file <absolute-project.pxa> --json <command> ...
```

On Windows, replace `cli-anything-aseprite` with `& $runner`, where `$runner` points to `scripts/invoke_cli.ps1`. Quote `#hex` colors in PowerShell.

## Project And Inspection

```text
project new <name> --width <1..1024> --height <1..1024> --palette <pico8|db16|sweetie16|na16>
project new <name> --preset <icon|sprite|avatar|portrait|scene|wide|max> --palette <name>
project info
project save [--as <path>]
pixel get <x> <y>
region get <x> <y> <w> <h>
history
undo
redo
terminal [--scale <n>] [--no-color] [--frame <id>] [--onion <count>]
preview <path.png> [--scale <n>]
```

Passing `--file` makes mutations persist automatically. `project open` accepts editable `.pxa`/JSON projects; PNG and `.aseprite` import are not implemented.

## Drawing

Coordinates are zero-based, with `(0, 0)` at the top left. Rectangle width and height are extents, while ellipse values are radii.

```text
pixel set <x> <y> <color>
pixel line <x0> <y0> <x1> <y1> <color>
pixel rect <x> <y> <w> <h> <color> [--fill]
pixel ellipse <cx> <cy> <rx> <ry> <color> [--fill]
pixel flood <x> <y> <color> [--tolerance <0..255>]
pixel erase <x> <y> [--radius <n>]
pixel gradient <x0> <y0> <x1> <y1> <color0> <color1> [--direction line|horizontal|vertical]
```

Colors accept `#rgb`, `#rrggbb`, `#rrggbbaa`, CSS names, or `rgb16:r,g,b` with channels from 0 to 15.

## Regions, Modes, And Canvas

```text
region fill <x> <y> <w> <h> <color>
region stroke <x> <y> <w> <h> <color>
region clear <x> <y> <w> <h>
region copy <x> <y> <w> <h>
region paste <x> <y>
region move <x> <y> <w> <h> <dx> <dy>
region invert <x> <y> <w> <h>
pixel symmetry <h|v|both|off>
pixel tiled <on|off>
canvas resize <width> <height> [--anchor nw|n|ne|w|c|e|sw|s|se] [--scale]
canvas rescale <width> <height>
transform apply <flip-h|flip-v|rotate-90|rotate-180|rotate-270>
```

Symmetry and tiled modes persist beside the project across CLI processes. Turn them off when the relevant pass is complete so later detail edits are not mirrored or wrapped accidentally.

## Palette And Layers

```text
palette list [--classic]
palette apply <pico8|db16|sweetie16|na16>
palette add <name> <color>
palette nearest <color>
palette quantize
layer list
layer add <name>
layer set <id>
layer property <id> <name|visible|opacity|reference> <value>
layer duplicate [--id <id>] [--name <name>]
layer remove [--id <id>]
layer merge
```

Opacity values are 0-255. Use `true`/`false` for visible and reference properties. Reference layers are excluded from rendering.

## Animation

```text
frame list
frame add [--duration <milliseconds>] [--blank]
frame duplicate [--id <id>]
frame set <id>
frame duration <id> <milliseconds>
frame remove [--id <id>]
frame tag add <name> <from-frame> <to-frame> [--color <#hex>]
frame tag list
frame tag remove <name>
```

`frame add` copies the current frame unless `--blank` is supplied.

## Export

```text
export png <path.png> [--scale <n>]
export gif <path.gif> [--scale <n>] [--loop <count>]
export spritesheet <path.png> [--data <path.json>] [--direction horizontal|vertical] [--scale <n>]
export pngs <directory> [--scale <n>] [--filename <prefix>]
export aseprite <path.aseprite>
```

Use nearest-neighbor integer scaling. Keep a 1x PNG for engines and an enlarged copy for review or presentation.
