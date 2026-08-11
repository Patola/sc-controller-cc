"""What the RIGHT input slot carries, per driver.

right_is_stick() decides whether the RIGHT slot is a self-centering stick or a
real touchpad, and four places branch on it: the mapper's RPAD dispatch,
BallModifier.whole/change and SmoothModifier.whole. Get it wrong for a pad and
trackball, per-pad sensitivity and pad feedback all silently stop working at
once, which is exactly what happened on the SC2.

The flags are plain class attributes, so the answer can be pinned here instead
of being rediscovered on hardware every time a driver is touched.
"""
import importlib

import pytest

from scc.constants import ControllerFlags, right_is_stick


def _flags(module, cls):
	# Not importorskip: the DS4/DS5 drivers pull in hiddrv, which loads the
	# compiled libhiddrv at import time and raises OSError -- not ImportError --
	# when it has not been built. CI does not build it, so importorskip alone
	# turned "cannot check this here" into a failure.
	try:
		mod = importlib.import_module("scc.drivers." + module)
	except (ImportError, OSError) as e:
		pytest.skip("scc.drivers.%s is not importable here: %s" % (module, e))
	return getattr(mod, cls).flags


# (driver module, controller class, RIGHT is a stick)
# Every controller class carrying its own flags, not one per device: the DS4 and
# DS5 each have three, and which one a given pad gets depends on how it is
# connected, so all three have to agree.
CONTROLLERS = [
	# A right stick and no touchpad beside it in the RIGHT slot -- the DS4/DS5
	# touchpad is CPAD. RIGHT is the stick.
	("ds4drv", "DS4Controller", True),
	("ds4drv", "DS4EvdevController", True),
	("ds4drv", "DS4HidRawController", True),
	("ds5drv", "DS5Controller", True),
	("ds5drv", "DS5EvdevController", True),
	("ds5drv", "DS5HidRawController", True),
	# Both a right stick and a right touchpad. HAS_RSTICK alone would claim the
	# stick REPLACED the pad, which is what broke the SC2 and the Deck.
	("sc2", "SC2Controller", False),
	("steamdeck", "Deck", False),
	# No right stick at all: RIGHT has always been the touchpad.
	("sc_dongle", "SCController", False),
]


@pytest.mark.parametrize(("module", "cls", "expected"), CONTROLLERS)
def test_right_slot_is_what_the_hardware_has(module, cls, expected):
	assert right_is_stick(_flags(module, cls)) is expected


@pytest.mark.parametrize(("module", "cls", "trash"), CONTROLLERS)
def test_has_rpad_is_never_set_alone(module, cls, trash):
	"""HAS_RPAD qualifies HAS_RSTICK; on its own it means nothing, and would
	read as "no right stick" anyway.
	"""
	flags = _flags(module, cls)
	if flags & ControllerFlags.HAS_RPAD:
		assert flags & ControllerFlags.HAS_RSTICK


def test_the_predicate_is_not_just_has_rstick():
	"""The whole point: these two disagree, and the old code used the wrong one."""
	both = ControllerFlags.HAS_RSTICK | ControllerFlags.HAS_RPAD
	assert bool(both & ControllerFlags.HAS_RSTICK)
	assert not right_is_stick(both)
	assert right_is_stick(ControllerFlags.HAS_RSTICK)
	assert not right_is_stick(0)
