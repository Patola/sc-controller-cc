# syntax=docker/dockerfile:1
ARG BASE_OS=ubuntu
ARG BASE_CODENAME=noble
FROM $BASE_OS:$BASE_CODENAME AS build-stage

# Download build dependencies
RUN <<EOR
	set -eu

	# jammy used to need python3-build from jammy-proposed, to work around
	# https://bugs.launchpad.net/ubuntu/+source/python-build/+bug/1992108. That
	# fix has since been SRU'd into jammy-updates (0.7.0-2ubuntu0.1) and the
	# package is no longer in proposed at all, so the workaround is not just
	# unnecessary, it is actively harmful: it enabled ONLY proposed's universe,
	# at the same priority as the release pockets, so apt would happily upgrade
	# a universe package to its proposed version while the matching main-pocket
	# dependency stayed invisible. That is exactly how the v0.6.0.7 build broke:
	#
	#   python3.10-venv : Depends: python3.10 (= 3.10.12-1~22.04.17)
	#                     but 3.10.12-1~22.04.16 is to be installed
	#   E: Unable to correct problems, you have held broken packages.
	#
	# Reproduced in a plain ubuntu:jammy container, and verified fixed by this
	# removal: the whole dependency set installs, python3-build imports, and
	# python3 -m venv works.

	apt-get update
	export DEBIAN_FRONTEND=noninteractive
	apt-get install -y --no-install-recommends \
		gcc \
		git \
		librsvg2-bin \
		libxfixes3 \
		linux-headers-generic \
		python3-build \
		python3-dev \
		python3-setuptools \
		python3-usb \
		python3-venv \
		python-is-python3

	apt-get clean && rm -rf /var/lib/apt/lists/*
EOR
# Prepare working directory and target
COPY . /work
WORKDIR /work
ARG TARGET=/build

# Build and install
RUN <<EOR
	set -eu

	python -m build --wheel
	python -m venv .env
	. .env/bin/activate
	# ioctl_opt is a real runtime dependency (device_monitor, lib/hidraw), so a
	# test that imports either needs it here -- the wheel that would pull it in
	# is not installed until after this test run.
	pip install libusb1 pytest vdf ioctl_opt
	# Tests need Python 3.11+, which jammy (3.10) lacks. os-release must be
	# sourced HERE: each RUN is a fresh shell, so the previous RUN's sourcing
	# doesn't carry over -- the old unquoted, unset ${UBUNTU_CODENAME} made
	# this test error out and silently skip the suite on EVERY base.
	. /etc/os-release
	if [ "${UBUNTU_CODENAME-}" != 'jammy' ]; then
		python -m pytest tests
	fi
	# --ignore-requires-python: the wheel declares the >=3.11 source-install
	# floor, but the jammy AppImage bundles jammy's Python 3.10, where the
	# runtime is deliberately kept working (the enums use the functional
	# IntEnum API); without the flag pip refuses the install on jammy.
	pip install --prefix "${TARGET}/usr" --no-warn-script-location --ignore-requires-python dist/*.whl

	# Save version
	PYTHONPATH=$(find "${TARGET}" -type d -name site-packages) \
	python -c "from scc.constants import DAEMON_VERSION; print('VERSION=' + DAEMON_VERSION)" >>/build/.build-metadata.env

	# Fix shebangs of scripts from '#!/work/.env/bin/python'
	find "${TARGET}/usr/bin" -type f | xargs sed -i 's:work/.env:usr:'

	# Provide input-event-codes.h as fallback for runtime systems without linux headers
	cp -a \
		"$(find /usr -type f -name input-event-codes.h -print -quit)" \
		"$(find "${TARGET}" -type f -name uinput.py -printf '%h\n' -quit)"

	# Create short name symlinks for static libraries
	suffix=".cpython-*-$(uname -m)-linux-gnu.so"
	find "${TARGET}" -type f -path "*/site-packages/*${suffix}" \
		| while read -r path; do ln -sfr "${path}" "${path%${suffix}}.so"; done

	share="${TARGET}/usr/share"

	# Put AppStream metadata to required location according to https://wiki.debian.org/AppStream/Guidelines
	metainfo="${share}/metainfo"
	mkdir -p "${metainfo}"
	cp -a scripts/sc-controller.appdata.xml "${metainfo}"

	# Convert icon to png format (required for icons in .desktop file)
	iconpath="${share}/icons/hicolor/512x512/apps"
	mkdir -p "${iconpath}"
	rsvg-convert --background-color none -o "${iconpath}/sc-controller.png" images/sc-controller.svg
EOR

# Store build metadata
ARG TARGETOS TARGETARCH TARGETVARIANT
RUN export "TARGETMACHINE=$(uname -m)" && printenv | grep ^TARGET >>/build/.build-metadata.env

# Keep only files required for runtime
FROM scratch AS export-stage
COPY --from=build-stage /build /
