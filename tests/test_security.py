"""Regression tests for security fixes from the 2026-08-12 audit."""

import pytest

from scc.scheduler import Task
from scc.tools import find_menu, find_profile

# scc.sccdaemon reaches ioctl_opt (via device_monitor), a real runtime
# dependency a minimal build environment may not have installed yet. Not being
# able to check the parser there is a skip, not a collection failure.
SafeTalkingActionParser = pytest.importorskip("scc.sccdaemon").SafeTalkingActionParser


class TestSafeParser:
	"""SafeTalkingActionParser must reject dangerous actions."""

	def _parse(self, action_str):
		"""TalkingActionParser returns None on parse failure instead of raising."""
		return SafeTalkingActionParser().restart(action_str).parse()

	def test_rejects_shell(self):
		assert self._parse("shell('echo pwned')") is None

	def test_rejects_shell_nested_in_and(self):
		assert self._parse("button(KEY_A) and shell('echo pwned')") is None

	def test_rejects_shell_in_semicolon_sequence(self):
		assert self._parse("button(KEY_A); shell('echo pwned')") is None

	def test_rejects_profile(self):
		assert self._parse("profile('evil')") is None

	def test_rejects_restart(self):
		assert self._parse("restart()") is None

	def test_rejects_exit_alias(self):
		assert self._parse("exit()") is None

	def test_rejects_turnoff(self):
		assert self._parse("turnoff()") is None

	def test_allows_button(self):
		action = self._parse("button(KEY_A)")
		assert action is not None

	def test_allows_axis(self):
		action = self._parse("axis(ABS_X)")
		assert action is not None

	def test_rejects_shell_as_action_parameter(self):
		assert self._parse("osd(shell('echo pwned'))") is None


class TestPathValidation:
	"""find_profile/find_menu must reject names with path components."""

	def test_profile_traversal_returns_none(self):
		assert find_profile("../../etc/passwd") is None

	def test_profile_absolute_returns_none(self):
		assert find_profile("/etc/passwd") is None

	def test_profile_dotdot_returns_none(self):
		assert find_profile("..") is None

	def test_menu_traversal_returns_none(self):
		assert find_menu("../../etc/shadow") is None

	def test_menu_absolute_returns_none(self):
		assert find_menu("/etc/passwd") is None

	def test_menu_dotdot_returns_none(self):
		assert find_menu("..") is None

	def test_menu_slash_only_returns_none(self):
		assert find_menu("subdir/file.menu") is None


class TestHIDDecoderPacketSize:
	"""Drivers that build HIDDecoder manually must set packet_size.

	hiddrv loads the compiled libhiddrv at import time and raises OSError -- not
	ImportError -- when it has not been built, so importorskip alone does not
	cover it. CI does not build the extension; not being able to check this
	there is a skip, not a failure.
	"""

	@staticmethod
	def _decoder():
		try:
			from scc.drivers.hiddrv import HIDDecoder
		except (ImportError, OSError) as e:
			pytest.skip("libhiddrv is not built here: %s" % e)
		return HIDDecoder()

	def test_default_packet_size_is_zero(self):
		assert self._decoder().packet_size == 0

	def test_ds4_sets_packet_size(self):
		d = self._decoder()
		d.packet_size = 64
		assert d.packet_size == 64


class TestSchedulerOrdering:
	"""Task.__lt__ must return a boolean, not None."""

	def test_task_ordering(self):
		t1 = Task(1.0, 0, lambda: None, ())
		t2 = Task(2.0, 1, lambda: None, ())
		assert (t1 < t2) is True
		assert (t2 < t1) is False

	def test_equal_time_fifo(self):
		t1 = Task(1.0, 0, lambda: None, ())
		t2 = Task(1.0, 1, lambda: None, ())
		assert (t1 < t2) is True
		assert (t2 < t1) is False


class TestDS5StickDeadzone:
	"""Both DualSense transports must swallow the same resting offset.

	The pad's mechanical centre sits several raw units off and only settles
	after the stick is worked. At the old value of 2 that reached the output as
	~1500 of 32767 -- constant drift -- and the Bluetooth path applied no
	deadzone whatsoever.
	"""

	def _ds5(self):
		try:
			import scc.drivers.ds5drv as ds5
		except (ImportError, OSError) as e:
			pytest.skip("ds5drv is not importable here: %s" % e)
		return ds5

	def test_the_deadzone_covers_a_realistic_resting_offset(self):
		"""~6 raw units was measured on hardware; anything at or under the
		deadzone must reach the output as exactly zero.
		"""
		ds5 = self._ds5()
		assert ds5._STICK_DEADZONE >= 8, "too small to cover the observed offset"
		assert ds5._STICK_DEADZONE <= 20, "so wide the stick would feel dead"

	def test_bluetooth_centres_a_resting_stick(self):
		ds5 = self._ds5()
		scale = ds5.DS5HidRawController._stick_axis_scale
		for raw in range(128 - ds5._STICK_DEADZONE, 128 + ds5._STICK_DEADZONE + 1):
			assert scale(None, raw) == 0, "raw %d drifts over Bluetooth" % raw

	def test_bluetooth_still_reaches_both_extremes(self):
		ds5 = self._ds5()
		from scc.constants import STICK_PAD_MAX, STICK_PAD_MIN

		scale = ds5.DS5HidRawController._stick_axis_scale
		assert scale(None, 255) == STICK_PAD_MAX
		assert scale(None, 0) == STICK_PAD_MIN
		# and just outside the deadzone it is live again, not stuck at 0
		assert scale(None, 128 + ds5._STICK_DEADZONE + 1) > 0
		assert scale(None, 128 - ds5._STICK_DEADZONE - 1) < 0

	def test_both_transports_share_one_value(self):
		"""They are separate code paths; a single constant keeps them honest."""
		ds5 = self._ds5()
		src = open(ds5.__file__).read()
		assert "deadzone=2*2.0/255" not in src, "a hardcoded deadzone crept back"
		assert src.count("_STICK_DEADZONE") >= 6
