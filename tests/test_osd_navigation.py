"""Menu navigation pacing.

StickController turns positions into repeated 'direction' signals. Menus accept
more than one input at once -- STICK, plus the d-pad, which arrives as LEFT on a
DualShock 4 and as DPAD on an SC2 -- and they all feed one controller.

Sharing it naively breaks in a way that looks like two unrelated bugs: nudging
the stick scrolls far too fast, and holding it fully deflected stops the list
dead. Both come from the same place. _move() emits on every direction change and
cancels the repeat timer whenever the direction reaches zero, so an idle input
reporting (0, 0) cancels the repeat the stick is driving. Movement then happens
only on changes -- once per event, at the controller's report rate -- and stops
entirely as soon as the stick is held still and stops producing events.

Needs Gtk for the GObject signal; run under xvfb-run on a headless machine.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
	not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
	reason="needs a display; try xvfb-run",
)


@pytest.fixture
def pacer():
	"""A StickController with its timer calls recorded rather than run."""
	import gi

	gi.require_version("Gtk", "3.0")
	from scc.osd import StickController

	sc = StickController()
	sc.emits, sc.timers = [], []
	sc.connect("direction", lambda o, x, y: sc.emits.append((x, y)))
	sc.timer = lambda name, delay, cb, *a: sc.timers.append("schedule")
	sc.cancel_timer = lambda name: sc.timers.append("cancel")
	return sc


def test_an_idle_input_does_not_cancel_another_that_is_held(pacer):
	"""The bug, stated directly: a d-pad sitting at rest must not stop the
	repeat that a held stick is driving.
	"""
	from scc.constants import LEFT, STICK, STICK_PAD_MAX

	for trash in range(3):
		pacer.set_stick(0, STICK_PAD_MAX, source=STICK)
		pacer.set_stick(0, 0, source=LEFT)      # d-pad, untouched

	assert pacer.emits == [(0, -1)], "moved once per event instead of once per interval"
	assert pacer.timers == ["schedule"], "the repeat timer was cancelled by the idle input"


def test_releasing_everything_still_stops(pacer):
	"""The cancel has to survive: once nothing is deflected, the repeat ends."""
	from scc.constants import LEFT, STICK, STICK_PAD_MAX

	pacer.set_stick(0, STICK_PAD_MAX, source=STICK)
	pacer.set_stick(0, 0, source=LEFT)
	pacer.set_stick(0, 0, source=STICK)

	assert pacer.emits[-1] == (0, 0)
	assert pacer.timers[-1] == "cancel"


@pytest.mark.parametrize("source_name", ["STICK", "LEFT", "DPAD"])
def test_any_single_input_navigates(pacer, source_name):
	"""Whichever input a given controller delivers its d-pad on, it works: the
	DS4 sends it as LEFT, the SC2 as DPAD.
	"""
	import scc.constants as c

	source = getattr(c, source_name)
	pacer.set_stick(0, c.STICK_PAD_MAX, source=source)
	assert pacer.emits == [(0, -1)]
	assert pacer.timers == ["schedule"]


def test_the_deflected_input_wins_over_an_idle_one(pacer):
	"""Order must not matter -- the idle input may be reported after the held
	one, which is precisely when it used to clobber it.
	"""
	from scc.constants import DPAD, STICK, STICK_PAD_MIN

	pacer.set_stick(0, 0, source=DPAD)
	pacer.set_stick(0, STICK_PAD_MIN, source=STICK)
	pacer.set_stick(0, 0, source=DPAD)

	assert pacer.emits == [(0, 1)], "a later idle report overrode the held input"


def test_callers_with_a_single_input_are_unaffected(pacer):
	"""launcher and dialog pass no source; they must behave exactly as before."""
	from scc.constants import STICK_PAD_MAX

	pacer.set_stick(0, STICK_PAD_MAX)
	pacer.set_stick(0, STICK_PAD_MAX)
	assert pacer.emits == [(0, -1)], "a repeated identical position re-fired"
	pacer.set_stick(0, 0)
	assert pacer.emits[-1] == (0, 0)
	assert pacer.timers[-1] == "cancel"


def test_a_submenu_accepts_the_dpad_too():
	"""A submenu reuses its parent's input lock and so never calls
	lock_inputs(). While _control_with_dpad was set in there, every submenu
	came up with it clear and ignored the d-pad -- the stick still worked,
	because it matches _control_with directly, so the main menu looked fine and
	only submenus ('All profiles') were dead. Deciding it in use_controller,
	which submenus DO call, is what makes them agree.
	"""
	import gi

	gi.require_version("Gtk", "3.0")
	from scc.constants import DPAD, LEFT, STICK, ControllerFlags
	from scc.osd.menu import Menu

	class FakeConfig:
		def get_controller_config(self, id):
			return {"menu_control": STICK, "menu_cancel": "B", "menu_confirm": "A"}

	class FakeArgs:
		control_with = STICK
		cancel_with = "B"
		confirm_with = "A"

	class FakeController:
		def get_id(self):
			return "sc2"

		def get_flags(self):
			return ControllerFlags.HAS_DPAD

	class FakeSubmenu:
		config = FakeConfig()
		args = FakeArgs()
		_control_with_dpad = False       # as a fresh menu starts out

	m = FakeSubmenu()
	Menu.use_controller(m, FakeController())   # and NOT lock_inputs()

	assert m._control_with_dpad, "use_controller must decide this, not lock_inputs"
	for source in (DPAD, LEFT):
		assert Menu._is_control_event(m, source), (
			"a submenu ignored the d-pad arriving as %r" % (source,))


def test_a_pad_without_a_dpad_does_not_pretend_to_have_one():
	"""The flag has to stay off where it was off before, or LEFT-as-d-pad would
	start navigating on controllers whose LEFT is a touchpad.
	"""
	import gi

	gi.require_version("Gtk", "3.0")
	from scc.constants import DPAD, STICK
	from scc.osd.menu import Menu

	class FakeConfig:
		def get_controller_config(self, id):
			return {"menu_control": STICK, "menu_cancel": "B", "menu_confirm": "A"}

	class FakeArgs:
		control_with = STICK
		cancel_with = "B"
		confirm_with = "A"

	class FakeController:
		def get_id(self):
			return "sc1"

		def get_flags(self):
			return 0

	m = type("M", (), {"config": FakeConfig(), "args": FakeArgs(), "_control_with_dpad": False})()
	Menu.use_controller(m, FakeController())
	assert not m._control_with_dpad
	assert not Menu._is_control_event(m, DPAD)


def test_the_menu_tells_the_pacer_which_input_an_event_came_from():
	"""The wiring, not just the pacer.

	StickController can only separate the inputs if the menu says which one an
	event arrived on. Without this the fix above is inert -- every input shares
	one entry again -- and nothing else in the suite would notice.
	"""
	from scc.constants import LEFT, STICK, STICK_PAD_MAX
	from scc.osd.menu import Menu

	seen = []

	class FakeScon:
		def set_stick(self, x, y, source=None):
			seen.append((x, y, source))

	class FakeMenu:
		_submenu = None
		_use_cursor = False
		_control_with = STICK
		_control_with_dpad = True
		_confirm_with = "A"
		_cancel_with = "B"
		_scon = FakeScon()
		_is_control_event = Menu._is_control_event

	m = FakeMenu()
	Menu.on_event(m, None, STICK, (0, STICK_PAD_MAX))
	Menu.on_event(m, None, LEFT, (0, 0))

	assert seen == [(0, STICK_PAD_MAX, STICK), (0, 0, LEFT)], (
		"the menu did not pass the source through: %r" % (seen,))
