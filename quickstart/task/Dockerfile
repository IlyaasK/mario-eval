# Split leaf image (<1 MB context, 0 container spawns, --provenance=false):
# Editing grader/, tools/mev.py, spec/, grader.json, or TASK.md rebuilds
# mario-eval-task in ~1 second without scanning the ~850 MB SM64/cache tree.
ARG BASE_IMAGE=mario-eval-task-base:latest
ARG GRADER_IMAGE=mario-eval:latest
FROM ${GRADER_IMAGE} AS grader_latest
FROM ${BASE_IMAGE}

USER root
COPY --from=grader_latest /opt/mario-eval/grader /opt/mario-eval/grader
COPY --from=grader_latest /opt/mario-eval/tools /opt/mario-eval/tools
COPY --chown=root:root rootfs/ /
RUN install -d -o 1000 -g 1000 /home/agent/.gemini/config /home/agent/.config/opencode /home/agent/.kimi-code

USER agent
ENV HOME=/home/agent
WORKDIR /task/game
