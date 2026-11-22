# mario-eval: one image with everything grading needs.
#   - pinned libdragon toolchain (trusted rebuild of submissions)
#   - n64run (ares + mario-eval instrumentation, CPU interpreter, lavapipe)
#   - the grader
# Build the two component images first:
#   docker build -t mario-eval-toolchain toolchain/
#   docker build -t mario-eval-runner runner/
ARG RUNNER_IMAGE=mario-eval-runner
FROM ${RUNNER_IMAGE} AS runner

FROM mario-eval-toolchain
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      mesa-vulkan-drivers libvulkan1 libgtk-3-0t64 libsdl2-2.0-0 libgl1 \
      libasound2t64 libpulse0 libao4 libopenal1 libudev1 \
      python3-numpy \
    && rm -rf /var/lib/apt/lists/*
COPY --from=runner /usr/local/bin/n64run /usr/local/bin/n64run
ENV VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.json
COPY grader /opt/mario-eval/grader
COPY tools /opt/mario-eval/tools
ENV PYTHONPATH=/opt/mario-eval
WORKDIR /work
