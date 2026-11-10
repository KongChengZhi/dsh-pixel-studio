# dsh-cli-anything-aseprite

**Aseprite pixel-art studio for DeepSeek Harness (DSH).**

An agent-usable CLI harness for the [Aseprite](https://www.aseprite.com) pixel-art
editor, built with the [CLI-Anything](https://github.com/HKUDS/CLI-Anything)
methodology, plus a DSH plugin that turns it into 18 model tools. The AI draws
pixel art **like a human** — one deliberate stroke at a time — and every stroke
is rendered live as an ANSI terminal frame, so humans can watch the AI work in
real time.

```
DSH 像素画工作室：AI 像人类一样分步绘制像素画（打形→底色→阴影→高光），
每一步操作实时渲染到终端，人类全程可见。
```

## ✨ Features

- **Human drawing vocabulary**: pixel / line (Bresenham) / rect / ellipse /
  flood fill / eraser — plus **symmetry** (h/v/both), **tiled mode**
  (seamless textures), **gradient** (rgb16 interpolation).
- **Selection (Aseprite semantics)**: fill / stroke / clear / copy (persistent
  clipboard) / paste / move / get.
- **Layers**: add / remove / duplicate / merge / opacity / visibility /
  **reference layers** (rotoscoping, excluded from render).
- **Animation**: frames, durations, **frame tags**, **onion-skin** ghost
  rendering in the terminal.
- **Canvas**: free size 1..1024², presets (icon…max), **resize with 9-grid
  anchor**, **nearest-neighbor rescale**.
- **Colors**: classic palettes (pico8/db16/sweetie16/na16) + **rgb16:r,g,b
  4096-color mode** (16×16×16 indexed RGB).
- **Export**: PNG (nearest upscale) / animated GIF / sprite sheet PNG+JSON /
  PNG sequence / **native .aseprite binary** (hand-written ASE writer,
  opens in the real Aseprite).
- **Undo/redo** across CLI processes (sidecar persistence), crash-safe
  concurrent saves.
- **75/75 tests** (unit + E2E, including byte-level .aseprite format checks).
- Optional **live monitor UI** (draggable overlay: ANSI canvas, preview zoom,
  layers with opacity sliders, export buttons, project switcher, workdir
  picker) — loaded as a DSH dynamic plugin, see `monitor/`.

## 📦 Install

### 1. Install the Python harness

```bash
pip install -e ./python        # provides the `cli-anything-aseprite` CLI
```

Requires Python ≥ 3.10, `click`, `Pillow`. No Aseprite binary needed — the
harness implements the document model, drawing primitives, and the native
`.aseprite` file format itself. If a real `aseprite` binary exists, set
`ASEPRITE_BIN` to enable advanced batch conversion.

### 2. Install the DSH plugin

From a checkout:

```bash
dsh plugin add ./dsh-cli-anything-aseprite
```

From npm (once published):

```bash
dsh plugin add dsh-cli-anything-aseprite
```

From GitHub:

```bash
dsh plugin add github:YOUR_USER/dsh-cli-anything-aseprite
```

Then verify the layer applied:

```bash
dsh --dump-config | grep cli-anything-aseprite
```

The plugin registers 18 `pixelart_*` tools in every session of that profile.
Workdir defaults to `~/.dsh/aseprite-work` (override with the plugin `config:
workdir:` row or `ASEPRITE_WORKDIR` env).

## 🚀 Quick start (AI draws a sprite)

1. Open a DSH session (profile with this bundle installed).
2. Ask: *"画一个 32×32 的像素勇者，pico8 调色板"* — or drive the tools manually:
   ```
   pixelart_new {name: "hero", preset: "sprite", palette: "pico8"}
   pixelart_draw {op: "line", x: 9, y: 7, x1: 9, y1: 13, color: "#1d2b53"}
   pixelart_draw {op: "rect", x: 10, y: 7, w: 12, h: 7, color: "#1d2b53"}
   pixelart_draw {op: "rect", x: 10, y: 7, w: 12, h: 4, color: "#ff004d", fill: true}
   pixelart_terminal {}     # → live ANSI frame (human-watchable)
   pixelart_export {format: "png", scale: 8}
   pixelart_export {format: "aseprite"}   # → hero.aseprite, opens in Aseprite
   ```
3. Watch the terminal frame after every stroke — the AI's canvas is always
   visible.

## 🗂️ Project layout

```
dsh-cli-anything-aseprite/
├── src/index.js            # DSH Host plugin: 18 pixelart_* tools (defineTool)
├── cordis.patch.yml        # DSH bundle patch layer
├── package.json            # dsh.bundle manifest
├── python/                 # cli-anything-aseprite Python harness
│   └── cli_anything/aseprite/
│       ├── core/           # model, canvas (drawing+symmetry+tiled+gradient),
│       │                   # palette, layers, animation, export (.aseprite
│       │                   # binary writer), session (undo)
│       ├── utils/          # terminal (ANSI frames + onion skin), io, backend
│       ├── tests/          # TEST.md plan + 73 tests
│       └── skills/SKILL.md # AI pixel-art methodology (human drawing passes)
└── monitor/                # optional live GUI monitor (dynamic DSH plugin)
```

## 🧪 Test

```bash
python3 -m pytest python/cli_anything/aseprite/tests/ -q   # 75 passing
```

## 🏗️ How it works (architecture)

```
model tools (pixelart_*)                 DSH Host plugin (src/index.js)
      │  JSON args
      ▼
cli-anything-aseprite --file X.pxa --json <cmd>     Python harness (python/)
      │
      ├── core/canvas.py   drawing primitives → sparse cel model
      ├── core/export.py   PNG/GIF/sheet/PNG-seq + .aseprite binary writer
      └── utils/terminal.py ANSI truecolor half-block frames (human view)
```

State persists per project as `<name>.pxa` (JSON document) + sidecars
(`.history.json` undo stack, `.clipboard.json` selection clipboard,
`.modes.json` symmetry/tiled) — so undo, clipboard and modes survive separate
CLI processes, exactly like a real editor session.

Every mutating tool refreshes the in-memory state and returns `version`, which
drives the live monitor UI (polling `pix-state`).

## 📚 References

- [Aseprite CLI docs](https://www.aseprite.com/docs/cli/) · [New Sprite dialog](https://aseprite.org/docs/new-sprite)
- [CLI-Anything (HKUDS)](https://github.com/HKUDS/CLI-Anything)
- DSH plugin packaging: `docs/user/develop/basic/publish.zh.md` (bundle
  manifests, `dsh plugin add`, npm/git install)

## License

MIT — see [LICENSE](LICENSE).
