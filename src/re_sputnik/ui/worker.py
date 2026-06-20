# SPDX-License-Identifier: GPL-2.0-only
"""Run blocking work (SSH, detection) off the Tk main thread — safely.

Tk is single-threaded AND its ``after`` is not safe to call from other threads.
So background results are pushed onto a thread-safe queue, and a poll loop owned
by the Tk main thread (installed once via :func:`install`) drains the queue and
runs the callbacks on the correct thread. This keeps every UI update on the main
thread while SSH runs in the background.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Optional

OnDone = Callable[[Any], None]
OnError = Callable[[BaseException], None]

_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
_installed = False


def install(root: Any, interval_ms: int = 50) -> None:
    """Install the main-thread poll loop on the Tk root. Call once at startup."""
    global _installed

    def pump() -> None:
        while True:
            try:
                callback = _queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:  # noqa: BLE001 — never let a callback kill the loop
                import traceback

                traceback.print_exc()
        root.after(interval_ms, pump)

    root.after(interval_ms, pump)
    _installed = True


def post_to(widget: Any, fn: Callable[[], None]) -> None:
    """Run ``fn`` on the Tk thread (e.g. a progress update from a worker thread)."""

    def cb() -> None:
        try:
            if widget.winfo_exists():
                fn()
        except Exception:  # noqa: BLE001 — destroyed widget / late callback
            pass

    _queue.put(cb)


def run_async(
    widget: Any,
    fn: Callable[[], Any],
    on_done: OnDone,
    on_error: Optional[OnError] = None,
) -> None:
    """Execute ``fn()`` in a daemon thread; deliver result on the Tk thread.

    ``widget`` is accepted for call-site clarity but results are marshalled via
    the shared queue, not the widget, so this is safe from any thread.
    """

    def alive() -> bool:
        # Don't deliver to a widget the user already navigated away from.
        try:
            return bool(widget.winfo_exists())
        except Exception:  # noqa: BLE001 — destroyed/invalid widget
            return False

    def worker() -> None:
        try:
            result = fn()
        except BaseException as exc:  # noqa: BLE001 — forward every failure
            if on_error is not None:
                _queue.put(lambda exc=exc: on_error(exc) if alive() else None)
            return
        _queue.put(lambda: on_done(result) if alive() else None)

    threading.Thread(target=worker, daemon=True).start()
