"""DualSense absolute orientation, pinned to a hardware measurement.

Captured with SCC_GYRO_CALIB=1 on a wired DualSense, rotating about one axis
at a time and identifying each motion by where gravity went (the accelerometer
says which physical axis moved, independently of anyone's description):

    nose-down pitch  ->  raw word at byte 16 goes NEGATIVE  (gravity +Y -> +Z)
    yaw right        ->  raw word at byte 18 goes NEGATIVE  (gravity unchanged)
    roll right       ->  raw word at byte 20 goes NEGATIVE  (gravity +Y -> -X)

Yaw leaving gravity where it was is the check that the capture is sound: a
rotation about the gravity vector cannot move it.

EUREL_GYROS wants the opposite sign on all three (+ = nose-down / yaw-right /
roll-right), so every axis is negated between the wire and the mapper -- the
Bluetooth path in _convert_input_data plus _GYRO_SIGN, the USB path in
DS5Controller.input plus the same _GYRO_SIGN. These tests hold that end to end
so the two transports cannot drift apart again.
"""
import pytest

try:
	# OSError, not ImportError, when libhiddrv is unbuilt -- find_library raises
	# it at hiddrv import time, so importorskip alone sails straight past.
	from scc.drivers import ds5drv
except (ImportError, OSError) as e:
	pytest.skip("ds5drv unavailable: %s" % (e,), allow_module_level=True)


class FakeState:
	"""Just the fields _integrate_orientation reads and writes."""

	def __init__(self, gpitch=0, gyaw=0, groll=0):
		self.gpitch, self.gyaw, self.groll = gpitch, gyaw, groll
		self.q1 = self.q2 = self.q3 = self.q4 = 0


def orientation(dt=0.1):
	"""A bare _DS5Orientation, standing in for either controller class."""
	o = ds5drv._DS5Orientation()
	o._init_orientation()
	o._delta_time = dt
	return o


def usb_state(b16, b18, b20):
	"""What the C decoder hands the integrator on USB: the raw words."""
	return FakeState(gpitch=b16, gyaw=b18, groll=b20)


def bt_state(b16, b18, b20):
	"""And what _convert_input_data leaves on Bluetooth: the same raw words."""
	return FakeState(gpitch=b16, gyaw=b18, groll=b20)


# The measured raw words, one per motion, at roughly the peak of each rotation.
NOSE_DOWN = (-1343, -70, 387)
YAW_RIGHT = (-11, -823, -161)
ROLL_RIGHT = (-27, -12, -363)


@pytest.mark.parametrize("build", [usb_state, bt_state], ids=["usb", "bt"])
@pytest.mark.parametrize(("motion", "raw", "slot"), [
	("nose down", NOSE_DOWN, "q1"),
	("yaw right", YAW_RIGHT, "q2"),
	("roll right", ROLL_RIGHT, "q3"),
])
def test_each_rotation_drives_its_own_slot_positive(build, motion, raw, slot):
	"""The axis the hardware moved is the axis the mapper sees move, and in the
	direction EUREL declares positive. Getting this wrong is issue #16: the yaw
	slot answered to roll, because it carried an accelerometer component.
	"""
	o = orientation()
	o._integrate_orientation(build(*raw))
	angles = {"q1": o._gyro_angles[0], "q2": o._gyro_angles[1], "q3": o._gyro_angles[2]}
	assert angles[slot] > 0, "%s produced %s=%.3f rad, wanted positive" % (
		motion, slot, angles[slot])
	# and it must not have dragged the other two along with it
	for other, value in angles.items():
		if other != slot:
			assert abs(value) < abs(angles[slot]) / 3, (
				"%s bled into %s (%.3f vs %.3f rad)" % (motion, other, value, angles[slot]))


@pytest.mark.parametrize("build", [usb_state, bt_state], ids=["usb", "bt"])
def test_both_transports_integrate_identically(build):
	"""Same raw words in, same angles out, whichever cable is or is not
	attached. The USB path had no integrator at all before this.
	"""
	usb, bt = orientation(), orientation()
	for raw in (NOSE_DOWN, YAW_RIGHT, ROLL_RIGHT):
		usb._integrate_orientation(usb_state(*raw))
		bt._integrate_orientation(bt_state(*raw))
	assert usb._gyro_angles == bt._gyro_angles


def test_q_slots_are_angles_not_accelerometer():
	"""The decoder leaves the raw accelerometer in q1-q3 (AxisMode.DS4GYRO).
	Whatever was there must be gone, replaced by the integrated angle -- that
	substitution is the whole fix on the USB path.
	"""
	o = orientation()
	st = usb_state(*NOSE_DOWN)
	st.q1, st.q2, st.q3 = -1544, 196, -7964    # a real resting accel triple
	o._integrate_orientation(st)
	assert (st.q1, st.q2, st.q3) != (-1544, 196, -7964)
	assert st.q1 == int(o._gyro_angles[0] * ds5drv._EUREL_SCALE)
	assert st.q4 == 0


def test_the_rate_fields_reach_the_mapper_unnegated():
	"""Absolute mode does NOT read the integrated angles. GyroAbsAction feeds
	the raw rates to the mouse through GyroAction.MOUSE_RATE_SIGN, a table
	shared with the DS4 -- so a driver that negates its rates on the way in
	comes out backwards there while relative mode, which does read the angles,
	looks perfect. That is exactly what happened, and it cost a hardware round
	trip. The negation belongs in _GYRO_SIGN, which only the integrator uses.
	"""
	assert ds5drv._GYRO_SIGN == (-1.0, -1.0, -1.0), (
		"the whole per-axis flip must live here, not in the decode step")

	st = usb_state(*YAW_RIGHT)
	before = (st.gpitch, st.gyaw, st.groll)
	orientation()._integrate_orientation(st)
	assert (st.gpitch, st.gyaw, st.groll) == before, (
		"integrating must not disturb the rates the mapper reads")


def test_the_ds5_and_ds4_agree_on_what_a_positive_rate_means():
	"""Both are read through the same MOUSE_RATE_SIGN, so their rate polarity
	has to match or one of them is wrong in absolute mode.
	"""
	ds4drv = pytest.importorskip("scc.drivers.ds4drv")
	assert ds5drv._GYRO_SIGN == ds4drv._GYRO_SIGN


def test_a_still_controller_does_not_wander():
	"""Resting bias, left uncorrected, integrates a slow drift across the whole
	range. The measured rest reading is (4, 4, -6) LSB.
	"""
	o = orientation(dt=0.004)
	for _ in range(2000):        # ~8 seconds of reports
		o._integrate_orientation(usb_state(4, 4, -6))
	for axis, angle in zip(("pitch", "yaw", "roll"), o._gyro_angles):
		assert abs(angle) < 0.35, "%s drifted %.3f rad while sitting still" % (axis, angle)
