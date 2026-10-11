"""SC Controller - Scheduler

Centralized scheduler that should be used everywhere.
Callbacks are executed on the main thread via run(). The schedule()
method may be called from any thread (e.g. socket handler threads).

Use schedule(delay, callback, *data) to register one-time task.
"""

import logging
import queue
import threading
import time

log = logging.getLogger("Scheduler")

# A task that reschedules itself and then fails would otherwise log a traceback
# every few milliseconds. The first failure of each callback is always reported
# in full; after that, repeats are counted and summarised no more often than
# this (seconds).
FAILURE_REPORT_INTERVAL = 10.0

# TODO: Maybe create actual thread for this? Use poler? Scrap everything and rewrite it in GO?


class Scheduler:
	def __init__(self):
		self._lock = threading.Lock()
		self._scheduled = queue.PriorityQueue()
		self._next = None
		self._now = time.time()
		self._seq = 0
		self._failures = {}  # callback name -> [count, time last reported]

	def schedule(self, delay, callback, *data):
		"""Schedules one-time task to be executed no sooner than after 'delay' of
		seconds. Delay may be float number.
		'callback' is called as callback(*data).

		Returned Task instance can be used to cancel task once scheduled.
		"""
		with self._lock:
			task = Task(self._now + delay, self._seq, callback, data)
			self._seq += 1
			if self._next is None or task.time < self._next.time:
				if self._next:
					self._scheduled.put(self._next)
				self._next = task
			else:
				self._scheduled.put(task)
			return task

	def cancel_task(self, task):
		"""Returns True if task was sucessfully removed or False if task was
		already executed or not known at all.

		Note that this is slow as hell, so it _has_ to be called on
		main thread.
		"""
		with self._lock:
			if task == self._next:
				self._next = None if self._scheduled.empty() else self._scheduled.get()
				return True
			tasks, found = [], False
			while not self._scheduled.empty():
				t = self._scheduled.get()
				if t == task:
					found = True
					break
				tasks.append(t)
			for t in tasks:
				self._scheduled.put(t)
			return found

	def run(self):
		self._now = time.time()
		while True:
			with self._lock:
				if not (self._next and self._now >= self._next.time):
					break
				callback, data = self._next.callback, self._next.data
				self._next = (None if self._scheduled.empty()
					else self._scheduled.get())
			try:
				callback(*data)
			except Exception:
				# A failing task must not take the daemon with it. run() is one
				# of the daemon's two mainloops, called from an unguarded
				# `while True`, so an exception here used to unwind straight
				# out of the process -- turning any mistake reachable from a
				# scheduled callback into a total outage, with a symptom
				# nowhere near its cause. SCC_NOGAMEPAD left mapper.gamepad as
				# None, and the daemon died a second later inside fix_xinput,
				# presenting as "cannot acquire my Steam Controller".
				#
				# The task itself is already gone: it was taken off the queue
				# before the call, so a one-shot task simply does not complete.
				# A task that reschedules itself before failing will repeat,
				# which is what the rate limiting below is for.
				#
				# `except Exception`, deliberately: KeyboardInterrupt and
				# SystemExit are not errors to be swallowed, and the daemon
				# must still be able to exit.
				self._report_failure(callback)

	def _report_failure(self, callback) -> None:
		"""Logs a task failure, in full the first time and sparingly after.

		Keyed by name rather than by the callback object, so this never keeps a
		bound method (and whatever it closes over) alive.
		"""
		name = getattr(callback, "__qualname__", None) or repr(callback)
		now = time.time()
		seen = self._failures.get(name)
		if seen is None:
			self._failures[name] = [1, now]
			log.exception("Scheduled task %s failed and was dropped; continuing", name)
		else:
			seen[0] += 1
			if now - seen[1] >= FAILURE_REPORT_INTERVAL:
				log.error("Scheduled task %s has failed %d times", name, seen[0])
				seen[1] = now


class Task:
	def __init__(self, time, seq, callback, data):
		self.time = time
		self.seq = seq
		self.callback = callback
		self.data = data

	def cancel(self):
		"""Marks task as canceled, without actually removing it from scheduler"""
		self.callback = lambda *a, **b: False
		self.data = ()

	def __lt__(self, other):
		if self.time != other.time:
			return self.time < other.time
		return self.seq < other.seq
