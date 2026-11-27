# Mario Eval v4 Offline Agent Harness Configurations

Reference offline-parity configurations used for 24-hour autonomous trials:

- `relay.py`: Host-isolated API key relay (`HTTP/1.0` SSE streaming, zero API keys inside `mario-eval-task`, optional `RELAY_EXTRA_JSON` thinking parameters).
- `agy-hooks.json`: Root-owned read-only `PreToolUse` gate mounted at `/home/agent/.gemini/config/hooks.json:ro` blocking `search_web`, `search_marketplace`, `read_url_content`, `*browser*`, and `ask_question`.
- `opencode-offline.json`: Read-only OpenCode config (`--thinking`, `OPENCODE_DISABLE_AUTOUPDATE=1`, `OPENCODE_DISABLE_MODELS_FETCH=1`) denying `webfetch`, `websearch`, `codesearch`, and `question` on both primary and `explore`/`general` subagents.
- `kimi-config.toml`: Read-only Kimi Code CLI config enabling `[thinking]`, disabling `builtin_product_skills`, and disabling `WebSearch`, `FetchURL`, and `AskUserQuestion`.

All trial containers run with `cap_drop: [ALL]`, `no-new-privileges:true`, `cpus: "4.5"`, `mem_limit: "10g"`, and internal-only Docker networking (`sandbox`) routed strictly through `relay` or a per-provider `allowlist.txt` proxy.
