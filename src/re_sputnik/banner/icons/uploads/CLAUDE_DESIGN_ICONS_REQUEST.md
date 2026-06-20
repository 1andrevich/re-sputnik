# Re:Sputnik — Icon design request (line-icon set, batch 2)

**To:** Claude Design
**From:** Re:Sputnik app (desktop, Python + customtkinter, "Orbit Cyan" dark theme)
**Deliverable:** 10 new single-color line icons as individual `.svg` files, drawn to match the existing batch-1 set exactly.

---

## 1. What this is

Re:Sputnik already ships a 15-icon line set (batch 1). They live as SVG masters and are
rasterized to PNG at build time; the app draws them in small "chips" next to section
titles, in the left nav of the settings shell, and at large size on the mode-select cards.

This request is **batch 2**: the Advanced settings area and a few cards are still on emoji
fallback. I need icons for those, in the **same visual language** as batch 1 so they sit
together without looking foreign.

**The single most important rule: match batch 1.** Same grid, same stroke, same weight,
same corner feel. When in doubt, trace the existing icons' conventions rather than a
generic icon pack.

---

## 2. Exact technical spec (non-negotiable — copy from batch 1)

Every icon is one `<svg>` with this exact envelope:

```
viewBox="0 0 24 24"  width="24"  height="24"
fill="none"
stroke="#38BDF8"            ← Orbit-Cyan accent, single color, no other colors
stroke-width="1.7"
stroke-linecap="round"
stroke-linejoin="round"
```

- **Outline only.** No fills, no solid shapes, no gradients, no second color.
- **One stroke weight (1.7) everywhere.** Don't mix thick/thin lines.
- **Optical padding:** keep artwork roughly within a 2–20 box inside the 24×24 frame
  (≈2px breathing room each side), like the references below.
- **Geometric / Feather-Lucide family.** Rounded joins, clean arcs, minimal nodes.
  Friendly but technical — this is networking software, not a kids' app.
- **Legibility at 16px is mandatory.** The icons render into a 30×30 chip at **16px**
  (see §4). Avoid detail that collapses at that size — ≤ ~6 path elements is a good ceiling,
  matching the references.
- Output: **flat SVG, no `<style>`, no classes, no `id`s, no transforms if avoidable.**
  Inline the geometry exactly like the references (the build renderer is resvg — keep it simple).

---

## 3. Reference icons (this is the house style — match it)

These two are shipped batch-1 masters. New icons must look like siblings of these.

**`nodes.svg`** (three linked dots — used for "Узлы / nodes"):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#38BDF8" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="7" r="2.2"/><circle cx="18" cy="9" r="2.2"/><circle cx="11" cy="17" r="2.2"/><path d="M8.1 7.7 15.9 8.6"/><path d="M7.2 9 10 15.1"/><path d="M16.8 10.8 12.6 15.4"/></svg>
```

**`package.svg`** (parcel/box — used for "Ядро / core"):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#38BDF8" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4v9l-8 4-8-4V7z"/><path d="M4 7l8 4 8-4"/><path d="M12 11v9"/></svg>
```

The full batch-1 set, for tone reference (look at the actual files — same folder as your output):

```
connect  file  finalize  globe  key  link  lock
mode_advanced  mode_guided  mode_preinstall  nodes  package  resource  verify  wifi
```

→ source files: `src/re_sputnik/banner/assets/icons/*.svg`

---

## 4. Where these are used (so the metaphors land)

- **Section-header chips:** a 16px icon centered in a 30×30 rounded chip,
  background `#163142`, on a `#1B2230` card. Title text sits to the right.
- **Settings left-nav:** same family, small.
- They must read against a **dark** surface (cyan-on-dark). Test mentally at 16px.

Palette context (don't put colors in the SVG beyond the cyan stroke — this is just so you
know the surroundings):

| token | hex |
|---|---|
| accent (stroke) | `#38BDF8` |
| chip background | `#163142` |
| card surface | `#1B2230` |
| app background | `#10131A` |
| text | `#E7E8EA` |

---

## 5. The 10 icons to design

Each row: **filename** · the Russian label it sits next to · what it means · a suggested
motif (you may improve on it, but keep the meaning unambiguous and distinct from siblings).

| filename | label (RU) | meaning | suggested motif |
|---|---|---|---|
| `overview.svg` | Обзор | Dashboard / live router status & metrics | a gauge/speedometer arc, **or** a 2×2 dashboard-tile layout. Must be clearly distinct from `package`. |
| `rules.svg` | Правила | Routing rules — which traffic goes proxy vs. direct | a signpost / forked route / two diverging arrows from one node. (Routing, not "list".) |
| `access.svg` | Контроль доступа | Which LAN devices are allowed through the proxy | a shield with a person, **or** an ID/access card. Distinct from `security`'s plain shield. |
| `byedpi.svg` | ByeDPI | Local DPI-bypass engine (defeats ISP deep-packet inspection) | a shield with a gap/arrow passing **through** it, **or** a wall with a breach + arrow. Conveys "punching through a block." |
| `strategy.svg` | Тест стратегии | Testing/benchmarking a bypass strategy | a target/bullseye with a check, **or** a lab flask, **or** a gauge with a pointer. Pairs with `byedpi`. |
| `diagnostics.svg` | Диагностика | Connectivity health checks & logs | a pulse/activity line, **or** a stethoscope. (Not a generic gauge — keep distinct from `overview`.) |
| `security.svg` | Безопасность | Router hardening (root password, exposure) | a clean shield (optionally a check inside). The "base" shield — `access` is the shield-with-person variant. |
| `traffic.svg` | Особый трафик | Special traffic categories bound to specific nodes | two interleaving/criss-cross arrows (shuffle-like), or directional flow arrows. |
| `alert.svg` | Конфликт адресов | Warning state (e.g., LAN subnet collision) | a triangle with an exclamation. The one icon that may *also* be tinted warning-amber by the app, so keep it a clean, symmetric triangle. |
| `info.svg` | О программе | About / app info | a circled "i", or a circled "i" with a small orbit dot to echo the Sputnik mark (subtle — only if it stays readable at 16px). |

**Distinctness matters:** `overview` vs `diagnostics` vs `gauge`, and `security` vs
`access` vs `byedpi`, are the easy-to-confuse clusters. Please make each unmistakable at a
glance and at 16px.

---

## 6. Output & naming

- One file per icon, named exactly as in the table (`overview.svg`, `rules.svg`, …).
- Drop them into: `src/re_sputnik/banner/assets/icons/`
- The build step rasterizes each SVG to a 96px PNG (`scripts/render_icons.py`, via resvg)
  into `src/re_sputnik/resources/icons_line/`; the app's `CTkImage` then downscales to
  16 / 20 / 44 / 64px. So: **render crisp at small sizes, but author at the 24px grid.**
- No accompanying CSS/JSON/manifest needed — just the SVGs.

---

## 7. Acceptance checklist

- [ ] All 10 files present, correctly named.
- [ ] Each opens to the exact envelope in §2 (`viewBox 0 0 24 24`, `stroke #38BDF8`,
      `stroke-width 1.7`, round caps/joins, `fill="none"`).
- [ ] No fills, no extra colors, no `<style>`/classes/ids.
- [ ] Sits convincingly next to `nodes.svg` and `package.svg` (same weight & rhythm).
- [ ] Reads clearly at 16px on a dark surface.
- [ ] The confusable clusters (overview/diagnostics, security/access/byedpi) are distinct.

---

_Generated as a design handoff brief; the existing batch-1 masters and `render_icons.py`
are the ground truth for style and pipeline._
