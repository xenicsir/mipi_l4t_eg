# arm64 Ubuntu image for Phase 3 — native dpkg -i of EG .debs under qemu-aarch64.
#
# Requires `qemu-user-static` on the host with binfmt_misc registered (check with
# `docker run --rm --platform=linux/arm64 arm64v8/ubuntu:22.04 uname -m` → aarch64).
#
# This image is the target of every per-package install test. It intentionally
# matches the runtime deps expected by the package's preinst/postinst.
FROM arm64v8/ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    coreutils \
    device-tree-compiler \
    file \
    python3 \
    python3-yaml \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Allow sudo passthrough (NOPASSWD) — our scripts do 'sudo /opt/eg/jetson-io/...'
RUN echo "ALL ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

WORKDIR /work
