# mario-eval runner: ares (pinned) + footprint patch + headless n64run frontend.
# Vulkan is provided by Mesa's lavapipe (CPU), so no GPU is needed; paraLLEl-RDP
# runs on it and is bit-exact with respect to the RDP model it implements.
FROM ubuntu:24.04 AS build
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build git ca-certificates pkg-config \
      libgtk-3-dev libsdl2-dev libgl-dev libx11-dev libxrandr-dev libxi-dev \
      libasound2-dev libpulse-dev libao-dev libopenal-dev libudev-dev \
      libvulkan-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY ARES_COMMIT /src/ARES_COMMIT
RUN git init ares && cd ares \
    && git remote add origin https://github.com/ares-emulator/ares.git \
    && git fetch --depth 1 origin "$(cat /src/ARES_COMMIT)" \
    && git checkout --quiet FETCH_HEAD
COPY patches /src/patches
RUN cd ares && git apply /src/patches/*.patch
COPY CMakeLists.txt n64run.cpp /src/ares/n64run/
RUN cd ares && sed -i 's|^add_subdirectory(desktop-ui)$|add_subdirectory(n64run)|' CMakeLists.txt \
    && cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DARES_CORES=n64 \
         -DARES_SKIP_DEPS=ON -DENABLE_CCACHE=OFF -DARES_ENABLE_LIBRASHADER=OFF \
    && cmake --build build --target n64run \
    && find build -name n64run -type f -perm -u+x -exec cp {} /usr/local/bin/n64run \;

FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      mesa-vulkan-drivers libvulkan1 libgtk-3-0t64 libsdl2-2.0-0 libgl1 \
      libasound2t64 libpulse0 libao4 libopenal1 libudev1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/bin/n64run /usr/local/bin/n64run
ENTRYPOINT ["/usr/local/bin/n64run"]
ENV VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.json
