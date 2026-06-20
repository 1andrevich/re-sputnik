# Building Re:Sputnik on macOS (Apple Silicon)

Produces `dist/Re-Sputnik.app`. Tested target: macOS 11+ on Apple Silicon (arm64).
The same `re_sputnik.spec` builds the Windows `.exe` — it branches on the platform.

> ⚠️ The macOS path is **not yet verified on real hardware** (it was written on
> Windows). The build should work; the one thing to actually test by hand is the
> clipboard under a non-Latin keyboard layout (see step 7).

---

## 1. Prerequisites

**Use a Python with a working Tcl/Tk** — this is the #1 macOS gotcha. The system
`python3` (from Xcode) has a broken/deprecated Tk and the app won't render.

Pick ONE:

- **python.org installer (recommended)** — download Python **3.13** "macOS 64-bit
  universal2 installer" from <https://www.python.org/downloads/macos/> and install.
  It bundles a known-good Tk.
- **Homebrew:** `brew install python@3.13 python-tk@3.13`

Also install Xcode command-line tools if you don't have them (provides git etc.;
`sips`/`iconutil` for the icon are already built into macOS):

```sh
xcode-select --install
```

Verify Tk works before going further:

```sh
python3.13 -m tkinter      # a small test window should appear
```

---

## 2. Get the code

```sh
git clone https://github.com/1andrevich/re-sputnik.git
cd re-sputnik
```

---

## 3. Virtual env + dependencies

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install ".[build]"          # runtime deps + resvg-py + pyinstaller
```

If `resvg-py` has no arm64 wheel for your Python and the install fails, install
without the icon rasterizer and rely on committed PNGs:

```sh
pip install . pyinstaller
```

---

## 4. Bake icons (best-effort)

Only needed if the PNGs aren't already committed; harmless to run twice. Skip if
`resvg-py` wasn't installed.

```sh
python scripts/render_icons.py
python scripts/gen_icons.py
```

---

## 5. Generate the .app icon (.icns) — optional

The build works without it (the app sets its icon at runtime too), but this gives
the bundle a proper Dock/Finder icon:

```sh
ICONDIR=src/re_sputnik/resources/branding
mkdir -p icon.iconset
for s in 16 32 64 128 256 512; do
  sips -z $s $s "$ICONDIR/icon_256.png" --out "icon.iconset/icon_${s}x${s}.png"
  sips -z $((s*2)) $((s*2)) "$ICONDIR/icon_256.png" --out "icon.iconset/icon_${s}x${s}@2x.png"
done
iconutil -c icns icon.iconset -o "$ICONDIR/icon.icns"
```

---

## 6. Build

```sh
pyinstaller --clean --noconfirm re_sputnik.spec
```

Output: **`dist/Re-Sputnik.app`**.

---

## 7. Run & test

```sh
open dist/Re-Sputnik.app
```

If it doesn't open, run the inner binary directly to see the traceback:

```sh
./dist/Re-Sputnik.app/Contents/MacOS/Re-Sputnik
```

**Gatekeeper (unsigned build):** the first launch may be blocked ("cannot be
opened because the developer cannot be verified"). Either right-click the `.app`
→ **Open** → **Open**, or strip the quarantine flag:

```sh
xattr -dr com.apple.quarantine dist/Re-Sputnik.app
```

**The one thing to verify by hand — clipboard under a Russian (non-Latin) layout:**
switch the macOS input source to Russian, open any text field in the app, and test
**⌘C / ⌘V / ⌘X / ⌘A**. The mac handler dispatches by hardware keycode (C=8, V=9,
X=7, A=0) bound to `<Command-KeyPress>` — if any key does nothing, tell me the
keycode (we can log `event.keycode`) and I'll fix the map.

---

## 8. Common issues

| Symptom | Cause / fix |
|---|---|
| Blank/garbled window, `_tkinter` error | Python has no working Tk → use python.org 3.13 or `python-tk@3.13` (step 1). |
| `resvg-py` install fails | No arm64 wheel for your Python → `pip install . pyinstaller` and rely on committed PNGs (step 3). |
| Icons missing in UI | `resources/icons_line` PNGs weren't committed/baked → run step 4. |
| `keyring` can't store secrets | Should "just work" via macOS Keychain; if prompted, allow access. The spec bundles `keyring.backends.macOS`. |
| App is huge / slow first launch | Normal for a bundled Python app; not onefile on macOS (it's a proper `.app` dir). |

---

## Notes

- **Signing / notarization** is not done here — that needs an Apple Developer ID
  ($99/yr). For personal use the quarantine-strip above is enough. The CI workflow
  (`.github/workflows/build.yml`) has placeholders for where signing plugs in.
- CI builds this same `.app` automatically on `macos-14` runners; this doc is for
  building locally on your own Mac.
