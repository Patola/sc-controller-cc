"""A failing scheduled task must not take the daemon with it.

Scheduler.run() is one of the daemon's two mainloops, driven by an unguarded
`while True: for fn in self.mainloops: fn()`. It invoked task callbacks with no
exception handling, so any mistake reachable from a scheduled callback became a
total outage rather than a log line -- and the symptom landed nowhere near the
cause. The worked example: SCC_NOGAMEPAD left mapper.gamepad as None, which is
cosmetic in itself, and the daemon died a second later inside the scheduled
fix_xinput, presenting as "cannot acquire my Steam Controller 1 and 2".

Pure Python, no hardware and no uinput, so this runs in every environment.
"""
import logging

import pytest

from scc.scheduler import Scheduler


def test_a_failing_task_does_not_escape_run():
	"""The bug itself: this used to propagate out and kill the process."""
	s = Scheduler()

	def boom():
		raise RuntimeError("task exploded")

	s.schedule(0, boom)
	s.run()          # must simply return


def test_later_tasks_still_run_after_one_fails():
	"""Losing the rest of the queue would be its own outage."""
	s = Scheduler()
	ran = []

	s.schedule(0, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
	s.schedule(0, ran.append, "after")
	s.run()

	assert ran == ["after"], "a failing task swallowed the tasks behind it"


def test_the_failure_is_logged_with_a_traceback(caplog):
	"""Swallowing silently would be worse than crashing -- the cause has to be
	findable, which is exactly what was missing when this was diagnosed.
	"""
	s = Scheduler()

	def identifiable_task():
		raise ValueError("the actual cause")

	with caplog.at_level(logging.DEBUG):
		s.schedule(0, identifiable_task)
		s.run()

	assert any(r.levelno >= logging.ERROR for r in caplog.records)
	text = caplog.text
	assert "identifiable_task" in text, "the log does not say which task failed"
	assert "the actual cause" in text, "the original exception is not in the log"
	assert "Traceback" in text, "no traceback; the cause would still be guesswork"


def test_normal_tasks_are_untouched():
	"""Regression guard on the happy path, arguments included."""
	s = Scheduler()
	seen = []

	s.schedule(0, lambda *a: seen.append(a), 1, "two")
	s.run()

	assert seen == [(1, "two")]


def test_a_task_scheduled_in_the_future_does_not_run_yet():
	s = Scheduler()
	ran = []
	s.schedule(3600, ran.append, "later")
	s.run()
	assert ran == []


def test_cancel_still_works():
	s = Scheduler()
	ran = []
	task = s.schedule(0, ran.append, "cancelled")
	assert s.cancel_task(task) is True
	s.run()
	assert ran == []


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_interrupts_still_propagate(exc):
	"""`except Exception`, not a bare `except`: Ctrl-C and SystemExit are not
	errors to swallow, and the daemon must still be able to exit.
	"""
	s = Scheduler()
	s.schedule(0, lambda: (_ for _ in ()).throw(exc()))
	with pytest.raises(exc):
		s.run()


def test_a_repeatedly_failing_task_does_not_flood_the_log(caplog):
	"""A task that reschedules itself and then fails would otherwise write a
	traceback every few milliseconds. The first is reported in full; the rest
	are counted.
	"""
	s = Scheduler()

	def always_fails():
		raise RuntimeError("again")

	with caplog.at_level(logging.DEBUG):
		for _ in range(50):
			s.schedule(0, always_fails)
			s.run()

	tracebacks = caplog.text.count("Traceback")
	assert tracebacks == 1, "logged %d tracebacks for one repeating failure" % tracebacks


def test_distinct_failing_tasks_are_each_reported(caplog):
	"""Rate limiting is per callback, so a second broken task is not hidden by
	the first one's noise.
	"""
	s = Scheduler()

	def first_task():
		raise RuntimeError("one")

	def second_task():
		raise RuntimeError("two")

	with caplog.at_level(logging.DEBUG):
		for cb in (first_task, second_task):
			s.schedule(0, cb)
			s.run()

	assert "first_task" in caplog.text
	assert "second_task" in caplog.text
