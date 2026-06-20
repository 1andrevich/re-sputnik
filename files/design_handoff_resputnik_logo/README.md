# Handoff: Re:Sputnik — Logo & App Icon

## Overview
The brand mark for **Re:Sputnik**, a desktop app (Windows, Python/customtkinter) that configures a home router as a secure proxy/VPN gateway over SSH. The mark is the **1957 Sputnik satellite** — polished sphere leading, four antennas swept back — climbing over the curve of the **Earth**, with a faint **signal beam** linking the satellite down to the surface. It carries three ideas at once: the iconic satellite, technological freedom (the climb over the horizon), and people connected (the downlink signal).

This is the **final, approved direction** (internally "Sputnik '57"). Earlier exploration directions (Companions in Orbit, Open Signal, Constellation) were dropped.

## About the design files
The files in `assets/` are **production-ready vector + raster exports**, not a UI to reverse-engineer:
- The **SVGs are the source of truth** — hand-authored, flat, on-palette, white-label friendly.
- The **PNGs and `.ico`** are generated *from* `logo_mark.svg` and can be regenerated at any time (see *Regenerating rasters*).
- `Re-Sputnik Logo Exploration.dc.html` is the **design reference / review page** showing the mark, monochrome, size tests and the lockup. It is an HTML prototype — use it to see intended appearance, not as code to ship.

Your task is to **wire these assets into the app** (window/taskbar icon, About screen, installer) using the codebase's existing conventions — not to rebuild the artwork.

## Fidelity
**High-fidelity.** Final colors, geometry and proportions. Use the supplied SVG/PNG/ICO directly; match the exact hex values below if you ever re-render.

## Assets in this bundle
| File | Purpose |
|------|---------|
| `assets/logo_mark.svg` | Master app-icon mark, 256×256 viewBox, dark rounded plate. **Source of truth.** |
| `assets/logo_mark_mono.svg` | Single-colour glyph (sphere + swept antennas), `currentColor`. Favicons, stamps, dark/light surfaces. |
| `assets/logo_wordmark.svg` | Horizontal lockup: mark + `Re:Sputnik` on a dark pill (560×150). |
| `assets/png/icon_{16,32,48,64,128,256}.png` | Rasterized app icon at standard sizes. |
| `assets/icon.ico` | Windows multi-resolution icon (PNG-compressed frames: 16/32/48/256). Use for the window + taskbar + executable icon. |
| `Re-Sputnik Logo Exploration.dc.html` | Visual reference page (not production code). |

## Design tokens

### Colors
| Role | Hex |
|------|-----|
| App-icon plate (vertical gradient, top → bottom) | `#10131A` → `#1B2230` |
| Sputnik sphere / accent (diagonal gradient) | `#3B82F6` → `#38BDF8` |
| Earth body (vertical gradient) | `#22507A` → `#12233A` |
| Earth atmosphere rim / signal glow | `#93DFFA`, `#38BDF8` (low opacity) |
| Antennas, antenna tips, linework | `#E7E8EA` |
| Sphere specular highlight | `#FFFFFF` @ 0.55 |
| Wordmark `Re:` | `#38BDF8` (on dark) / `#0E9BD6` (on light) |
| Wordmark `Sputnik` | `#E7E8EA` (on dark) / `#1B2230` (on light) |

### Geometry (all in the 256×256 mark coordinate space)
- **Plate:** `rect 0,0,256,256`, corner radius `rx=56`.
- **Earth:** circle `cx=128 cy=426 r=240` (only the top limb shows ≈ y184↓), fill `earthg`; atmosphere = same circle stroked `#93DFFA` @0.55, width 2.5; faint outer glow ring `r=248` stroke `#38BDF8` @0.14, width 8. Two low-opacity `#356F9C` ellipses hint landmass.
- **Sphere (Sputnik body):** `cx=102 cy=105 r=29`, fill `sat`; inner edge stroke `#0B0E14` @0.25 width 2; highlight circle `cx=92 cy=95 r=7` white @0.55.
- **Antennas:** 4 lines from the sphere swept to the right, `stroke #E7E8EA`, width 4, round caps; tips end in `r=3.6` filled dots at `(208,60) (222,98) (218,142) (190,178)`.
- **Signal beam:** quadratic path `M116,124 Q130,158 150,188`, `#38BDF8` @0.3 width 1.6; three travelling pulse dots fading downward; ground node `cx=150 cy=188 r=3.6` solid `#38BDF8` with a `r=6.5` ring @0.4.
- **Glow:** radial `glow` circle `cx=106 cy=104 r=82` behind the satellite.

### Typography (wordmark)
- Family: **Inter**, fallback `'Segoe UI', Arial, sans-serif` (system-safe; matches the app's customtkinter UI).
- `Re:Sputnik` — weight **700**, size 56 (at 560-wide lockup), letter-spacing ≈ −1.
- No tagline (the previous Russian tagline «маршрутизатор на связи» was removed at the client's request).

### Radii used in the review UI
- Plate corner at 256: `56`. Scaled equivalents: 48px→11, 32px→7, 16px→4.

## Usage rules
- **Minimum size:** legible to **16px** (taskbar). Below 32px the antennas/signal read as a soft glow — that's expected; don't add detail.
- **Clear space:** keep padding ≥ ~10% of icon size around the plate.
- **Don't:** recolor the sphere outside the blue→cyan family, rotate the mark, add the old horror/ruined-city aesthetic, or place the light linework on a light background (use `logo_mark_mono.svg` for that).
- **Monochrome:** `logo_mark_mono.svg` inherits `currentColor` — set `color:` (or `fill`) on the element. It ships with a default of `#1B2230`.

## White-label / theming
The app has a white-label ambition (VPN providers reskinning it). The mark is built for that:
- The **accent gradient** (`sat`: `#3B82F6`→`#38BDF8`) is the single swappable hue family. Swap both stops in `logo_mark.svg` (sphere) and `logo_wordmark.svg` (`Re:`) to reskin. Keep the same lightness/chroma relationship.
- The **plate**, **Earth**, and **linework** are neutral and can stay fixed across skins.
- Keep the `Re:` prefix in any wordmark (product-family marker for Re:HomeProxy, Re:filter, …).
- Recommended implementation: expose `--accent-from` / `--accent-to` (or equivalent Python theme constants) and template the two gradient stops at build time.

## Regenerating rasters
PNGs and the `.ico` are derived from `logo_mark.svg`. To regenerate in the app's Python toolchain (Pillow + a rasterizer such as `cairosvg`):
1. Render `logo_mark.svg` to PNG at 16, 32, 48, 64, 128, 256.
2. Pack 16/32/48/256 into a single `.ico` (`Pillow`: `img.save('icon.ico', sizes=[(16,16),(32,32),(48,48),(256,256)])`, or assemble PNG-compressed frames as in this bundle).
The provided `icon.ico` already contains PNG-compressed 16/32/48/256 frames (Vista+).

## Integration notes (this codebase)
- **Window / taskbar icon:** point customtkinter / Tk `iconbitmap('icon.ico')` (Windows) at `assets/icon.ico`; for the in-app logo use a PNG via `CTkImage` (e.g. `icon_64.png` or `icon_128.png` for HiDPI).
- **About / splash:** use `logo_wordmark.svg` (or a PNG render of it) on a dark surface.
- **Installer:** `icon.ico` for the executable and shortcut.

## Files in the wider project (reference only)
- `Re-Sputnik Logo Exploration.dc.html` — the review page (also copied into this bundle).
- Original client brief: `uploads/LOGO_BRIEF.md` (in the design project).
