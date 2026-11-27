# N64 MIPS64 cross-compilation toolchain for Super Mario 64 (hash-pinned
# prebuilt GCC MIPS64 package providing mips64-elf-gcc/ld/objcopy/nm/objdump).
FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
ARG TOOLCHAIN_SHA256=fac8e6572493a66468b7d45df41b042f90b1a630ec96aa218bd5fb1f320a0a4d
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential bsdextrautils git ca-certificates curl python3 \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/tc.deb https://github.com/DragonMinded/libdragon/releases/download/toolchain-continuous-prerelease/gcc-toolchain-mips64-x86_64.deb \
    && echo "${TOOLCHAIN_SHA256}  /tmp/tc.deb" | sha256sum -c - \
    && dpkg -i /tmp/tc.deb && rm /tmp/tc.deb
ENV N64_INST=/opt/libdragon
ENV PATH=/opt/libdragon/bin:$PATH
WORKDIR /work
