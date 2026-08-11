"""Hotplug bookkeeping in DeviceMonitor.

Bluetooth reconnects were broken in three separate ways at once, all of them
invisible without a controller to pair and unpair. These drive on_data_ready
with synthesized udev events, which needs no hardware and no udev.

The syspaths below are the real ones a DualShock 4 produces on this machine.
Note the HCI handle: it ALTERNATES between connections, which is what made the
stale-entry bug permanent rather than transient.
"""
from collections import namedtuple

import pytest

# scc.device_monitor needs ioctl_opt, a real runtime dependency that a minimal
# build environment may not have installed yet. Not being able to check this
# here is a skip, not a failure.
DeviceMonitor = pytest.importorskip("scc.device_monitor").DeviceMonitor

HCI_50 = ("/sys/devices/pci0000:00/0000:00:02.1/0000:04:00.0/0000:05:08.0/"
          "0000:0b:00.0/0000:0c:0c.0/0000:15:00.0/usb1/1-12/1-12:1.0/bluetooth/hci0/hci0:50")
HCI_51 = HCI_50[:-1] + "1"

Event = namedtuple("Event", "action node initialized subsystem devtype syspath devnum")


def _event(action, syspath, subsystem="bluetooth", initialized=True):
	return Event(action, None, initialized, subsystem, "link", syspath, 0)


class FakeMonitor(DeviceMonitor):
	"""DeviceMonitor without the eudev machinery underneath it."""

	# eudevmonitor's __del__ pokes self._monitor; we never ran its __init__
	_monitor = None

	def __init__(self):
		self.daemon = None
		self.dev_added_cbs = {}
		self.dev_removed_cbs = {}
		self.bt_addresses = {}
		self.known_devs = {}
		self._queue = []
		self.created = []

	# -- stubs for everything on_data_ready reaches ------------------------
	def receive_device(self):
		return self._queue.pop(0) if self._queue else None

	def _get_hci_addresses(self):
		pass

	def get_vendor_product(self, syspath, subsystem=None):
		return 0x054C, 0x09CC

	def feed(self, event):
		self._queue.append(event)
		self.on_data_ready()


class FakeController:
	"""Stands in for DS4HidRawController: its close() is registered through
	add_remove_callback, which is where the argument-count bug lived.
	"""

	def __init__(self, syspath):
		self.syspath = syspath
		self.closed = 0

	def close(self, *a):
		self.closed += 1


@pytest.fixture
def mon():
	m = FakeMonitor()

	def added(syspath, vendor, product):
		c = FakeController(syspath)
		m.created.append(c)
		m.add_remove_callback(syspath, c.close)
		return c

	m.dev_added_cbs[("bluetooth", 0x054C, 0x09CC)] = added
	m.dev_removed_cbs[("bluetooth", 0x054C, 0x09CC)] = None
	return m


def test_a_controller_is_created_on_connect(mon):
	mon.feed(_event("add", HCI_50))
	assert len(mon.created) == 1
	assert HCI_50 in mon.known_devs


def test_disconnect_closes_the_controller(mon):
	"""The remove callback is invoked with (syspath, vendor, product). close()
	took no arguments, so this raised TypeError -- inside a poller callback that
	nothing catches, so the daemon died AND the controller stayed open.
	"""
	mon.feed(_event("add", HCI_50))
	mon.feed(_event("remove", HCI_50))

	assert mon.created[0].closed == 1
	assert HCI_50 not in mon.known_devs


def test_reconnect_on_the_same_handle_is_not_swallowed(mon):
	"""The bug that made a re-paired controller inert.

	Bluetooth handles alternate, so the remove names a handle we never
	registered and the entry for the one we DID register is never cleared.
	Every later add for that syspath then hit `if syspath not in known_devs`
	and was dropped: the daemon still listed the dead controller, so it looked
	connected while delivering nothing.
	"""
	mon.feed(_event("add", HCI_50))
	mon.feed(_event("remove", HCI_51))      # the OTHER handle -- matches nothing
	assert HCI_50 in mon.known_devs, "precondition: the stale entry survives"

	mon.feed(_event("add", HCI_50))         # same handle comes back

	assert len(mon.created) == 2, "reconnect was swallowed by the stale entry"
	assert mon.created[0].closed == 1, "the dead controller was left registered"


def test_no_syspath_ever_holds_two_live_controllers(mon):
	"""Repeated cycles must not pile up controllers on the same syspath.

	Eviction is per-syspath, so with handles alternating this settles at one
	live controller per handle -- the one on the handle NOT currently in use is
	dead but still registered. The monitor cannot tell: it never saw a remove
	for it. Cleaning that up is the driver's job, via the failing read in
	DS4HidRawController._input, which no longer just returns.
	"""
	for syspath in (HCI_50, HCI_51, HCI_50, HCI_51, HCI_50):
		mon.feed(_event("add", syspath))

	assert len(mon.created) == 5
	assert len(mon.known_devs) == 2, "one entry per handle, not one per connection"
	live = [c for c in mon.created if not c.closed]
	assert len(live) == 2
	assert {c.syspath for c in live} == {HCI_50, HCI_51}
	assert mon.created[-1] in live, "the newest connection must be the live one"


def test_a_remove_that_does_match_still_closes(mon):
	"""The half that works: when the handle does line up, the entry goes and the
	controller is closed, leaving nothing behind.
	"""
	mon.feed(_event("add", HCI_50))
	mon.feed(_event("add", HCI_51))
	mon.feed(_event("remove", HCI_50))
	mon.feed(_event("remove", HCI_51))

	assert all(c.closed for c in mon.created)
	assert mon.known_devs == {}


def test_a_raising_callback_cannot_kill_the_daemon(mon):
	"""on_data_ready runs inside Poller.poll, which catches nothing, and
	SCCDaemon.run catches nothing either. A callback that raises used to take
	the whole daemon down -- every controller and the OSD with it.
	"""
	def added(syspath, vendor, product):
		c = FakeController(syspath)
		mon.created.append(c)
		mon.add_remove_callback(syspath, lambda *a: 1 / 0)
		return c

	mon.dev_added_cbs[("bluetooth", 0x054C, 0x09CC)] = added
	mon.feed(_event("add", HCI_50))
	mon.feed(_event("remove", HCI_50))       # must not propagate

	assert HCI_50 not in mon.known_devs, "the entry must go even if close() fails"


def test_an_uninitialized_add_is_still_ignored(mon):
	mon.feed(_event("add", HCI_50, initialized=False))
	assert not mon.created
