"""Taking the kernel's evdev nodes away from libinput.

Opening /dev/hidrawN does not displace the kernel's HID driver, so on the
Bluetooth path hid-playstation stays bound and keeps publishing evdev nodes for
the same pad. The DS4's touchpad node arrives as a multitouch device, which
libinput drives as a real touchpad: pointer acceleration and coasting we never
asked for, and a clickpad button mapping that overrides whatever the pad is
bound to -- so the touchpad looked unconfigurable. USB does not have the
problem, because claiming the interface through libusb detaches the driver.

These drive the helper with stub devices; a real grab needs hardware.
"""
import os

import pytest

from scc.drivers import evdevdrv


class FakeDevice:
	def __init__(self, path, name="pad", fails=False):
		self.path = path
		self.name = name
		self.grabbed = False
		self.ungrabbed = False
		self.closed = False
		self._fails = fails

	def grab(self):
		if self._fails:
			raise OSError(16, "Device or resource busy")
		self.grabbed = True

	def ungrab(self):
		if not self.grabbed:
			raise OSError(22, "Invalid argument")
		self.ungrabbed = True

	def close(self):
		self.closed = True


@pytest.fixture
def nodes(monkeypatch):
	found = [
		FakeDevice("/dev/input/event20", "Wireless Controller"),
		FakeDevice("/dev/input/event21", "Wireless Controller Touchpad"),
		FakeDevice("/dev/input/event22", "Wireless Controller Motion Sensors"),
	]
	by_path = {d.path: d for d in found}
	monkeypatch.setattr(evdevdrv, "HAVE_EVDEV", True)
	monkeypatch.setattr(evdevdrv, "evdev_nodes_from_hidraw", lambda p: list(by_path))
	monkeypatch.setattr(evdevdrv, "evdev", type("m", (), {"InputDevice": staticmethod(by_path.get)}))
	return found


def test_every_node_is_grabbed(nodes):
	"""Including the gamepad node itself: left ungrabbed, the kernel delivers
	the buttons and sticks a second time alongside our emulated pad.
	"""
	grabbed = evdevdrv.grab_evdev_nodes("/dev/hidraw22")
	assert grabbed == nodes
	assert all(d.grabbed for d in nodes)


def test_a_node_that_cannot_be_grabbed_does_not_stop_the_others(nodes):
	"""One busy node is worth a warning, not a controller that refuses to work."""
	nodes[1]._fails = True
	grabbed = evdevdrv.grab_evdev_nodes("/dev/hidraw22")

	assert nodes[1] not in grabbed
	assert nodes[1].closed, "a node we could not grab must not be left open"
	assert [d.path for d in grabbed] == [nodes[0].path, nodes[2].path]


def test_nothing_is_grabbed_without_evdev(monkeypatch):
	monkeypatch.setattr(evdevdrv, "HAVE_EVDEV", False)
	assert evdevdrv.grab_evdev_nodes("/dev/hidraw22") == []


def test_enumeration_failure_is_not_fatal(monkeypatch):
	def boom(hidraw_path):
		raise OSError("no such device")

	monkeypatch.setattr(evdevdrv, "HAVE_EVDEV", True)
	monkeypatch.setattr(evdevdrv, "evdev_nodes_from_hidraw", boom)
	assert evdevdrv.grab_evdev_nodes("/dev/hidraw99") == []


def test_ungrab_hands_everything_back_and_closes_it(nodes):
	grabbed = evdevdrv.grab_evdev_nodes("/dev/hidraw22")
	evdevdrv.ungrab_evdev_nodes(grabbed)
	assert all(d.ungrabbed and d.closed for d in nodes)


def test_ungrab_survives_a_device_that_already_went_away(nodes):
	"""The usual case: this runs on disconnect, so the node is often gone."""
	grabbed = evdevdrv.grab_evdev_nodes("/dev/hidraw22")
	nodes[0].grabbed = False   # ungrab() will raise, as it does on a dead node
	evdevdrv.ungrab_evdev_nodes(grabbed)
	assert nodes[1].ungrabbed
	assert all(d.closed for d in nodes)


def test_ungrab_accepts_nothing_at_all():
	evdevdrv.ungrab_evdev_nodes(None)
	evdevdrv.ungrab_evdev_nodes([])


def _fake_sysfs(tmp_path, monkeypatch, inputs):
	"""Builds the sysfs shape a DS4 paired over Bluetooth really has."""
	hid = tmp_path / "devices" / "virtual" / "misc" / "uhid" / "0005:054C:09CC.034B"
	for input_dir, nodes in inputs.items():
		for node in nodes:
			(hid / "input" / input_dir / node).mkdir(parents=True)
	(hid / "hidraw" / "hidraw22").mkdir(parents=True)
	cls = tmp_path / "class" / "hidraw" / "hidraw22"
	cls.mkdir(parents=True)
	(cls / "device").symlink_to(hid)
	monkeypatch.setattr(evdevdrv, "SYS_CLASS_HIDRAW", str(tmp_path / "class" / "hidraw"))
	return hid


def test_nodes_are_found_through_the_hidraw_device(tmp_path, monkeypatch):
	"""The first attempt used get_evdev_devices_from_syspath on the syspath the
	driver callback receives. Over Bluetooth that is the HCI path, which holds
	nothing but device/, power/, subsystem/ and uevent -- the controller itself
	lives under /sys/devices/virtual/misc/uhid/. So it enumerated nothing,
	grabbed nothing, said nothing, and the kernel kept driving the touchpad.
	The hidraw node is the one handle we are certain to be holding.
	"""
	hid = _fake_sysfs(tmp_path, monkeypatch, {
		"input1045": ["event10"], "input1046": ["event13"], "input1047": ["event14"]})
	# sysfs keeps plain attribute files in the same directories
	(hid / "input" / "input1045" / "event_count").write_text("0")

	assert evdevdrv.evdev_nodes_from_hidraw("/dev/hidraw22") == [
		"/dev/input/event10", "/dev/input/event13", "/dev/input/event14"]


def test_a_device_with_no_input_nodes_yields_nothing(tmp_path, monkeypatch):
	_fake_sysfs(tmp_path, monkeypatch, {})
	assert evdevdrv.evdev_nodes_from_hidraw("/dev/hidraw22") == []
