#!/usr/bin/env python3
"""Compute the `hash` that package.nix needs, without having nix installed.

`fetchFromGitHub`'s `hash` is not a hash of the tarball. Nix downloads the
GitHub tarball for a rev, unpacks it stripping the top-level directory, and
hashes the *NAR serialization* of the resulting tree. So `sha256sum` on the
tarball gives a different, useless value, and the hash cannot be known before
the tag exists -- bumping package.nix necessarily lands after the release.

The documented way to get it is to set `hash = lib.fakeHash;`, run a build,
and copy the value out of the mismatch error. That needs nix. This script is
for the case where the person cutting the release does not have it.

    ./scripts/nar-hash.py --self-test        # prove the implementation first
    ./scripts/nar-hash.py v0.6.0.9           # then hash the new tag

ALWAYS run --self-test before trusting a value. It recomputes the hash of a
tag whose correct answer is known and pinned below, which catches the failure
mode that matters: a subtly wrong serialization produces a confident,
plausible, wrong hash, and the first person to hit it is a user whose build
breaks. A pass means the serialization agrees with nix's on a real tree of
this repository -- not a proof, but it is the check that would fail if
anything here were wrong.

The NAR format (Dolstra's thesis, appendix E; nix/src/libutil/archive.cc):

    every string is  <8-byte LE length><bytes><zero padding to a multiple of 8>
    serialize(fso)   = str("nix-archive-1") node(fso)
    node(regular)    = str("(") str("type") str("regular")
                       [str("executable") str("")]
                       str("contents") str(data) str(")")
    node(symlink)    = str("(") str("type") str("symlink")
                       str("target") str(target) str(")")
    node(directory)  = str("(") str("type") str("directory")
                         for each entry, sorted bytewise by name:
                           str("entry") str("(") str("name") str(name)
                           str("node") node(child) str(")")
                       str(")")

Only the executable bit of the mode is recorded. Owners, groups, timestamps
and non-executable permission bits are deliberately not, which is why the
result does not depend on the umask of whoever runs this.
"""
import argparse
import base64
import hashlib
import os
import subprocess
import sys
import tempfile

REPO = "https://github.com/Patola/sc-controller-cc"

# A tag whose hash nix itself produced, kept as the self-test fixture. Do not
# "update" this to a newer tag unless the new value came from nix (a fakeHash
# mismatch error), or the test starts confirming this script against itself.
SELF_TEST_TAG = "v0.6.0.5"
SELF_TEST_HASH = "sha256-xPJNaetU0Ekpo9H0WPI+dMxXRPQwJUScND3B2sQli4k="


def _str(h, b) -> None:
	if isinstance(b, str):
		b = b.encode()
	h.update(len(b).to_bytes(8, "little"))
	h.update(b)
	pad = (8 - len(b) % 8) % 8
	if pad:
		h.update(b"\0" * pad)


def _node(h, path: str) -> None:
	_str(h, "(")
	if os.path.islink(path):
		_str(h, "type")
		_str(h, "symlink")
		_str(h, "target")
		_str(h, os.readlink(path).encode())
	elif os.path.isdir(path):
		_str(h, "type")
		_str(h, "directory")
		# bytewise on the encoded name: nix compares raw bytes, and a locale
		# aware sort would order non-ASCII names differently
		for name in sorted(os.listdir(path), key=lambda n: n.encode()):
			_str(h, "entry")
			_str(h, "(")
			_str(h, "name")
			_str(h, name.encode())
			_str(h, "node")
			_node(h, os.path.join(path, name))
			_str(h, ")")
	else:
		_str(h, "type")
		_str(h, "regular")
		if os.lstat(path).st_mode & 0o100:
			_str(h, "executable")
			_str(h, "")
		with open(path, "rb") as f:
			data = f.read()
		_str(h, "contents")
		_str(h, data)
	_str(h, ")")


def nar_sri(path: str) -> str:
	"""SRI-encoded sha256 of the NAR serialization of the tree at `path`."""
	h = hashlib.sha256()
	_str(h, "nix-archive-1")
	_node(h, path)
	return "sha256-" + base64.b64encode(h.digest()).decode()


def hash_tag(tag: str) -> str:
	"""Fetch a tag's GitHub tarball the way fetchFromGitHub does, and hash it."""
	with tempfile.TemporaryDirectory() as tmp:
		url = "%s/archive/%s.tar.gz" % (REPO, tag)
		curl = subprocess.run(["curl", "-fsSL", url], capture_output=True)
		if curl.returncode != 0:
			sys.exit("failed to download %s: %s" % (url, curl.stderr.decode().strip()))
		tar = subprocess.run(
			["tar", "xz", "-C", tmp, "--strip-components=1"],
			input=curl.stdout, capture_output=True,
		)
		if tar.returncode != 0:
			sys.exit("failed to unpack %s: %s" % (url, tar.stderr.decode().strip()))
		return nar_sri(tmp)


def main() -> int:
	p = argparse.ArgumentParser(description=__doc__,
		formatter_class=argparse.RawDescriptionHelpFormatter)
	p.add_argument("tag", nargs="?", help="tag to hash, e.g. v0.6.0.9")
	p.add_argument("--self-test", action="store_true",
		help="check this script against a hash nix itself produced")
	args = p.parse_args()

	if args.self_test:
		got = hash_tag(SELF_TEST_TAG)
		ok = got == SELF_TEST_HASH
		print("%s\n  got:  %s\n  want: %s\n%s" % (
			SELF_TEST_TAG, got, SELF_TEST_HASH,
			"PASS" if ok else "FAIL -- do not use this script's output"))
		if not ok or not args.tag:
			return 0 if ok else 1

	if not args.tag:
		p.error("give a tag to hash, or --self-test")
	print(hash_tag(args.tag))
	return 0


if __name__ == "__main__":
	sys.exit(main())
