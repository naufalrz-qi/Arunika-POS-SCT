# Claude Code — MCP, Plugin & Skill Aktif

Snapshot tools/plugin yang terpasang di Claude Code (`~/.claude/settings.json`) saat mengerjakan proyek ini. Kolom **Sesi ini** = benar-benar dipakai saat kerja Arunika POS.

## MCP Servers

Server MCP yang tersedia (tool prefix `mcp__<server>__…`).

| Server | Tool prefix | Fungsi | Sumber | Sesi ini |
|---|---|---|---|---|
| context7 | `mcp__context7__` | Fetch dokumentasi library/framework terbaru (resolve-library-id, query-docs) | MCP standalone + rule global | ✅ (docs Inertia defer) |
| chrome-devtools | `mcp__plugin_ecc_chrome-devtools__` | Otomasi browser: navigate, screenshot, click, network, console, perf, lighthouse | plugin `ecc` | ✅ (smoke test UI, cek CORS/network) |
| logfire | `mcp__plugin_logfire_logfire__` | Observability Pydantic Logfire: query telemetry, dashboard, alert | plugin `logfire` | — |
| prisma | `mcp__plugin_prisma_Prisma-Local__` | Prisma ORM: Studio, migrate-dev, migrate-reset, migrate-status | plugin `prisma` | — |
| Google Drive | `mcp__claude_ai_Google_Drive__` | Baca/cari/tulis file Google Drive | integrasi claude.ai | — |
| ide | `mcp__ide__` | Integrasi VS Code: executeCode (Jupyter), getDiagnostics | IDE extension | — |

## Plugin terpasang (`enabledPlugins`)

| Plugin | Marketplace | Fungsi | Sesi ini |
|---|---|---|---|
| `ponytail` | ponytail (DietrichGebert/ponytail) | Mode "lazy senior dev": kode minimal, anti over-engineering | ✅ (aktif full) |
| `caveman` | caveman (juliusbrussee/caveman) | Mode output ringkas + agent `cavecrew-*` (builder/investigator/reviewer) | ✅ (aktif full) |
| `superpowers` | superpowers-dev (obra/superpowers) | Process skills: brainstorming, systematic-debugging, TDD, verification | ✅ (systematic-debugging, brainstorming) |
| `frontend-design` | claude-plugins-official | Skill desain UI distinctive (palette/tipografi/layout opinionated) | ✅ (redesign nav) |
| `impeccable` | impeccable (pbakaus/impeccable) | Hook cek kualitas desain tiap edit `.vue` + manual-edit-applier | ✅ (hook jalan otomatis) |
| `ecc` | ecc (affaan-m/ecc) | Suite besar: MCP chrome-devtools + banyak agent reviewer (`ecc:*` python/vue/django/security/…) | ✅ (chrome-devtools) |
| `typescript-lsp` | claude-plugins-official | Language server TypeScript (diagnostics, definisi) | — |
| `qdrant-skills` | claude-plugins-official | Skill Qdrant vector DB | — |
| `logfire` | claude-plugins-official | MCP Logfire (lihat tabel MCP) | — |
| `prisma` | claude-plugins-official | MCP Prisma (lihat tabel MCP) | — |
| `supabase` | claude-plugins-official | Integrasi Supabase | — |
| `ui-ux-pro-max` | ui-ux-pro-max-skill | Skill UI/UX | — |
| `andrej-karpathy-skills` | karpathy-skills | Kumpulan skill ala Karpathy | — |
| `claude-hud` | claude-hud | Status line HUD (dipakai di `statusLine`) | ✅ (status line) |

## Skill dipakai sesi ini

- **superpowers:systematic-debugging** — debug "UI tak muncul via Tailscale" (root cause CORS, bukan tebak).
- **superpowers:brainstorming** — sebelum plan mode.
- **frontend-design** — rombak navbar+sidebar (tema RX-78-2).
- **impeccable** — hook otomatis scan tiap edit `.vue` (design-quality).

## Mode aktif

- **Caveman** (full) — output ringkas, buang filler. Toggle: `/caveman lite|full|ultra`, `stop caveman`.
- **Ponytail** (full) — solusi termalas yang jalan, anti over-engineering. Toggle: `/ponytail lite|full|ultra`, `stop ponytail`.

## Rule & sistem global

- **context7.md** (`~/.claude/rules/`) — wajib pakai Context7 MCP untuk pertanyaan library/framework/API.
- **Memory** (`~/.claude/projects/D--Project-ArunikaPOSDjango/memory/`) — memori file-based per proyek, index di `MEMORY.md`.

## Marketplace terdaftar

`claude-plugins-official` (anthropics), `ponytail`, `superpowers-dev` (obra), `caveman` (juliusbrussee), `ecc` (affaan-m), `impeccable` (pbakaus), `ui-ux-pro-max-skill`, `karpathy-skills`, `claude-hud`.

---
*Sumber: `~/.claude/settings.json` → `enabledPlugins`. MCP diturunkan dari plugin + integrasi claude.ai/IDE. Regenerate bila plugin berubah.*
