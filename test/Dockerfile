FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    bash \
    device-tree-compiler \
    python3 \
    python3-yaml \
    python3-libfdt \
    && rm -rf /var/lib/apt/lists/*

# Allow sudo as root (passthrough)
RUN echo "ALL ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers 2>/dev/null || true

WORKDIR /repo
