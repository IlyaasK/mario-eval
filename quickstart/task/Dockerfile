# The container the agent works in: the mario-eval image (toolchain, n64run,
# grader) plus the target game source, public corpus and public-only reference.
# Build context: repository root (stage cache/public-stage via export-public first).
FROM mario-eval
ARG CORPUS_DIR=corpus
ARG GAME_DIR=workload
ARG TASK_DOC=quickstart/task/TASK.md
ARG GAME_TITLE="Pip's Garden baseline"

COPY ${CORPUS_DIR}/grader.json /opt/mario-eval/corpus/grader.json
RUN python3 -c 'import json, pathlib; p = pathlib.Path("/opt/mario-eval/corpus/grader.json"); d = json.loads(p.read_text()); d.pop("o2_reference_patch", None); p.write_text(json.dumps(d, indent=2) + "\n")'
COPY ${CORPUS_DIR}/replays/public /opt/mario-eval/corpus/replays/public
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
    && git config --system user.name "agent" \
    && git config --system user.email "agent@mario-eval" \
    && mkdir -p /home/agent/.claude /home/agent/.codex /home/agent/.gemini \
                /home/agent/.config /home/agent/.cache /home/agent/.local/bin \
    && chown -R 1000:1000 /home/agent

COPY --chown=1000:1000 ${GAME_DIR} /task/game
COPY --chown=root:root --chmod=0444 ${TASK_DOC} /task/TASK.md
COPY --chown=root:root quickstart/task/docs /task/docs
RUN chmod -R a-w,a+rX /task/docs \
    && echo console > /task/PROFILE \
    && chown 1000:1000 /task /task/PROFILE

# The ordinary distclean target can remove extracted assets from /task/game.
# Keep only the extractor's manifest and its listed US assets outside /task.
RUN <<'SH'
set -eu
if [ "$CORPUS_DIR" = sm64/corpus ]; then
    cd /task/game
    python3 - <<'PY'
import json
import pathlib
import tarfile

root = pathlib.Path.cwd()
manifest = pathlib.Path(".assets-local.txt")
assets = json.loads(pathlib.Path("assets.json").read_text())
names = set(manifest.read_text().splitlines()[2:])
expected = {name for name, spec in assets.items() if not name.startswith("@") and "us" in spec[-1]}
assert expected <= names, "incomplete US asset extraction"
with tarfile.open("/opt/mario-eval/sm64-assets.tar.gz", "w:gz", dereference=True) as archive:
    for name in [manifest.name, *sorted(expected)]:
        path = pathlib.Path(name)
        assert not path.is_absolute() and ".." not in path.parts, name
        assert path.is_file() and path.resolve().is_relative_to(root), name
        assert path.suffix.lower() not in (".z64", ".n64", ".v64"), name
        archive.add(path, arcname=name, recursive=False)
PY
    chmod 0444 /opt/mario-eval/sm64-assets.tar.gz
fi
SH

# Verify zero held-out data, variant patches, or retail ROM images exist in the image.
RUN python3 -c 'import json, pathlib; ref = pathlib.Path("/opt/mario-eval/reference"); idx = json.loads((ref / "index.json").read_text()); assert all(not k.startswith("heldout") for k in idx.get("workloads", {})), "heldout leaked in index.json"; assert not list(ref.rglob("heldout*")), "heldout files leaked in reference"; assert not pathlib.Path("/opt/mario-eval/corpus/variants").exists(), "variant patches leaked into task image"; assert not list(pathlib.Path("/task/game").rglob("*.z64")), "ROM file leaked in /task/game"'

USER agent
ENV HOME=/home/agent
RUN cd /task/game && rm -rf .git build build_* *.z64 \
    && find . -exec touch -t 202601010000 {} + \
    && printf 'build/\nbuild_*/\n*.z64\n' >> .gitignore \
    && git init -q -b main \
    && git -c user.name=baseline -c user.email=baseline@mario-eval add -A \
    && git -c user.name=baseline -c user.email=baseline@mario-eval commit -qm "${GAME_TITLE}" \
    && test -z "$(git fsck --full --no-reflogs --unreachable 2>&1)"
WORKDIR /task/game
