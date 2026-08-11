"""The feedback_effect struct is defined twice, and both copies must agree.

scc/uinput.c declares it in C; scc/uinput.py redeclares it as a ctypes
Structure that reads the very same bytes. Nothing links the two, so adding a
field to one and not the other does not fail to build -- it silently
misinterprets every force-feedback effect the daemon reads, which is how
rumble reaches the drivers.

Parsed from source rather than from the compiled library on purpose: this has
to hold on a machine that has not built the extension, and a build that IS
present may be a stale one shadowing the tree (see find_library in scc/tools).
"""
import ctypes
import pathlib
import re

from scc.uinput import FeedbackEvent

C_TO_CTYPES = {
	"bool": ctypes.c_bool,
	"int8_t": ctypes.c_int8,
	"uint8_t": ctypes.c_uint8,
	"int16_t": ctypes.c_int16,
	"uint16_t": ctypes.c_uint16,
	"int32_t": ctypes.c_int32,
	"uint32_t": ctypes.c_uint32,
}


def _fields_from_c():
	source = (pathlib.Path(__file__).parent.parent / "scc" / "uinput.c").read_text()
	body = re.search(r"struct feedback_effect\s*\{(.*?)\}\s*;", source, re.DOTALL)
	assert body, "struct feedback_effect not found in scc/uinput.c"
	fields = []
	for line in body.group(1).splitlines():
		line = line.split("//")[0].strip()
		match = re.fullmatch(r"(\w+)\s+(\w+)\s*;", line)
		if match:
			ctype, name = match.groups()
			assert ctype in C_TO_CTYPES, "unhandled C type %r; add it to C_TO_CTYPES" % (ctype,)
			fields.append((name, C_TO_CTYPES[ctype]))
	return fields


def test_c_and_python_declare_the_same_fields_in_the_same_order():
	assert _fields_from_c() == list(FeedbackEvent._fields_)


def test_the_rumble_magnitudes_are_present():
	"""Named explicitly: they were appended after the fact, and dropping them
	is what would make the heavy and light motors feel identical again.
	"""
	names = [name for name, trash in FeedbackEvent._fields_]
	assert "strong" in names
	assert "weak" in names
	# appended at the end, so an older build still reads level/duration right
	assert names[-2:] == ["strong", "weak"]
