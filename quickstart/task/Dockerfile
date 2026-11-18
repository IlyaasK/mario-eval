# The container the agent works in: the mario-eval image (toolchain, n64run,
# grader) plus the target game source, public corpus and public-only reference.
# Build context: repository root (stage cache/public-stage via export-public first).
FROM mario-eval
ARG CORPUS_DIR=corpus
ARG GAME_DIR=workload
ARG TASK_DOC=quickstart/task/TASK.md
ARG GAME_TITLE="Pip's Garden baseline"

COPY ${CORPUS_DIR}/grader.json /opt/mario-eval/corpus/grader.json
COPY ${CORPUS_DIR}/replays/public /opt/mario-eval/corpus/replays/public
COPY ${CORPUS_DIR}/variants /opt/mario-eval/corpus/variants
COPY cache/public-stage /opt/mario-eval/reference
COPY tools/mev.py /usr/local/bin/mev

# Non-root `agent` user (uid 1000) + locked empty git hooks directory so the
# agent cannot plant post-commit hooks executed by host checkpointing.
RUN chmod 755 /usr/local/bin/mev \
    && (id -u ubuntu >/dev/null 2>&1 && usermod -l agent -d /home/agent -m ubuntu && groupmod -n agent ubuntu \
        || useradd -m -u 1000 -s /bin/bash agent) \
    && mkdir -p /usr/share/mario-eval/empty-hooks \
    && chmod 0555 /usr/share/mario-eval/empty-hooks \
    && git config --system core.hooksPath /usr/share/mario-eval/empty-hooks \
    && mkdir -p /home/agent/.claude /home/agent/.codex /home/agent/.gemini \
                /home/agent/.config /home/agent/.cache /home/agent/.local/bin \
    && chown -R 1000:1000 /home/agent

COPY --chown=1000:1000 ${GAME_DIR} /task/game
COPY --chown=root:root --chmod=0444 ${TASK_DOC} /task/TASK.md
COPY --chown=root:root quickstart/task/docs /task/docs
RUN chmod -R a-w,a+rX /task/docs \
    && echo console > /task/PROFILE \
    && chown 1000:1000 /task /task/PROFILE

# Verify zero held-out data or retail ROM images exist anywhere in the image.
RUN python3 -c 'import json, pathlib; ref = pathlib.Path("/opt/mario-eval/reference"); idx = json.loads((ref / "index.json").read_text()); assert all(not k.startswith("heldout") for k in idx.get("workloads", {})), "heldout leaked in index.json"; assert not list(ref.rglob("heldout*")), "heldout files leaked in reference"; assert not list(pathlib.Path("/task/game").rglob("*.z64")), "ROM file leaked in /task/game"'

USER agent
ENV HOME=/home/agent
RUN cd /task/game && rm -rf .git build build_* *.z64 \
    && printf 'build/\nbuild_*/\n*.z64\n' >> .gitignore \
    && git init -q -b main \
    && git -c user.name=baseline -c user.email=baseline@mario-eval add -A \
    && git -c user.name=baseline -c user.email=baseline@mario-eval commit -qm "${GAME_TITLE}"
WORKDIR /task
