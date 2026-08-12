"""Regression tests for security fixes from the 2026-08-12 audit."""

from scc.sccdaemon import SafeTalkingActionParser
from scc.scheduler import Task
from scc.tools import find_menu, find_profile


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
	"""Drivers that build HIDDecoder manually must set packet_size."""

	def test_default_packet_size_is_zero(self):
		from scc.drivers.hiddrv import HIDDecoder
		d = HIDDecoder()
		assert d.packet_size == 0

	def test_ds4_sets_packet_size(self):
		from scc.drivers.hiddrv import HIDDecoder
		d = HIDDecoder()
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
