"""
UTF-8 CONSOLE
=============
FILE: core/console_safe.py

Makes stdout, stderr and logging survive a non-ASCII character on
Windows. Import it before anything that logs.

WHAT WENT WRONG WITHOUT IT

Python on Windows gives stdout the console's legacy code page, cp1252,
which cannot encode any emoji. This codebase has 476 print/log lines
containing them. Any one of those raises UnicodeEncodeError at the
moment it is written -- not a garbled character, an exception.

That turned decorative logging into control flow:

  * ai/ai_gnn imports emit a "brain" emoji at module level. The import
    therefore raised, core/asset_analysis_gnn.py caught it as
    `except Exception` -> "GNN initialization failed", and
    GNN_AVAILABLE stayed False. The graph neural network contributed to
    ZERO of 4240 replayed decisions and reported gnn active% 0.0 with
    no variance -- indistinguishable in every report from a component
    that ran and had nothing to say.

  * core/run_replay.py finished every single run by raising
    UnicodeEncodeError on its final `print(report)`, after the work was
    done and the files were written. Every replay in this project
    "failed" at the last line.

Both look like separate, deep problems. They are one missing encoding.

WHY errors="replace" AND NOT strict

A log line is never worth killing a trading process for. With replace,
an unencodable glyph becomes "?" and execution continues -- the message
is degraded, the program is not. That is the correct trade for output
that exists to describe work rather than to do it.

This is idempotent and safe to import repeatedly.
"""

import io
import logging
import sys


def _reconfigure(stream_name: str) -> bool:
    """Point one std stream at UTF-8. True if it now speaks UTF-8."""
    stream = getattr(sys, stream_name, None)
    if stream is None:
        return False

    # Python 3.7+: the stream can retarget itself in place, which keeps
    # any reference already captured elsewhere valid.
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
            return True
        except (ValueError, AttributeError, OSError):
            pass

    # Fallback for a stream that cannot retarget (a pipe wrapper, a
    # captured buffer under a test runner). Wrap its binary buffer.
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        try:
            setattr(sys, stream_name,
                    io.TextIOWrapper(buffer, encoding="utf-8",
                                     errors="replace", line_buffering=True))
            return True
        except (ValueError, AttributeError, OSError):
            pass
    return False


def _fix_logging_handlers() -> int:
    """
    Retarget handlers already attached to the root logger.

    A handler created before this module ran captured the old encoding,
    so fixing sys.stderr alone leaves it raising. Counts what it fixed.
    """
    fixed = 0
    for handler in list(logging.getLogger().handlers):
        stream = getattr(handler, "stream", None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
                fixed += 1
            except (ValueError, AttributeError, OSError):
                pass
    return fixed


def disable_quick_edit() -> bool:
    """
    Stop a mouse click in the console window from freezing the process.

    With QuickEdit mode on, a click inside a Windows console starts a text
    selection and PAUSES the console: every write to it blocks until the
    selection ends (Enter or Esc). A service that prints from several threads
    then stops as a whole. Measured on the live monitor on 2026-09-17: every
    thread, the once-a-minute health update included, went silent for 38 to
    165 minutes at a time (05:29-06:07, 06:12-07:56, 08:11-10:56, 11:26-12:48,
    13:05-14:23) while the machine was awake, so nothing was analysed and no
    trade could open. Clearing ENABLE_QUICK_EDIT_MODE keeps the window and its
    output; only click-to-select goes.

    False (and no change) when the process has no console: a pipe, a test
    runner, a non-Windows host. Never raises.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetStdHandle.argtypes = (wintypes.DWORD,)
        kernel32.GetConsoleMode.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.SetConsoleMode.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        handle = kernel32.GetStdHandle(wintypes.DWORD(-10 & 0xFFFFFFFF))     # STD_INPUT_HANDLE
        mode = wintypes.DWORD()
        if not handle or not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_quick_edit_mode, enable_extended_flags = 0x0040, 0x0080
        new_mode = (mode.value | enable_extended_flags) & ~enable_quick_edit_mode
        return bool(kernel32.SetConsoleMode(handle, new_mode))
    except Exception:
        return False


def install() -> dict:
    """
    Make console output UTF-8 safe, and a click in the window harmless.
    Idempotent.

    Returns what changed, so a caller that cares can log it -- safely,
    by then.
    """
    result = {
        "stdout": _reconfigure("stdout"),
        "stderr": _reconfigure("stderr"),
        "handlers_fixed": _fix_logging_handlers(),
        "quick_edit_disabled": disable_quick_edit(),
    }
    return result


# Installed on import: the failures this prevents happen at IMPORT time
# in other modules (ai/ai_gnn logs while being imported), so requiring
# an explicit call would be too late for the case that matters most.
_INSTALLED = install()
