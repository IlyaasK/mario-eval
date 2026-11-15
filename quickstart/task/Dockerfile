# The container the agent works in: the mario-eval image (toolchain, n64run,
# grader) plus the game source, the public corpus and its baseline reference.
# Build context: repository root.
FROM mario-eval
COPY corpus/grader.json /opt/mario-eval/corpus/grader.json
COPY corpus/replays/public /opt/mario-eval/corpus/replays/public
COPY cache/reference /opt/mario-eval/reference
COPY tools/mev.py /usr/local/bin/mev
RUN chmod 755 /usr/local/bin/mev \
    && (id -u ubuntu >/dev/null 2>&1 && usermod -l agent -d /home/agent -m ubuntu && groupmod -n agent ubuntu \
        || useradd -m -u 1000 agent)
COPY --chown=1000:1000 workload /task/game
COPY --chown=1000:1000 quickstart/task/TASK.md /task/TASK.md
COPY --chown=1000:1000 quickstart/task/docs /task/docs
RUN echo speed > /task/PROFILE && chown -R 1000:1000 /task
USER agent
RUN cd /task/game && rm -rf build *.z64 \
    && printf 'build/\n*.z64\n' > .gitignore \
    && git init -q -b main && git -c user.name=baseline -c user.email=baseline@mario-eval \
         add -A && git -c user.name=baseline -c user.email=baseline@mario-eval commit -qm "Pip's Garden baseline"
WORKDIR /task
