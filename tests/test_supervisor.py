# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import signal
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pridge_client.supervisor import _SignalForwarder, run_supervised


class _FakeProcess:
    def __init__(self, exit_code: int) -> None:
        self._exit_code = exit_code
        self._exited = False

    def wait(self) -> int:
        self._exited = True
        return self._exit_code

    def poll(self):
        return self._exit_code if self._exited else None

    def send_signal(self, _signum: int) -> None:
        self._exited = True


class _RecordingPopenFactory:
    """Stands in for subprocess.Popen: returns one _FakeProcess per call,
    in order, and records what command each call was made with.
    """

    def __init__(self, exit_codes: list[int]) -> None:
        self._exit_codes = list(exit_codes)
        self.calls: list[list[str]] = []

    def __call__(self, command, *_args, **_kwargs):
        self.calls.append(list(command))
        return _FakeProcess(self._exit_codes.pop(0))


class SignalForwarderTests(unittest.TestCase):
    def test_forwards_to_a_live_process_and_marks_terminating(self) -> None:
        forwarder = _SignalForwarder()
        fake_process = SimpleNamespace(poll=lambda: None, send_signal=Mock())
        forwarder.process = fake_process

        forwarder(signal.SIGTERM, None)

        self.assertTrue(forwarder.terminating)
        fake_process.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_skips_a_process_that_already_exited(self) -> None:
        forwarder = _SignalForwarder()
        fake_process = SimpleNamespace(poll=lambda: 0, send_signal=Mock())
        forwarder.process = fake_process

        forwarder(signal.SIGINT, None)

        self.assertTrue(forwarder.terminating)
        fake_process.send_signal.assert_not_called()

    def test_marks_terminating_even_with_no_process_running(self) -> None:
        forwarder = _SignalForwarder()
        forwarder(signal.SIGTERM, None)
        self.assertTrue(forwarder.terminating)


class RunSupervisedTests(unittest.TestCase):
    def test_restarts_the_child_after_a_crash_then_stops_on_clean_exit(self) -> None:
        factory = _RecordingPopenFactory([7, 0])
        with patch("pridge_client.supervisor.subprocess.Popen", factory), patch(
            "pridge_client.supervisor.command", return_value=["fake-exe"]
        ), patch("pridge_client.supervisor.INITIAL_BACKOFF_SECONDS", 0.001), patch(
            "pridge_client.supervisor.SLEEP_CHUNK_SECONDS", 0.001
        ):
            exit_code = run_supervised([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(factory.calls), 2)

    def test_does_not_restart_after_a_clean_exit(self) -> None:
        factory = _RecordingPopenFactory([0])
        with patch("pridge_client.supervisor.subprocess.Popen", factory), patch(
            "pridge_client.supervisor.command", return_value=["fake-exe"]
        ):
            exit_code = run_supervised(["--headless"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(factory.calls, [["fake-exe", "--headless"]])

    def test_gives_up_after_repeated_rapid_crashes(self) -> None:
        factory = _RecordingPopenFactory([1, 1, 1])
        with patch("pridge_client.supervisor.subprocess.Popen", factory), patch(
            "pridge_client.supervisor.command", return_value=["fake-exe"]
        ), patch("pridge_client.supervisor.INITIAL_BACKOFF_SECONDS", 0.001), patch(
            "pridge_client.supervisor.SLEEP_CHUNK_SECONDS", 0.001
        ), patch("pridge_client.supervisor.MAX_RAPID_FAILURES", 3):
            exit_code = run_supervised([])

        self.assertEqual(exit_code, 1)
        self.assertEqual(len(factory.calls), 3)


if __name__ == "__main__":
    unittest.main()
