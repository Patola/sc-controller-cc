"""What an action does with the RIGHT input slot depends on the controller.

The SC2 and the Deck put a touchpad there and deliver the right stick
separately as RSTICK. The DS4 and DS5 have no touchpad in that slot and deliver
the right STICK as RIGHT -- their HID state has no rstick_* fields. So RIGHT
alone says nothing about whether the data is a stick or a pad; right_is_stick()
does, and every action that branches on it has to use the predicate.

MouseAction had this clause removed rather than converted when the predicate was
introduced, and a DS4 right stick bound to Mouse fell through to the trackball
branch. Driven through a fake mapper: the real one needs a daemon, a controller
and uinput devices.
"""
import pytest

from scc.actions import MouseAction
from scc.constants import RIGHT, RSTICK, STICK, STICK_PAD_MAX, ControllerFlags

DS4_LIKE = ControllerFlags.HAS_RSTICK                            # stick in RIGHT
SC2_LIKE = ControllerFlags.HAS_RSTICK | ControllerFlags.HAS_RPAD  # pad in RIGHT
SC1_LIKE = ControllerFlags(0)                                     # pad in RIGHT


class FakeMouse:
	def __init__(self):
		self.moves = []

	def moveEvent(self, dx, dy, elapsed):
		self.moves.append((dx, dy))

	def clearRemainders(self):
		pass


class FakeMapper:
	def __init__(self, flags):
		self._flags = flags
		self.mouse = FakeMouse()
		self.force_event = set()
		self.time_elapsed = 0.01
		self.stick_moves = []
		self.touched = set()
		self.button_calls = []   # the pad-style handover path uses these

	def controller_flags(self):
		return self._flags

	def mouse_move_stick(self, dx, dy):
		self.stick_moves.append((dx, dy))

	def mouse_move(self, dx, dy):
		self.mouse.moves.append((dx, dy))

	def is_touched(self, what):
		return what in self.touched

	def was_touched(self, what):
		return what in self.touched

	def send_feedback(self, *a):
		pass

	def set_button(self, what, value):
		self.button_calls.append((what, value))

	def set_was_pressed(self, what, value):
		self.button_calls.append((what, value))

	def is_pressed(self, what):
		return False

	def was_pressed(self, what):
		return False


def _travel(moves):
	"""Net pointer displacement along x."""
	return sum(dx for dx, trash in moves)


@pytest.mark.parametrize("what", [STICK, RSTICK])
def test_a_real_stick_drives_velocity_mouse(what):
	m = FakeMapper(SC2_LIKE)
	MouseAction().whole(m, STICK_PAD_MAX // 2, 0, what)
	assert m.stick_moves, "%s should move the pointer at a velocity" % (what,)
	assert not m.mouse.moves


def test_ds4_right_stick_is_a_stick_even_though_it_arrives_as_right():
	m = FakeMapper(DS4_LIKE)
	MouseAction().whole(m, STICK_PAD_MAX // 2, 0, RIGHT)
	assert m.stick_moves
	assert not m.mouse.moves


@pytest.mark.parametrize("flags", [SC2_LIKE, SC1_LIKE])
def test_a_right_touchpad_stays_a_trackball(flags):
	m = FakeMapper(flags)
	m.touched.add(RIGHT)
	MouseAction().whole(m, 0, 0, RIGHT)
	MouseAction().whole(m, 1000, 0, RIGHT)
	assert not m.stick_moves, "a touchpad must not get velocity-style mouse"


def test_a_stick_held_and_released_does_not_spring_the_pointer_back():
	"""The symptom the regression produced, stated as a property.

	On the trackball branch the pointer follows the stick's absolute deflection,
	so returning the stick to centre undoes every bit of movement -- the pointer
	is trapped in a circle around where it started. A stick must keep moving the
	pointer for as long as it is held, and leave it where it got to.
	"""
	m = FakeMapper(DS4_LIKE)
	action = MouseAction()
	for x in (0, 8000, 16000, 24000, 32000, 24000, 16000, 8000, 0):
		action.whole(m, x, 0, RIGHT)

	assert _travel(m.stick_moves) > 0, "pointer sprang back to where it started"
	assert not m.mouse.moves


class RecordingAction:
	"""Stands in for a ring's child action."""

	def __init__(self):
		self.calls = []

	def whole(self, mapper, x, y, what):
		self.calls.append((x, y, what))

	def __bool__(self):
		return True


def test_a_stick_deflection_presses_a_button_bound_to_the_right_slot():
	"""ButtonAction treats a stick as one big button, past a deadzone. A pad
	instead waits for a click or a touch -- neither of which a stick reports, so
	on the wrong branch the button simply never fires.
	"""
	from scc.actions import ButtonAction

	m = FakeMapper(DS4_LIKE)
	action = ButtonAction(1)
	pressed = []
	action.button_press = lambda mapper: pressed.append("press")
	action.button_release = lambda mapper: pressed.append("release")

	action.whole(m, STICK_PAD_MAX, 0, RIGHT)   # pushed hard over
	action.whole(m, 0, 0, RIGHT)               # let go, recentres
	assert pressed == ["press", "release"]


def test_a_ring_on_a_stick_crosses_its_border_the_stick_way():
	"""A ring hands over between its two children differently for a stick and a
	pad: a stick is recentred (the old child gets 0,0), a finger is treated as
	lifted and re-touched (set_button around the handover). A stick never
	reports a touch at all, so on the pad branch nothing happened whatsoever.
	"""
	from scc.actions import RingAction

	inner, outer = RecordingAction(), RecordingAction()
	action = RingAction(0.5, inner, outer)
	m = FakeMapper(DS4_LIKE)

	action.whole(m, STICK_PAD_MAX, 0, RIGHT)   # out into the outer ring
	assert outer.calls, "stick deflection never reached a ring child"
	assert action._active is outer

	outer.calls.clear()
	action.whole(m, 0, 0, RIGHT)               # back to centre: inner takes over
	assert outer.calls[-1] == (0, 0, RIGHT), "outgoing child was not recentred"
	assert action._active is inner
	assert not m.button_calls, "a stick must not be handed over as a touch"
