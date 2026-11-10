/**
 * dsh-cli-anything-aseprite — formal DSH Host plugin.
 *
 * Registers the pixel-art studio tool set (19 tools) that drive the
 * `cli-anything-aseprite` Python harness (CLI-Anything methodology):
 * every stroke is a real CLI command against a persistent project file,
 * so AI draws pixel art like a human — one deliberate operation at a time.
 *
 * Requirements:
 *   pip install -e ./python     (the harness; `cli-anything-aseprite` CLI)
 *
 * Works on DSH 0.1.x and 0.2.x: the shell executor seam is `run(spec)` in
 * 0.1 and `execute(spec) → handle.result()` from 0.2 on, so both are probed
 * at call time. Commands are built for `bash -c` on POSIX and for
 * `pwsh -Command` on Windows.
 */
import { defineTool } from '@deepseek-ai/dsh-tools'
import { mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const name = 'cli-anything-aseprite'
export const inject = ['tools', 'timer']

/** Quote one argv word for a POSIX shell. */
function q(arg) {
  return "'" + String(arg).replace(/'/g, "'\\''") + "'"
}

/** Quote one argv word for PowerShell (single-quoted, doubled inner quotes). */
function qPwsh(arg) {
  return "'" + String(arg).replace(/'/g, "''") + "'"
}

/** Expand a leading `~` the way a shell would, on every platform. */
function expandHome(p) {
  if (typeof p !== 'string') return p
  if (p === '~') return homedir()
  if (p.startsWith('~/') || p.startsWith('~\\')) return join(homedir(), p.slice(2))
  return p
}

export function apply(ctx, config = {}) {
  const CLI = process.env.ASEPRITE_CLI || config.cli || 'cli-anything-aseprite'
  const DEFAULT_DIR = process.env.ASEPRITE_WORKDIR || config.workdir || '~/.dsh/aseprite-work'
  const workdir = expandHome(DEFAULT_DIR)

  const state = {
    version: 0, file: null, workdir, name: '', width: 0, height: 0,
    ansi: '', pixels: 0, undo: 0, redo: 0, frames: 0, layers: 0,
    palette: 0, dirty: false, lastOp: '', log: [],
  }

  // The harness workdir must exist before the shell executor tries to spawn in
  // it: a missing cwd fails the spawn itself, before the CLI ever runs.
  function ensureWorkdir() {
    try { mkdirSync(state.workdir, { recursive: true }) } catch (e) { /* surfaced by the CLI run below */ }
  }

  // DSH 0.2 replaced ShellExecutor.run(spec) with execute(spec) → handle.result().
  // The returned result object kept its shape (exitCode / stdout.text /
  // stderr.text), so only the call itself differs between the two generations.
  async function runShell(shell, spec) {
    if (typeof shell.execute === 'function') {
      const handle = await shell.execute(spec)
      return typeof handle?.result === 'function' ? await handle.result() : handle
    }
    if (typeof shell.run === 'function') return await shell.run(spec)
    throw new Error('DSH shell executor exposes neither run() nor execute()')
  }

  /**
   * Build the one-line command for this host's shell executor.
   * POSIX hosts run bash -c; Windows hosts run pwsh -Command. PowerShell needs
   * the call operator (&) in front of a quoted program path, otherwise the
   * line is parsed as a bare string expression and nothing executes.
   */
  function buildCommand(args) {
    const words = [CLI].concat(args)
    const win32 = process.platform === 'win32'
    const quoted = words.map(win32 ? qPwsh : q).join(' ')
    return win32 ? '& ' + quoted : quoted
  }

  async function runCli(args) {
    const shell = ctx.get('shell')
    if (shell === undefined) throw new Error('shell service unavailable — dsh shell plugin missing')
    ensureWorkdir()
    const policyService = ctx.get('sandboxPolicy')
    const policy = policyService !== undefined
      ? policyService.resolve({ mode: 'danger-full-access' })
      : undefined
    const spec = shell.resolve({
      command: buildCommand(args),
      workdir: state.workdir,
      timeoutMs: 60000,
      stdoutMaxBytes: 4000000,
      sandboxPolicy: policy,
    })
    const r = await runShell(shell, spec)
    if (r.exitCode !== 0) {
      const err = String((r.stderr && r.stderr.text) || r.stdout.text || '?').slice(0, 500)
      if (/No such file or directory|command not found|not found/.test(err)) {
        throw new Error(
          'cli-anything-aseprite harness not installed — run: pip install -e ./python ' +
          '(the package ships under python/ in this plugin)')
      }
      throw new Error('harness failed: ' + err)
    }
    const out = String((r.stdout && r.stdout.text) || '').trim()
    if (out === '') throw new Error('harness returned no output (command: ' + buildCommand(args) + ')')
    try {
      return JSON.parse(out)
    } catch (e) {
      throw new Error('harness returned non-JSON output: ' + out.slice(0, 400))
    }
  }

  async function refresh(lastOp) {
    if (!state.file) return
    const info = await runCli(['--file', state.file, '--json', 'project', 'info'])
    state.name = info.name || state.name
    const sp = String(info.size || '0x0').split('x')
    state.width = parseInt(sp[0], 10) || 0
    state.height = parseInt(sp[1], 10) || 0
    state.pixels = info.pixels || 0
    state.undo = info.undo || 0
    state.redo = info.redo || 0
    state.frames = info.frames || 0
    state.layers = info.layers || 0
    state.palette = info.palette || 0
    try {
      state.ansi = (await runCli(['--file', state.file, '--json', 'terminal'])).frame || ''
    } catch (e) { state.ansi = '' }
    state.lastOp = lastOp || state.lastOp
    if (lastOp) {
      state.log.push({ t: Date.now(), op: lastOp, pixels: state.pixels })
      if (state.log.length > 200) state.log.splice(0, state.log.length - 200)
    }
    state.version += 1
    return state.version
  }

  async function act(args, opName) {
    const r = await runCli(['--file', state.file, '--json'].concat(args))
    await refresh(opName)
    return r
  }

  function reg(name, description, parameters, execute) {
    ctx.tools.register(defineTool({
      name,
      description,
      parameters,
      output: {
        schema: { type: 'json' },
        render: (_a, v) => [{ type: 'text', text: JSON.stringify(v, null, 2) }],
      },
      async execute(args) { return execute(args) },
      timeoutMs: 90000,
    }))
  }

  const n = (v) => v === undefined ? null : parseInt(v, 10)

  // ---------------------------------------------------------------- tools
  const TOOLS = [
    ['pixelart_new', '新建像素画项目，独立文件 <name>.pxa。尺寸自由 1..1024 或 preset(icon/sprite/avatar/portrait/scene/wide/max)，palette pico8/db16/sweetie16/na16。',
      { name: { type: 'string', required: true }, width: { type: 'integer' }, height: { type: 'integer' }, preset: { type: 'string', enum: ['icon', 'sprite', 'avatar', 'portrait', 'scene', 'wide', 'max'] }, palette: { type: 'string' } },
      async (a) => {
        const f = join(state.workdir, String(a.name || 'untitled').replace(/[^a-zA-Z0-9_\u4e00-\u9fa5-]/g, '_') + '.pxa')
        ensureWorkdir()
        const c = ['--file', f, '--json', 'project', 'new', a.name || 'untitled']
        if (a.preset) c.push('--preset', a.preset)
        else { if (a.width) c.push('--width', String(a.width)); if (a.height) c.push('--height', String(a.height)) }
        if (a.palette) c.push('--palette', a.palette)
        c.push('--save', f)
        const r = await runCli(c)
        state.file = f
        await refresh('new ' + (a.name || ''))
        return { ...r, file: f, version: state.version }
      }],
    ['pixelart_open', '打开已有 .pxa 项目。', { path: { type: 'string' } },
      async (a) => {
        const p = a && a.path ? String(a.path) : join(state.workdir, 'art.pxa')
        const r = await runCli(['--file', p, '--json', 'project', 'info'])
        state.file = p
        await refresh('open')
        return { ...r, file: p, version: state.version }
      }],
    ['pixelart_workdir', '查看/更改工作区目录（作品存放处）。', { op: { type: 'string', required: true, enum: ['get', 'set'] }, dir: { type: 'string' } },
      async (a) => {
        if (a.op === 'set') { if (!a.dir) throw new Error('dir required'); state.workdir = expandHome(String(a.dir)); ensureWorkdir(); state.file = null }
        return { workdir: state.workdir, open: state.file, version: state.version }
      }],
    ['pixelart_draw', '绘制原语 pixel/line/rect/ellipse/flood/erase。颜色支持 rgb16:r,g,b（4096 色）。受对称/平铺模式影响。',
      { op: { type: 'string', required: true, enum: ['pixel', 'line', 'rect', 'ellipse', 'flood', 'erase'] }, x: { type: 'integer' }, y: { type: 'integer' }, x1: { type: 'integer' }, y1: { type: 'integer' }, w: { type: 'integer' }, h: { type: 'integer' }, color: { type: 'string' }, fill: { type: 'boolean' }, tolerance: { type: 'integer' }, radius: { type: 'integer' } },
      async (a) => {
        const c = ['--file', state.file, '--json', 'pixel']
        switch (a.op) {
          case 'pixel': c.push('set', String(n(a.x)), String(n(a.y)), a.color); break
          case 'line': c.push('line', String(n(a.x)), String(n(a.y)), String(n(a.x1)), String(n(a.y1)), a.color); break
          case 'rect': c.push('rect', String(n(a.x)), String(n(a.y)), String(n(a.w)), String(n(a.h)), a.color); if (a.fill) c.push('--fill'); break
          case 'ellipse': c.push('ellipse', String(n(a.x)), String(n(a.y)), String(n(a.w)), String(n(a.h)), a.color); if (a.fill) c.push('--fill'); break
          case 'flood': c.push('flood', String(n(a.x)), String(n(a.y)), a.color); if (a.tolerance !== undefined) c.push('--tolerance', String(n(a.tolerance))); break
          case 'erase': c.push('erase', String(n(a.x)), String(n(a.y))); if (a.radius !== undefined) c.push('--radius', String(n(a.radius))); break
        }
        const r = await act(c, 'draw ' + a.op)
        return { ...r, version: state.version }
      }],
    ['pixelart_region', '选区：fill/stroke/clear/copy/paste/move/get（Aseprite 语义）。',
      { op: { type: 'string', required: true, enum: ['fill', 'stroke', 'clear', 'copy', 'paste', 'move', 'get'] }, x: { type: 'integer', required: true }, y: { type: 'integer', required: true }, w: { type: 'integer' }, h: { type: 'integer' }, dx: { type: 'integer' }, dy: { type: 'integer' }, color: { type: 'string' } },
      async (a) => {
        const c = ['--file', state.file, '--json', 'region', a.op]
        switch (a.op) {
          case 'fill': case 'stroke': c.push(String(n(a.x)), String(n(a.y)), String(n(a.w)), String(n(a.h)), a.color); break
          case 'clear': case 'copy': c.push(String(n(a.x)), String(n(a.y)), String(n(a.w)), String(n(a.h))); break
          case 'paste': c.push(String(n(a.x)), String(n(a.y))); break
          case 'move': c.push(String(n(a.x)), String(n(a.y)), String(n(a.w)), String(n(a.h)), String(n(a.dx)), String(n(a.dy))); break
          case 'get': c.push(String(n(a.x)), String(n(a.y)), String(n(a.w)), String(n(a.h))); break
        }
        const r = await act(c, 'region ' + a.op)
        return { ...r, version: state.version }
      }],
    ['pixelart_symmetry', '对称绘制（Aseprite Symmetry）：h/v/both/off，跨命令持久。', { mode: { type: 'string', required: true, enum: ['h', 'v', 'both', 'off'] } },
      async (a) => { const r = await act(['--file', state.file, '--json', 'pixel', 'symmetry', a.mode], 'sym ' + a.mode); return { ...r, version: state.version } }],
    ['pixelart_tiled', '平铺模式 on/off（无缝纹理，跨命令持久）。', { state: { type: 'string', required: true, enum: ['on', 'off'] } },
      async (a) => { const r = await act(['--file', state.file, '--json', 'pixel', 'tiled', a.state], 'tiled ' + a.state); return { ...r, version: state.version } }],
    ['pixelart_gradient', '渐变工具（Aseprite Gradient）：两点插值，支持 rgb16；direction line/horizontal/vertical。',
      { x0: { type: 'integer', required: true }, y0: { type: 'integer', required: true }, x1: { type: 'integer', required: true }, y1: { type: 'integer', required: true }, color0: { type: 'string', required: true }, color1: { type: 'string', required: true }, direction: { type: 'string', enum: ['line', 'horizontal', 'vertical'] } },
      async (a) => {
        const c = ['--file', state.file, '--json', 'pixel', 'gradient', String(n(a.x0)), String(n(a.y0)), String(n(a.x1)), String(n(a.y1)), a.color0, a.color1]
        if (a.direction) c.push('--direction', a.direction)
        const r = await act(c, 'gradient')
        return { ...r, version: state.version }
      }],
    ['pixelart_resize', '画布尺寸：resize（anchor 九宫格 nw/n/ne/w/c/e/sw/s/se，scale 缩放内容）/ rescale（内容缩放）。',
      { op: { type: 'string', required: true, enum: ['resize', 'rescale'] }, width: { type: 'integer', required: true }, height: { type: 'integer', required: true }, anchor: { type: 'string', enum: ['nw', 'n', 'ne', 'w', 'c', 'e', 'sw', 's', 'se'] }, scale: { type: 'boolean' } },
      async (a) => {
        const c = ['--file', state.file, '--json', 'canvas', a.op, String(n(a.width)), String(n(a.height))]
        if (a.op === 'resize') { if (a.anchor) c.push('--anchor', a.anchor); if (a.scale) c.push('--scale') }
        const r = await act(c, 'canvas ' + a.op)
        return { ...r, version: state.version }
      }],
    ['pixelart_tag', '帧标签 add/list/remove（Aseprite Frame Tags）。',
      { action: { type: 'string', required: true, enum: ['add', 'list', 'remove'] }, name: { type: 'string' }, from: { type: 'integer' }, to: { type: 'integer' }, color: { type: 'string' } },
      async (a) => {
        const c = ['--file', state.file, '--json', 'frame', 'tag', a.action]
        if (a.action === 'add') { if (!a.name || a.from === undefined || a.to === undefined) throw new Error('need name/from/to'); c.push(a.name, String(n(a.from)), String(n(a.to))); if (a.color) c.push('--color', a.color) }
        else if (a.action === 'remove') { if (!a.name) throw new Error('need name'); c.push(a.name) }
        const r = await act(c, 'tag ' + a.action)
        return { ...r, version: state.version }
      }],
    ['pixelart_undo', '撤销上一步绘制。', {}, async () => { const r = await act(['--file', state.file, '--json', 'undo'], 'undo'); return { ...r, version: state.version } }],
    ['pixelart_redo', '重做上一步。', {}, async () => { const r = await act(['--file', state.file, '--json', 'redo'], 'redo'); return { ...r, version: state.version } }],
    ['pixelart_palette', '调色板 apply/add/nearest/quantize（rgb16 支持）。',
      { op: { type: 'string', required: true, enum: ['apply', 'add', 'nearest', 'quantize'] }, name: { type: 'string' }, color: { type: 'string' } },
      async (a) => {
        let c
        if (a.op === 'quantize') c = ['--file', state.file, '--json', 'palette', 'quantize']
        else if (a.op === 'nearest') c = ['--file', state.file, '--json', 'palette', 'nearest', a.color]
        else if (a.op === 'apply') c = ['--file', state.file, '--json', 'palette', 'apply', a.name]
        else c = ['--file', state.file, '--json', 'palette', 'add', a.name, a.color]
        const r = await act(c, 'palette ' + a.op)
        return { ...r, version: state.version }
      }],
    ['pixelart_layer', '图层 list/add/remove/set/property/duplicate/merge；property 支持 name/visible/opacity/reference（参考层不渲染）。',
      { op: { type: 'string', required: true, enum: ['list', 'add', 'remove', 'set', 'property', 'duplicate', 'merge'] }, name: { type: 'string' }, id: { type: 'integer' }, prop: { type: 'string', enum: ['name', 'visible', 'opacity', 'reference'] }, value: { type: 'string' } },
      async (a) => {
        let c
        switch (a.op) {
          case 'list': c = ['--file', state.file, '--json', 'layer', 'list']; break
          case 'add': c = ['--file', state.file, '--json', 'layer', 'add', a.name || 'layer']; break
          case 'remove': c = ['--file', state.file, '--json', 'layer', 'remove', '--id', String(n(a.id))]; break
          case 'set': c = ['--file', state.file, '--json', 'layer', 'set', String(n(a.id))]; break
          case 'property': c = ['--file', state.file, '--json', 'layer', 'property', String(n(a.id)), a.prop, String(a.value)]; break
          case 'duplicate': c = ['--file', state.file, '--json', 'layer', 'duplicate', '--id', String(n(a.id))]; break
          case 'merge': c = ['--file', state.file, '--json', 'layer', 'merge']; break
        }
        const r = await act(c, 'layer ' + a.op)
        return { ...r, version: state.version }
      }],
    ['pixelart_frame', '帧 list/add/set/remove/duration/duplicate。',
      { op: { type: 'string', required: true, enum: ['list', 'add', 'set', 'remove', 'duration', 'duplicate'] }, id: { type: 'integer' }, duration: { type: 'integer' }, blank: { type: 'boolean' } },
      async (a) => {
        let c
        switch (a.op) {
          case 'list': c = ['--file', state.file, '--json', 'frame', 'list']; break
          case 'add': c = ['--file', state.file, '--json', 'frame', 'add']; if (a.duration) c.push('--duration', String(n(a.duration))); if (a.blank) c.push('--blank'); break
          case 'set': c = ['--file', state.file, '--json', 'frame', 'set', String(n(a.id))]; break
          case 'remove': c = ['--file', state.file, '--json', 'frame', 'remove', '--id', String(n(a.id))]; break
          case 'duration': c = ['--file', state.file, '--json', 'frame', 'duration', String(n(a.id)), String(n(a.duration))]; break
          case 'duplicate': c = ['--file', state.file, '--json', 'frame', 'duplicate', '--id', String(n(a.id))]; break
        }
        const r = await act(c, 'frame ' + a.op)
        return { ...r, version: state.version }
      }],
    ['pixelart_transform', '整层变换 flip-h/flip-v/rotate-90/rotate-180/rotate-270。',
      { op: { type: 'string', required: true, enum: ['flip-h', 'flip-v', 'rotate-90', 'rotate-180', 'rotate-270'] } },
      async (a) => { const r = await act(['--file', state.file, '--json', 'transform', 'apply', a.op], 'transform ' + a.op); return { ...r, version: state.version } }],
    ['pixelart_export', '导出 png/gif/aseprite/spritesheet/pngs 序列。',
      { format: { type: 'string', required: true, enum: ['png', 'gif', 'aseprite', 'spritesheet', 'pngs'] }, path: { type: 'string' }, scale: { type: 'integer' }, filename: { type: 'string' } },
      async (a) => {
        let p
        if (a.format === 'pngs') p = a.path || join(state.workdir, 'frames')
        else { const ext = a.format === 'spritesheet' ? 'png' : a.format; p = a.path || join(state.workdir, 'art.' + ext) }
        const c = ['--file', state.file, '--json', 'export', a.format === 'pngs' ? 'pngs' : a.format, p]
        if (a.format === 'pngs' && a.filename) c.push('--filename', a.filename)
        if (a.scale) c.push('--scale', String(a.scale))
        const r = await act(c, 'export ' + a.format)
        return { ...r, version: state.version }
      }],
    ['pixelart_terminal', '获取当前画布的 ANSI 终端帧（AI 每步绘制后人类可实时观看）。', {},
      async () => {
        if (!state.file) return { error: 'no project yet' }
        const r = await runCli(['--file', state.file, '--json', 'terminal'])
        return { frame: r.frame, width: state.width, height: state.height, version: state.version }
      }],
    ['pixelart_info', '项目状态（尺寸/帧/图层/像素/undo/操作日志）。', {},
      async () => state.file
        ? { open: true, name: state.name, workdir: state.workdir, size: state.width + 'x' + state.height,
            frames: state.frames, layers: state.layers, palette: state.palette, pixels: state.pixels,
            undo: state.undo, redo: state.redo, dirty: state.dirty, lastOp: state.lastOp,
            log: state.log.slice(-12), version: state.version }
        : { open: false, error: 'use pixelart_new first' }],
  ]
  for (const [name, desc, params, exec] of TOOLS) reg(name, desc, params, exec)

  // auto-resume the default project on start
  ctx.timeout(async () => {
    try {
      const f = join(state.workdir, 'art.pxa')
      const fs = ctx.get('fs')
      if (fs === undefined || typeof fs.lstat !== 'function') return
      // lstat() takes a plain path, so resuming needs no extra service and no
      // directory that must already exist.
      const info = await fs.lstat(f)
      if (info !== undefined) {
        state.file = f
        await refresh('resumed')
      }
    } catch (e) { /* no project yet */ }
  }, 300)
}
