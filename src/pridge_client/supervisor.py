# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import signal
import subprocess
import time
from collections.abc import Sequence

from pridge_client.autostart import command, independent_child_environment


logger = logging.getLogger(__name__)

INITIAL_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
# A crash after a long healthy run shouldn't be punished with a long wait -
# only sustained rapid crashing should back off.
BACKOFF_RESET_AFTER_SECONDS = 300.0
# Guards against a poison-pill crash-on-startup spinning forever.
MAX_RAPID_FAILURES = 10
RAPID_FAILURE_WINDOW_SECONDS = 300.0
SLEEP_CHUNK_SECONDS = 1.0


class _SignalForwarder:
    """Marks the supervisor as terminating and relays the signal to whichever
    child process is currently running, if any. A plain class (rather than a
    closure) so tests can drive it directly instead of sending real OS
    signals, which don't behave uniformly across platforms.
    """

    def __init__(self) -> None:
        self.terminating = False
        self.process: subprocess.Popen | None = None

    def __call__(self, signum: int, _frame: object) -> None:
        self.terminating = True
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signum)


def run_supervised(extra_args: Sequence[str]) -> int:
    """Relaunch the app whenever it crashes, but never after a clean exit.

    Spawns the real app as a child process with --supervised-child so it
    runs its normal startup path. A child exit code of 0 means Quit was
    used deliberately (see gui.py's quit_application / app.py's headless
    SIGTERM handling) and supervision stops; anything else is treated as a
    crash and the child is relaunched with backoff. SIGTERM/SIGINT sent to
    this process (e.g. on logout/shutdown) are forwarded to the child and
    then supervision stops without restarting, so a system shutdown never
    turns into a crash-loop.
    """
    child_command = [*command("--supervised-child"), *extra_args]
    forwarder = _SignalForwarder()
    signal.signal(signal.SIGTERM, forwarder)
    signal.signal(signal.SIGINT, forwarder)

    backoff_seconds = INITIAL_BACKOFF_SECONDS
    failure_times: list[float] = []

    while not forwarder.terminating:
        started_at = time.monotonic()
        forwarder.process = subprocess.Popen(child_command, env=independent_child_environment())
        exit_code = forwarder.process.wait()
        forwarder.process = None

        if forwarder.terminating or exit_code == 0:
            return 0

        uptime_seconds = time.monotonic() - started_at
        logger.warning(
            "Pridge Client exited unexpectedly (code %s) after %.1fs; restarting",
            exit_code,
            uptime_seconds,
        )

        now = time.monotonic()
        failure_times.append(now)
        failure_times[:] = [when for when in failure_times if now - when <= RAPID_FAILURE_WINDOW_SECONDS]
        if len(failure_times) >= MAX_RAPID_FAILURES:
            logger.critical(
                "Pridge Client crashed %s times within %.0fs; giving up auto-restart",
                len(failure_times),
                RAPID_FAILURE_WINDOW_SECONDS,
            )
            return exit_code

        if uptime_seconds >= BACKOFF_RESET_AFTER_SECONDS:
            backoff_seconds = INITIAL_BACKOFF_SECONDS

        remaining_seconds = backoff_seconds
        while remaining_seconds > 0 and not forwarder.terminating:
            chunk = min(SLEEP_CHUNK_SECONDS, remaining_seconds)
            time.sleep(chunk)
            remaining_seconds -= chunk
        backoff_seconds = min(backoff_seconds * 2, MAX_BACKOFF_SECONDS)

    return 0
