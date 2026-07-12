#!/bin/bash -e
# Seed this stage's rootfs from the previous stage (stage2 / Bookworm Lite).
# Every pi-gen stage needs this; without it ${ROOTFS_DIR} is empty and the
# chroot steps fail with "Unable to chroot".
if [ ! -d "${ROOTFS_DIR}" ]; then
	copy_previous
fi
