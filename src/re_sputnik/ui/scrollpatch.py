# SPDX-License-Identifier: GPL-2.0-only
"""Make the mouse wheel scroll the page under the pointer — reliably.

Three stock customtkinter problems this fixes:

1. **Wheel decided by focus, not the pointer.** customtkinter binds the wheel
   with ``bind_all`` and picks which scrollable reacts from ``event.widget``. On
   Windows the ``<MouseWheel>`` event is delivered to the *focused* widget, so a
   page only scrolls if focus happens to sit inside it. We instead use the widget
   genuinely **under the pointer** (``winfo_containing``).

2. **No scrolling while hovering any widget.** customtkinter draws every rounded
   widget (buttons, cards, frames) on an internal ``Canvas``. A naive "walk up
   until the first Canvas" treats those as scroll boundaries, so the page only
   scrolled over its bare background and went dead over any card/button. We
   instead resolve the owning scrollable by its nearest **CTkScrollableFrame**
   ancestor — internal widget canvases are ignored, and nested lists still scroll
   independently (innermost wins).

3. **Sluggish wheel on Windows.** customtkinter uses ``yscrollincrement=1`` and
   ``delta/6`` (~20 px/notch). We scroll a more natural ~60 px/notch there.

Idempotent; ``apply()`` is called once before any scrollable frame is built.
"""
from __future__ import annotations

import sys

import customtkinter as ctk

_FLAG = "_resputnik_pointer_wheel"


def apply() -> None:
    if getattr(ctk.CTkScrollableFrame, _FLAG, False):
        return

    def _mouse_wheel_all(self, event):  # type: ignore[no-untyped-def]
        canvas = getattr(self, "_parent_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return  # this scrollable was destroyed; its bind_all handler lingers
        # The widget under the POINTER — not event.widget, which on Windows is the
        # focused widget and makes scrolling depend on what was last clicked.
        try:
            target = self.winfo_containing(event.x_root, event.y_root)
        except Exception:  # noqa: BLE001 — pointer off-screen / between toplevels
            return
        if target is None:
            return
        # Resolve which scrollable owns the pointer: walk up to the NEAREST
        # CTkScrollableFrame ancestor. We must NOT stop at "a Canvas" — customtkinter
        # renders every rounded widget on its own internal Canvas, so that would
        # kill scrolling over buttons/cards. Only a real scrollable is a boundary,
        # and the innermost one wins (nested lists scroll independently).
        w = target
        while w is not None:
            if isinstance(w, ctk.CTkScrollableFrame):
                break
            w = getattr(w, "master", None)
        if w is not self:
            return  # pointer is over another scrollable (or none)
        horizontal = getattr(self, "_shift_pressed", False)
        view = canvas.xview() if horizontal else canvas.yview()
        if view == (0.0, 1.0):
            return  # nothing to scroll — don't fight a non-overflowing view
        if sys.platform == "darwin":
            step = -event.delta                      # increment=8; ctk's own math
        elif sys.platform.startswith("win"):
            step = -int(event.delta / 2)             # increment=1 px; ~60 px/notch
        else:
            step = -event.delta                      # X11 (Button-4/5 not handled)
        (canvas.xview if horizontal else canvas.yview)("scroll", step, "units")

    ctk.CTkScrollableFrame._mouse_wheel_all = _mouse_wheel_all
    setattr(ctk.CTkScrollableFrame, _FLAG, True)
