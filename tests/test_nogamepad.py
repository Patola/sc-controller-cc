"""Disabling the emulated gamepad must not disturb input handling.

SCC_NOGAMEPAD is meant to do one thing: emit no virtual pad. It did rather
more. create_gamepad() returned None in that branch while the caller assigns
what it returns, so mapper.gamepad became None instead of a Dummy. Nothing
noticed until the first thing touched it -- fix_xinput, which the daemon
schedules one second after startup and which the scheduler invokes without a
guard -- so the AttributeError propagated out of the mainloop and killed the
daemon about a second in, i.e. right after the controllers had been acquired.
It read as "cannot acquire my Steam Controller", with nothing pointing at the
output device.

TODO.md plans to expose this as a GUI option, which makes the contract worth
pinning: whatever the output device is set to, mapper.gamepad is always
something safe to call.
"""
import pytest

try:
	# OSError, not ImportError, when libuinput is unbuilt.
	from scc.mapper import Mapper
	from scc.uinput import Dummy
except (ImportError, OSError) as e:
	pytest.skip("mapper unavailable: %s" % (e,), allow_module_level=True)


def make_gamepad(monkeypatch, nogamepad: bool, enabled: bool = True):
	"""create_gamepad() unbound -- the disabled path returns before it touches
	self or /dev/uinput, so this needs no Mapper and no uinput."""
	if nogamepad:
		monkeypatch.setenv("SCC_NOGAMEPAD", "1")
	else:
		monkeypatch.delenv("SCC_NOGAMEPAD", raising=False)
	return Mapper.create_gamepad(None, enabled, None)


def test_scc_nogamepad_yields_a_dummy_not_none(monkeypatch):
	"""The bug itself. None here is what took the daemon down."""
	gamepad = make_gamepad(monkeypatch, nogamepad=True)
	assert gamepad is not None, "mapper.gamepad would be None; anything touching it raises"
	assert isinstance(gamepad, Dummy)


def test_the_dummy_absorbs_every_call_a_binding_would_make(monkeypatch):
	"""A profile bound to gamepad axes/buttons must go quiet, not explode."""
	gamepad = make_gamepad(monkeypatch, nogamepad=True)
	gamepad.keyEvent(0, 1)
	gamepad.axisEvent(0, 0)
	gamepad.synEvent()


def test_an_empty_value_still_disables_it(monkeypatch):
	"""It is a presence test, so SCC_NOGAMEPAD= and =0 disable it too. Pinned
	because a GUI option would plausibly write "0" and expect it to mean off.
	"""
	for value in ("", "0", "false"):
		monkeypatch.setenv("SCC_NOGAMEPAD", value)
		assert isinstance(Mapper.create_gamepad(None, True, None), Dummy), (
			"SCC_NOGAMEPAD=%r did not disable the gamepad" % (value,))


def test_disabled_by_argument_behaves_the_same(monkeypatch):
	"""The route a GUI option would take, rather than the env var."""
	assert isinstance(make_gamepad(monkeypatch, nogamepad=False, enabled=False), Dummy)


def test_the_gamepad_name_is_none_when_there_is_no_gamepad(monkeypatch):
	"""fix_xinput asks for this one second into startup and skips its work when
	it is None. It is also where the AttributeError was raised.
	"""
	class FakeMapper:
		gamepad = make_gamepad(monkeypatch, nogamepad=True)

	assert Mapper.get_gamepad_name(FakeMapper()) is None
