#!/usr/bin/env python3
"""mario-eval grader.

    python3 -m grader.grade precompute BASELINE_SRC --corpus DIR --cache DIR [--o2-patch PATCH]
    python3 -m grader.grade grade SUBMISSION_SRC --corpus DIR --cache DIR --out DIR
                            [--split public|heldout|all] [--heldout DIR]
    python3 -m grader.grade export-public --corpus DIR --cache DIR --out DIR

A submission is a source tree (e.g. Pip's Garden or Super Mario 64). The grader:
  1. checks the protected harness files are unchanged,
  2. rebuilds the ROM itself with the pinned toolchain (and verifies the console
     PLAY=1 build compiles when configured),
  3. runs every workload under n64run (ares, CPU interpreter, unthrottled),
  4. gates on gameplay (bit-exact), video and audio (tolerances), hardware
     limits and execution, then
  5. measures resource cost against the baseline and emits, per optimization
     profile, a log-scaled reward (log2 speedup / reward_log2_scale), the
     speedup (base / cand) and the speedup relative to GCC -O2 (when calibrated).

summary.json "status" is "valid", "invalid" (the submission failed a gate:
reward -1 for every profile) or "grader_error" (infrastructure failure: no
reward; rerun).
"""
import argparse
import concurrent.futures
import ctypes
import functools
import hashlib
import json
import itertools
import math
import os
import pathlib
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zlib

import numpy as np

from grader import contract

HW_DEVICES = ["VR4300 ICache", "VR4300 DCache", "VR4300 Uncached", "SP DMA",
              "PI DMA", "SI DMA", "VI DMA", "AI DMA", "DP DMA", "DP Draw"]
RATIO_KEYS = ("est_console_ms", "est_console_p99_ms", "cpu_effective_cycles", "cpu_busy_cycles", "frame_ticks",
              "frame_ticks_p99", "rdp_effective_cycles", "rdp_busy", "rsp_busy", "rsp_gfx_ms", "rsp_aud_ms",
              "rdram_bytes", "footprint_bytes")


class GraderError(Exception):
    """Infrastructure failure: not the submission's fault."""


# --------------------------------------------------------------------- build

def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _copy_source(src, dst):
    root = str(pathlib.Path(src).resolve())

    def _ignore(cur, names):
        ignored = {n for n in names if n == ".git" or n.endswith((".z64", ".n64", ".v64"))}
        if str(pathlib.Path(cur).resolve()) == root:
            ignored |= {n for n in names if n == "build" or n.startswith("build_")}
        return ignored

    shutil.copytree(src, dst, ignore=_ignore)


_DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Strict allowlist of host environment variables passed to untrusted submission
# builds: only PATH and N64_INST are inherited so Make override variables
# (COMPILER, GRUCODE, OPT_FLAGS, PLAY, CFLAGS, MAKEFLAGS, ...), preload shims,
# proxies, and credentials can never leak into or subvert a build.
_BUILD_ENV_ALLOW = ("PATH", "N64_INST")


def _build_env(home, tmp):
    """Strictly scrubbed environment for the untrusted submission build."""
    env = {k: os.environ[k] for k in _BUILD_ENV_ALLOW if k in os.environ}
    env.update({
        "PATH": os.environ.get("PATH", _DEFAULT_PATH),
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "TMP": str(tmp),
        "TEMP": str(tmp),
        "LANG": "C",
        "LC_ALL": "C",
        "TERM": "dumb",
        "SHELL": "/bin/sh",
    })
    return env


def _kill_build_group(proc):
    """Kill the build's whole process group, so no leftover background process
    can keep running (and tamper with the grading environment) after it."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _run_build(cmd, cwd, home, tmp, timeout):
    """Run one untrusted build command, isolated as far as the container allows.

    The submission's Makefile runs as the same container user as the grader, so
    it cannot be given a private filesystem view without namespaces (blocked by
    the default container seccomp profile). What it does get: a scrubbed
    environment, its own HOME/TMPDIR, its own session/process group (killed
    afterwards), no core dumps, and the grading container runs with no network.
    Returns (returncode, output, timed_out).
    """
    def child_setup():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    proc = subprocess.Popen(cmd, cwd=cwd, env=_build_env(home, tmp),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True, preexec_fn=child_setup)
    timed_out = False
    out = ""
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_build_group(proc)
        try:
            out, _ = proc.communicate(timeout=60)
        except Exception:
            out = ""
    _kill_build_group(proc)
    return proc.returncode, out or "", timed_out


def build(src, cfg, log_path, keep_play=False):
    """Build in scratch, retaining only the benchmark ROM, idle ranges and optional PLAY ROM."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="mev-build-"))
    out_rom = work / "built.z64"
    home, tmp = work / "home", work / "tmp"
    try:
        _copy_source(src, work / "src")
        home.mkdir(exist_ok=True)
        tmp.mkdir(exist_ok=True)
        jobs = int(os.cpu_count() or 4)
        base_cmd = cfg.get("build_cmd", ["make"])
        play_cmd = cfg.get("play_build_cmd")

        def _make_cmd(raw, j):
            return [raw[0], f"-j{j}", *raw[1:]] if raw[0] == "make" else list(raw)

        if play_cmd:
            # Build benchmark and PLAY=1 ROMs concurrently in separate scratch copies
            # so full clean `mev check` stays well under interactive/agent timeouts.
            play_src = work / "play-src"
            play_home, play_tmp = work / "play-home", work / "play-tmp"
            _copy_source(src, play_src)
            play_home.mkdir(exist_ok=True)
            play_tmp.mkdir(exist_ok=True)
            j_half = max(1, jobs // 2)
            cmd = _make_cmd(base_cmd, jobs - j_half)
            pcmd = _make_cmd(play_cmd, j_half)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                f_bench = pool.submit(_run_build, cmd, work / "src", home, tmp, cfg["build_timeout_s"])
                f_play = pool.submit(_run_build, pcmd, play_src, play_home, play_tmp, cfg["build_timeout_s"])
                rc, out, timed_out = f_bench.result()
                prc, pout, ptimeout = f_play.result()
        else:
            cmd = _make_cmd(base_cmd, jobs)
            rc, out, timed_out = _run_build(cmd, work / "src", home, tmp, cfg["build_timeout_s"])
            prc, pout, ptimeout = 0, "", False
            play_src = None

        if timed_out:
            pathlib.Path(log_path).write_text(out + "\nbuild timed out\n")
            shutil.rmtree(work, ignore_errors=True)
            return None, "build timed out"

        logs = [out]
        rom = work / "src" / cfg["rom"]
        if rc != 0 or not rom.exists():
            pathlib.Path(log_path).write_text("".join(logs))
            shutil.rmtree(work, ignore_errors=True)
            return None, "build failed; see build.log"

        # Verify the compiled ELF actually retains the unmodified harness symbols
        # and that no other code touches the ISViewer MMIO port or wraps mev_*.
        elf_err = verify_elf_harness(work / "src" / cfg["elf"], cfg, src_root=work / "src") if cfg.get("elf") else None
        if elf_err:
            pathlib.Path(log_path).write_text("".join(logs) + f"\n--- ELF harness check ---\n{elf_err}\n")
            shutil.rmtree(work, ignore_errors=True)
            return None, elf_err

        shutil.copy2(rom, out_rom)
        # The ELF is only used to scope the idle-time exclusion to the idle
        # function; the emulator credits only a genuine halt loop inside that
        # range, so a doctored ELF buys nothing.
        elf_path = work / "src" / cfg["elf"] if cfg.get("elf") else None
        idle = idle_ranges(elf_path, cfg.get("idle_symbols", [])) if elf_path else []
        (work / "built.idle.json").write_text(json.dumps(idle))
        if elf_path and elf_path.is_file():
            (work / "built.meta.json").write_text(json.dumps(inspect_elf_metadata(elf_path, src_root=work / "src", cfg=cfg)))

        if play_cmd:
            logs.append("\n--- play build ---\n" + pout)
            if ptimeout:
                logs.append("\n--- PLAY=1 ROM build timed out ---\n")
                pathlib.Path(log_path).write_text("".join(logs))
                shutil.rmtree(work, ignore_errors=True)
                return None, "PLAY=1 ROM build timed out"
            if prc != 0:
                pathlib.Path(log_path).write_text("".join(logs))
                shutil.rmtree(work, ignore_errors=True)
                return None, "PLAY=1 ROM build failed; see build.log"
            if cfg.get("play_rom"):
                playable = play_src / cfg["play_rom"]
                if not playable.is_file() or playable.stat().st_size < 65536:
                    pathlib.Path(log_path).write_text("".join(logs))
                    shutil.rmtree(work, ignore_errors=True)
                    return None, "PLAY=1 build did not produce its ROM; see build.log"
                play_bytes = playable.read_bytes()
                if play_bytes == out_rom.read_bytes() or b"@mev " in play_bytes:
                    pathlib.Path(log_path).write_text("".join(logs))
                    shutil.rmtree(work, ignore_errors=True)
                    return None, "PLAY=1 ROM still contains benchmark harness; see build.log"
                if keep_play:
                    shutil.copyfile(playable, work / "play.z64")

        pathlib.Path(log_path).write_text("".join(logs))
        shutil.rmtree(work / "src", ignore_errors=True)
        if play_src is not None:
            shutil.rmtree(play_src, ignore_errors=True)
        return out_rom, None
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def build_submission(args):
    cfg = json.loads(pathlib.Path(args.config).read_text())
    out = pathlib.Path(args.out)
    if args.play_smoke and not cfg.get("play_rom"):
        raise GraderError("PLAY runtime smoke is not supported for this target")
    audit_errs = audit_submission_integrity(args.source, cfg)
    if audit_errs:
        (out / "error.txt").write_text("integrity audit failed: " + "; ".join(audit_errs[:4]))
        return
    rom, error = build(args.source, cfg, out / "build.log", keep_play=args.play_smoke)
    if rom is None:
        (out / "error.txt").write_text(error)
        return
    try:
        for name in ("built.z64", "built.idle.json"):
            shutil.copyfile(rom.parent / name, out / name)
        if (rom.parent / "built.meta.json").is_file():
            shutil.copyfile(rom.parent / "built.meta.json", out / "built.meta.json")
        if args.play_smoke:
            shutil.copyfile(rom.parent / "play.z64", out / "play.z64")
    finally:
        shutil.rmtree(rom.parent, ignore_errors=True)


def load_submission_build(directory):
    for name in ("error.txt", "built.z64", "built.idle.json", "built.meta.json", "play.z64"):
        p = directory / name
        if p.is_symlink() or (p.exists() and not p.is_file()):
            raise GraderError("invalid build handoff")
    error = directory / "error.txt"
    if error.is_file():
        with error.open(encoding="utf-8", errors="replace") as stream:
            return None, stream.read(256)
    if not all((directory / name).is_file() for name in ("built.z64", "built.idle.json")):
        raise GraderError("missing isolated build output")
    return directory / "built.z64", None


# ------------------------------------------------------- build-time integrity

def _digest(paths):
    """sha256 over the (path, content) of every file the measurement trusts."""
    def _one(p):
        p = pathlib.Path(p)
        try:
            return str(p), sha256(p)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return str(p), "-"

    if len(paths) > 4:
        workers = min(len(paths), os.cpu_count() or 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            entries = list(pool.map(_one, paths))
    else:
        entries = [_one(p) for p in paths]
    h = hashlib.sha256()
    for path_s, dig in entries:
        h.update(path_s.encode())
        h.update(dig.encode())
    return h.hexdigest()


def measurement_artifacts(corpus, cache, items):
    """Everything a malicious build could rewrite to change what is scored:
    the emulator, the grader itself, the corpus (config/patches/variants), the
    reference cache and the replays. The grader hashes these before the build
    and again before measuring, so tampering is detected instead of scored."""
    paths = []
    exe = shutil.which("n64run")
    if exe:
        paths.append(exe)
    paths += sorted(str(p) for p in pathlib.Path(__file__).parent.rglob("*.py"))
    so_paths = sorted(str(p) for p in pathlib.Path(__file__).parent.rglob("*.so"))
    opt_so = pathlib.Path("/opt/mario-eval/grader/_fast_video.so")
    if opt_so.is_file() and str(opt_so) not in so_paths:
        so_paths.append(str(opt_so))
    paths += so_paths
    corpus = pathlib.Path(corpus)
    paths += sorted(str(p) for p in corpus.rglob("*") if p.is_file())
    cache = pathlib.Path(cache)
    if (cache / "index.json").exists():
        paths.append(str(cache / "index.json"))
    for w in items:
        run = cache / "runs" / w["id"]
        for name in ("obs.bin", "audio.bin", "frames.jsonl", "result.json", "frames.bin", "frames.json"):
            if (run / name).exists():
                paths.append(str(run / name))
        paths += sorted(str(p) for p in run.glob("video*.z"))
        paths.append(str(w["replay"]))
    return _digest(paths)


_SOURCE_EXTS = {".c", ".h", ".s", ".S", ".inc", ".cc", ".cpp"}
_BUILD_EXTS = {".mk", ".ld", ".sh"}
_RE_ISV_ADDR = re.compile(r"0x(?:b3f[ef]|13f[ef])[0-9a-f]{4}[uUlL]{0,3}\b", re.IGNORECASE)
_RE_MEV_MACRO = re.compile(r"^\s*#\s*(?:define|undef)\s+(?:mev_|MEV_|sMev|ISV_|SM64_MEV_H)", re.MULTILINE)
_RE_MEV_COND = re.compile(
    r"^\s*#\s*(?:ifdef|ifndef|if|elif)\b[^\n]*\b(?:SM64_MEV_H|MEV_\w*|mev_\w*|sMev\w*|ISV_\w*)\b",
    re.MULTILINE,
)
_RE_PLAY_COND = re.compile(r"^\s*#\s*(?:ifdef|ifndef|if|elif)\b[^\n]*\bPLAY\b", re.MULTILINE)
_RE_MAKE_PLAY_COND = re.compile(
    r"^\s*(?:ifn?eq|ifn?def)\b[^\n]*\bPLAY\b"
    r"|\$\(\s*(?:if|or|and|filter|filter-out|subst|patsubst|eval)\b[^\n]*\bPLAY\b"
    r"|\$\([^)\n]*\$\(?PLAY\)?"
)
_RE_MAKE_DYN_EVAL = re.compile(r"\$\(\s*eval\b[^\n]*\$\(\s*(?:if|or|and|filter|shell)\b")
_RE_SH_PLAY_COND = re.compile(r"\$\{?PLAY\}?\b")
_RE_GCC_INJECT = re.compile(r"(?:=|:=|\+=|\s)(?:-include|--include|-imacros)(?:\s|=|$)")
_RE_LD_WRAP = re.compile(r"(?:--wrap|-Wl,(?:[^,\s]*,)*--wrap)(?:=|,|\s|$)")
_RE_LD_DEFSYM = re.compile(
    r"(?:--defsym|-Wl,(?:[^,\s]*,)*--defsym)(?:=|,|\s)[^\n]*(?:mev_|MEV_|sMev|thread1_idle)"
)
_RE_LD_SCRIPT_SYM = re.compile(
    r"(?:PROVIDE(?:_HIDDEN)?\s*\(\s*|(?:^|[;\s]))(?:mev_|MEV_|sMev|thread1_idle)\w*\s*="
)
_RE_CC_MEV_DEF = re.compile(r"(?:^|\s)-D\s*(?:mev_|MEV_|sMev|ISV_)")
_RE_BSLASH_NL = re.compile(r"\\\r?\n")
_RE_ADJ_STR = re.compile(r'"\s+"')


def _extract_play_block_hashes(norm_text):
    """Return SHA-256 digests of every top-level #ifdef/#ifndef/#if ... PLAY block."""
    lines = norm_text.splitlines()
    hashes = []
    i = 0
    while i < len(lines):
        if _RE_PLAY_COND.match(lines[i]):
            depth, start, i = 1, i, i + 1
            while i < len(lines) and depth > 0:
                if re.match(r"^\s*#\s*(?:ifdef|ifndef|if)\b", lines[i]):
                    depth += 1
                elif re.match(r"^\s*#\s*endif\b", lines[i]):
                    depth -= 1
                i += 1
            norm = "\n".join(l.rstrip() for l in lines[start:i])
            hashes.append(hashlib.sha256(norm.encode("utf-8")).hexdigest())
        else:
            i += 1
    return hashes


def _extract_make_play_block_hashes(norm_text):
    """Return SHA-256 digests of every top-level GNU Make ifeq/ifneq/ifdef/ifndef PLAY block."""
    lines = norm_text.splitlines()
    hashes = []
    i = 0
    while i < len(lines):
        if re.match(r"^\s*(?:ifn?eq|ifn?def)\b[^\n]*\bPLAY\b", lines[i]):
            depth, start, i = 1, i, i + 1
            while i < len(lines) and depth > 0:
                if re.match(r"^\s*(?:ifn?eq|ifn?def)\b", lines[i]):
                    depth += 1
                elif re.match(r"^\s*endif\b", lines[i]):
                    depth -= 1
                i += 1
            norm = "\n".join(l.rstrip() for l in lines[start:i])
            hashes.append(hashlib.sha256(norm.encode("utf-8")).hexdigest())
        else:
            i += 1
    return hashes


def _play_blocks_match(got_hashes, expected):
    """Match extracted PLAY block digests against expected list (None = editable slot)."""
    if len(got_hashes) != len(expected):
        return False
    return all(exp is None or got == exp for got, exp in zip(got_hashes, expected))


def audit_submission_integrity(src, cfg):
    """Static anti-reward-hacking audit over submission source and build scripts.

    Blocks harness spoofing (direct ISViewer/MMIO writes or '@mev ' strings outside
    protected files), macro/header shadowing of mev_* / MEV_*, Makefile/linker
    flag subversion (-include/--wrap/--defsym/-Dmev_*/linker-script overrides),
    and unauthorized PLAY conditionals or edits inside protected benchmark-only
    PLAY glue blocks that could split benchmark vs real-console behavior.
    """
    root = pathlib.Path(src).resolve()
    protected = {pathlib.PurePosixPath(f).as_posix() for f in cfg.get("protected_files", [])}
    allowed_play = cfg.get("allowed_play_guards")
    protected_play_blocks = cfg.get("protected_play_blocks") or {}
    errors = []

    for dirpath, dirnames, filenames in os.walk(root):
        cur = pathlib.Path(dirpath)
        rel_dir = cur.relative_to(root)
        dirnames[:] = [
            d for d in dirnames
            if d != ".git" and not (rel_dir == pathlib.PurePosixPath(".") and (d == "build" or d.startswith("build_")))
        ]
        for fname in filenames:
            p = cur / fname
            rel = p.relative_to(root).as_posix()
            if rel in protected:
                continue
            ext = p.suffix
            is_ld = (ext == ".ld" or fname.endswith(".ld.in"))
            is_make = (fname in ("Makefile", "makefile", "GNUmakefile") or fname.startswith("Makefile.") or ext == ".mk")
            is_sh = (ext == ".sh")
            is_build = (is_make or is_ld or is_sh)
            is_src = (ext in _SOURCE_EXTS or fname.endswith(".inc.c"))
            if not is_build and not is_src:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            # Join backslash-newline continuations (C translation phase 2 & Make
            # line folding) and adjacent C string literals so multiline/split tricks
            # cannot evade static regex checks.
            norm_text = _RE_BSLASH_NL.sub("", text)
            joined_str = _RE_ADJ_STR.sub("", norm_text) if is_src else norm_text

            if _RE_ISV_ADDR.search(norm_text):
                errors.append(f"{rel}: direct ISViewer MMIO address outside protected harness")
            if '"@mev ' in joined_str or "'@mev " in joined_str:
                errors.append(f"{rel}: raw '@mev ' protocol string outside protected harness")
            if is_src and _RE_MEV_MACRO.search(norm_text):
                errors.append(f"{rel}: preprocessor #define/#undef of protected mev/ISV symbol")
            if is_src and _RE_MEV_COND.search(norm_text):
                errors.append(f"{rel}: unauthorized preprocessor conditional referencing protected mev/ISV symbol")

            if is_build:
                n_build_play = 0
                # Strip C block comments before scanning linker scripts for symbol assignments.
                scan_text = re.sub(r"/\*.*?\*/", "", norm_text, flags=re.DOTALL) if is_ld else norm_text
                # Inspect build/linker lines while ignoring GNU Make's top-level `-include dep.d`.
                for lineno, line in enumerate(scan_text.splitlines(), 1):
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    if not (stripped.startswith("-include ") or stripped.startswith("-include\t")):
                        if _RE_GCC_INJECT.search(line):
                            errors.append(f"{rel}:{lineno}: disallowed compiler header-injection flag (-include/-imacros)")
                    if _RE_LD_WRAP.search(line):
                        errors.append(f"{rel}:{lineno}: disallowed linker --wrap flag")
                    if _RE_LD_DEFSYM.search(line):
                        errors.append(f"{rel}:{lineno}: disallowed linker --defsym targeting harness/idle symbol")
                    if _RE_CC_MEV_DEF.search(line):
                        errors.append(f"{rel}:{lineno}: disallowed -D override of mev/ISV symbol")
                    if is_ld and _RE_LD_SCRIPT_SYM.search(line):
                        errors.append(f"{rel}:{lineno}: disallowed linker-script override of harness/idle symbol")
                    if is_make and _RE_MAKE_DYN_EVAL.search(line):
                        errors.append(f"{rel}:{lineno}: disallowed dynamic Make $(eval ...) conditional")
                    if is_make and _RE_MAKE_PLAY_COND.search(line):
                        n_build_play += 1
                    elif is_sh and _RE_SH_PLAY_COND.search(line):
                        n_build_play += 1
                if (is_make or is_sh) and allowed_play is not None:
                    max_allowed = int(allowed_play.get(rel, 0))
                    if n_build_play > max_allowed:
                        errors.append(f"{rel}: unauthorized PLAY build conditional ({n_build_play} > allowed {max_allowed})")
                if is_make and rel in protected_play_blocks:
                    got_hashes = _extract_make_play_block_hashes(norm_text)
                    if not _play_blocks_match(got_hashes, protected_play_blocks[rel]):
                        errors.append(f"{rel}: protected PLAY Makefile conditional block was modified")

            if is_src and allowed_play is not None:
                n_play = len(_RE_PLAY_COND.findall(norm_text))
                max_allowed = int(allowed_play.get(rel, 0))
                if n_play > max_allowed:
                    errors.append(f"{rel}: unauthorized PLAY preprocessor conditional ({n_play} > allowed {max_allowed})")
            if is_src and rel in protected_play_blocks:
                got_hashes = _extract_play_block_hashes(norm_text)
                if not _play_blocks_match(got_hashes, protected_play_blocks[rel]):
                    errors.append(f"{rel}: protected PLAY/#ifndef PLAY benchmark glue block was modified")
            if len(errors) >= 16:
                return errors
    return errors


def inspect_elf_metadata(elf, src_root=None, cfg=None):
    """Extract active compiler, microcode, and optimization flags from the
    submission's build configuration and linked ELF for numerical attribution."""
    p = pathlib.Path(elf)
    if not p.is_file():
        return {}
    raw = p.read_bytes()
    compiler = "gcc" if b"GCC: (" in raw else None
    ucode = None
    opt_flags = None

    if src_root is not None and (pathlib.Path(src_root) / "Makefile").is_file():
        base_cmd = (cfg or {}).get("build_cmd", ["make"])
        make_flags = [a for a in base_cmd[1:] if "=" in a] if base_cmd and base_cmd[0] == "make" else []
        with tempfile.TemporaryDirectory(prefix="mev-meta-") as td:
            td_p = pathlib.Path(td)
            try:
                r = subprocess.run(
                    ["make", "-s", *make_flags, "print-COMPILER", "print-GRUCODE", "print-OPT_FLAGS"],
                    cwd=src_root, env=_build_env(td_p, td_p),
                    capture_output=True, text=True, timeout=10,
                )
                if r.returncode == 0:
                    for line in (r.stdout + "\n" + r.stderr).splitlines():
                        m = re.match(r"^(COMPILER|GRUCODE|OPT_FLAGS)\s+is\s+.*\[(.*)\]", line.strip())
                        if m:
                            k, v = m.group(1), m.group(2).strip()
                            if k == "COMPILER" and v:
                                compiler = v
                            elif k == "GRUCODE" and v:
                                ucode = v
                            elif k == "OPT_FLAGS":
                                opt_flags = v
            except Exception:
                pass

    proc = subprocess.run(["mips64-elf-nm", "--defined-only", str(p)], capture_output=True, text=True)
    if proc.returncode == 0:
        syms = {line.split()[-1] for line in proc.stdout.splitlines() if line.split()}
        syms_lower = {s.lower() for s in syms}
        if compiler is None:
            compiler = "gcc" if any(
                s in syms for s in ("__udivdi3", "__divdi3", "__ashldi3", "__lshrdi3", "__popcountsi2", "__clzsi2")
            ) else "ido"
        if ucode is None:
            if any("f3dex3" in s for s in syms_lower):
                ucode = "f3dex3"
            elif any("f3dex2" in s for s in syms_lower):
                ucode = "f3dex2"
            elif "rspf3dbootstart" in syms_lower or "rspfast3dstart" in syms_lower:
                ucode = "f3d_old"
    trap_insns = None
    od = subprocess.run(["mips64-elf-objdump", "-d", str(p)], capture_output=True, text=True)
    if od.returncode == 0:
        trap_insns = len(re.findall(r"\t(?:teq|tne|tlt|tltu|tge|tgeu|teqi|tnei|tlti|tltiu|tgei|tgeiu)\b", od.stdout))
    return {
        **({"compiler": compiler} if compiler else {}),
        **({"ucode": ucode} if ucode else {}),
        **({"opt_flags": opt_flags} if opt_flags is not None else {}),
        **({"trap_insns": trap_insns} if trap_insns is not None else {}),
        "elf_bytes": len(raw),
    }


def verify_elf_harness(elf, cfg, src_root=None):
    """Post-build ELF verification that protected harness code/data survived intact."""
    spec = cfg.get("elf_harness_check")
    if not spec or not pathlib.Path(elf).is_file():
        return None
    proc = subprocess.run(["mips64-elf-nm", "-S", "--defined-only", str(elf)], capture_output=True, text=True)
    if proc.returncode != 0:
        return f"ELF harness check failed: mips64-elf-nm returned {proc.returncode}"
    text_syms = {}
    data_syms = {}
    wrap_syms = []
    wrap_prefix = spec.get("forbid_wrap_prefix", "__wrap_mev_")
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 4:
            _addr, size_hex, stype, name = parts
            size = int(size_hex, 16)
        elif len(parts) == 3:
            _addr, stype, name = parts
            size = 0
        else:
            continue
        if (wrap_prefix and name.startswith(wrap_prefix)) or name == "__wrap_thread1_idle":
            wrap_syms.append(name)
        if stype in "tT":
            text_syms[name] = size
        else:
            data_syms[name] = size

    if wrap_syms:
        return f"ELF harness check failed: forbidden wrapped symbols {wrap_syms[:5]}"
    for sym in spec.get("required_text_symbols", []):
        if sym not in text_syms:
            return f"ELF harness check failed: missing harness symbol '{sym}'"
    for sym, expected in spec.get("required_data_sizes", {}).items():
        # Note: static BSS/data symbols (e.g. sMevObs) may be omitted from the
        # linked ELF symbol table under SGI IDO; verify size whenever present.
        if sym in data_syms and data_syms[sym] != 0 and data_syms[sym] != expected:
            return f"ELF harness check failed: '{sym}' size {data_syms[sym]} != expected {expected}"
    for sym, minimum in spec.get("min_data_sizes", {}).items():
        if sym in data_syms and data_syms[sym] != 0 and data_syms[sym] < minimum:
            return f"ELF harness check failed: '{sym}' size {data_syms[sym]} < minimum {minimum}"

    isv_imm = spec.get("isv_upper_imm")
    if isv_imm:
        pat = re.compile(rf"\blui\b[^\n]*\b{re.escape(isv_imm)}\b", re.IGNORECASE)
        od_elf = subprocess.run(["mips64-elf-objdump", "-d", str(elf)], capture_output=True, text=True)
        if od_elf.returncode != 0:
            return f"ELF harness check failed: mips64-elf-objdump returned {od_elf.returncode}"
        elf_hits = len(pat.findall(od_elf.stdout))
        mev_obj_rel = spec.get("mev_object")
        mev_obj = (pathlib.Path(src_root) / mev_obj_rel) if (src_root and mev_obj_rel) else None
        if mev_obj is not None:
            if not mev_obj.is_file():
                return f"ELF harness check failed: missing compiled harness object '{mev_obj_rel}'"
            od_mev = subprocess.run(["mips64-elf-objdump", "-d", str(mev_obj)], capture_output=True, text=True)
            if od_mev.returncode != 0:
                return f"ELF harness check failed: mips64-elf-objdump on {mev_obj_rel} returned {od_mev.returncode}"
            mev_hits = len(pat.findall(od_mev.stdout))
            if mev_hits == 0:
                return f"ELF harness check failed: harness ISViewer write ({isv_imm}) missing from {mev_obj_rel}"
            if elf_hits != mev_hits:
                return f"ELF harness check failed: ISViewer MMIO ({isv_imm}) count in ELF ({elf_hits}) != harness ({mev_hits})"
        elif elf_hits == 0:
            return f"ELF harness check failed: harness ISViewer write ({isv_imm}) missing from compiled ELF"
    return None


def idle_ranges(elf, symbols):
    """Address ranges ("lo:hi", hex) of the named idle functions in the ELF.

    CPU time spent executing inside them is time the CPU only waited (for the
    RCP, or for the next frame), and is excluded from CPU busy time.
    """
    if not symbols:
        return []
    proc = subprocess.run(["mips64-elf-nm", "-S", "--defined-only", str(elf)], capture_output=True, text=True)
    found = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[3] in symbols and parts[2] in "tT":
            lo = int(parts[0], 16) & 0xFFFFFFFF
            found[parts[3]] = f"{lo:x}:{lo + int(parts[1], 16):x}"
    missing = [s for s in symbols if s not in found]
    if missing:
        raise GraderError(f"idle symbols not found in {elf}: {missing}")
    return [found[s] for s in symbols]


# ----------------------------------------------------------------------- run

def run_workload(rom, replay, frames, out_dir, max_fields, timeout, clear_stale=True):
    out_dir = pathlib.Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    if clear_stale:
        # The submission build runs in this container and shares /tmp, and n64run
        # keeps its ares settings/saves there; clear them so a planted ares home
        # cannot influence the emulator.
        for stale in ("/tmp/n64run-home", "/tmp/n64run-saves"):
            shutil.rmtree(stale, ignore_errors=True)
    cmd = ["n64run", "--rom", str(rom), "--replay", str(replay), "--out", str(out_dir),
           "--frames", str(frames), "--max-fields", str(max_fields)]
    idle_file = pathlib.Path(rom).with_suffix(".idle.json")
    for r in (json.loads(idle_file.read_text()) if idle_file.exists() else []):
        cmd += ["--idle-range", r]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "host_timeout"}
    (out_dir / "stderr.txt").write_text("\n".join(
        l for l in proc.stderr.splitlines() if "Stalled compile" not in l))
    shutil.rmtree(out_dir / "home", ignore_errors=True)
    shutil.rmtree(out_dir / "saves", ignore_errors=True)
    result_path = out_dir / "result.json"
    if proc.returncode < 0 or not result_path.exists():
        raise GraderError(f"n64run died (code {proc.returncode}) on {replay}")
    return json.loads(result_path.read_text())


def load_run(out_dir):
    out_dir = pathlib.Path(out_dir)
    rows = [json.loads(l) for l in (out_dir / "frames.jsonl").read_text().splitlines() if l]
    return {
        "rows": rows,
        "result": json.loads((out_dir / "result.json").read_text()),
        "obs": (out_dir / "obs.bin").read_bytes(),
        "audio": (out_dir / "audio.bin").read_bytes(),
        "video_path": out_dir / "video.bin",
    }


# ------------------------------------------------------------------- metrics

def busy_rsp(row):
    return row["rsp_cycles"] - row["rsp_halted_cycles"]


def rdram_bytes(row):
    return sum(sum(row["rdram"].get(d, (0, 0))) for d in HW_DEVICES)


def _delta_mean(rows, key):
    if len(rows) < 2 or key not in rows[0]:
        return 0.0
    return float((rows[-1][key] - rows[0][key]) / (len(rows) - 1))


# Clock domains (verified against ares: master clock 187.5 MHz, CPU instruction
# = 2 master clocks, RSP cycle = 3 master clocks).
CPU_CYCLES_PER_MS = 93_750.0      # count_ticks / cpu_idle_cycles: VR4300 cycles (93.75 MHz)
RSP_UNITS_PER_MS = 187_500.0      # rsp_cycles: master clocks (RSP runs at 62.5 MHz)
RDP_CYCLES_PER_MS = 62_500.0      # rdp_cycles: modelled RDP cycles (62.5 MHz)
# Effective sustained mixed-master N64 RDRAM throughput (peak burst is 500 MB/s,
# but mixed CPU cachelines + 2D triangle spans + R/W turnarounds sustain ~250 MB/s).
RDRAM_BYTES_PER_MS = 250_000.0
FIELD_MS = 1000.0 / 60.0
# Bus-coupled CPU contention: ares already charges uncontended cache fills (40/48
# cycles). On real hardware, extra wait cycles per CPU bus transaction rise with
# concurrent RCP RDRAM traffic (SP DMA + DP DMA + DP Draw + PI/SI DMA) plus
# continuous 60 Hz VI scanout. Coupling contention to RCP traffic ensures that
# real bandwidth/fillrate wins (ra-zb-opa, F3DEX2, TMEM batching) reduce CPU
# bus stalls just as on console.
BUS_CONTENTION_BASE_CYCLES = 4.0
BUS_CONTENTION_PER_MB_RCP = 6.0
RCP_BUS_DEVICES = ("SP DMA", "PI DMA", "SI DMA", "DP DMA", "DP Draw")
# Symmetric RDP RDRAM burst turnaround & bus contention (62.5 MHz gclk per 32B
# DP DMA / DP Draw RDRAM burst): models RDRAM packet/read-write span turnarounds
# plus MI/RI contention from concurrent CPU + SP + PI/SI + 60 Hz VI scanout traffic,
# matching real-N64 DPC_PIPEBUSY_REG behavior on fill-heavy scenes (e.g. JRB).
DP_BUS_DEVICES = ("DP DMA", "DP Draw")
RDP_BUS_BASE_CYCLES = 3.5
RDP_BUS_PER_MB_OTHER = 2.5


def rcp_rdram_bytes(row):
    return sum(sum(row["rdram"].get(d, (0, 0))) for d in RCP_BUS_DEVICES)


def dp_rdram_bytes(row):
    return sum(sum(row["rdram"].get(d, (0, 0))) for d in DP_BUS_DEVICES)


def metrics(run):
    """Per-frame costs over frames 1..N-1 (frame 0 includes boot and setup).

    The benchmark build runs each frame's stages one after another. On a
    console, SM64 overlaps them: the CPU builds frame N+1 while the RSP and RDP
    draw frame N, all sharing RDRAM alongside continuous 60 Hz VI scanout. So a
    frame's console cost is estimated as the busiest unit: max(CPU, RSP busy,
    RDP busy, RDRAM time at sustained bandwidth). CPU time excludes the idle
    thread (waiting for the RCP) and adds bus-coupled contention per CPU bus
    transaction proportional to concurrent RCP RDRAM traffic. The RDP model
    includes 4-bank x 2 KB RDRAM page-miss cycles (see docs/n64-cost-model.md).
    """
    rows = run["rows"]
    if len(rows) < 2:
        raise GraderError(f"need at least 2 frames to compute per-frame metrics (got {len(rows)})")
    d = lambda key: np.array([b.get(key, 0) - a.get(key, 0) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    ticks = d("count_ticks")
    idle = d("cpu_idle_cycles")
    cpu_busy = ticks - idle
    bus_events = (d("icache_misses") + d("dcache_misses") + d("dcache_writebacks")
                  + d("uncached_reads") + d("uncached_writes"))
    rsp = np.array([busy_rsp(b) - busy_rsp(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    rdp = d("rdp_cycles")
    traffic = np.array([rdram_bytes(b) - rdram_bytes(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    rcp_traffic = np.array([rcp_rdram_bytes(b) - rcp_rdram_bytes(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    dp_traffic = np.array([dp_rdram_bytes(b) - dp_rdram_bytes(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    # Continuous 60 Hz VI scanout (two fields per 30 Hz logical frame) is not
    # charged during unthrottled n64run; add its framebuffer read bandwidth here.
    fb_w, fb_h, fb_bpp = rows[0]["fb"]
    vi_bytes_per_frame = float(2 * fb_w * fb_h * (fb_bpp // 8))
    contention_cycles = BUS_CONTENTION_BASE_CYCLES + BUS_CONTENTION_PER_MB_RCP * (rcp_traffic / 1_000_000.0)
    cpu_eff = cpu_busy + contention_cycles * bus_events
    other_bus_mb = (traffic - dp_traffic + vi_bytes_per_frame) / 1_000_000.0
    rdp_bus_cycles = (dp_traffic / 32.0) * (RDP_BUS_BASE_CYCLES + RDP_BUS_PER_MB_OTHER * other_bus_mb)
    rdp_eff = rdp + rdp_bus_cycles
    last, first = rows[-1], rows[0]
    per_device = {dev: (sum(last["rdram"].get(dev, (0, 0))) - sum(first["rdram"].get(dev, (0, 0)))) / (len(rows) - 1)
                  for dev in HW_DEVICES}
    cpu_ms_f = cpu_eff / CPU_CYCLES_PER_MS
    rsp_ms_f = rsp / RSP_UNITS_PER_MS
    rdp_ms_f = rdp_eff / RDP_CYCLES_PER_MS
    mem_ms_f = (traffic + vi_bytes_per_frame) / RDRAM_BYTES_PER_MS
    console_ms = np.maximum.reduce([cpu_ms_f, rsp_ms_f, rdp_ms_f, mem_ms_f])
    bottleneck = np.argmax(np.stack([cpu_ms_f, rsp_ms_f, rdp_ms_f, mem_ms_f]), axis=0)
    # Displayed rate with SM64's 30 Hz game logic: a frame is shown on the first
    # video field after it completes, and never sooner than two fields.
    fields = np.maximum(2, np.ceil(console_ms / FIELD_MS - 1e-9))
    est_console_ms = float(console_ms.mean())
    return {
        "frame_ticks": float(ticks.mean()),
        "frame_ticks_p99": float(np.percentile(ticks, 99)),
        "cpu_busy_cycles": float(cpu_busy.mean()),
        "cpu_effective_cycles": float(cpu_eff.mean()),
        "cpu_bus_contention_cycles": float((contention_cycles * bus_events).mean()),
        "cpu_idle_cycles": float(idle.mean()),
        "frame_ms": float(ticks.mean() / CPU_CYCLES_PER_MS),
        "cpu_ms": float(cpu_ms_f.mean()),
        "cpu_cycles": float(cpu_eff.mean()),
        "rsp_busy": float(rsp.mean()),
        "rsp_ms": float(rsp_ms_f.mean()),
        "rsp_gfx_ms": float(_delta_mean(rows, "rsp_gfx_cycles") / RSP_UNITS_PER_MS),
        "rsp_aud_ms": float(_delta_mean(rows, "rsp_aud_cycles") / RSP_UNITS_PER_MS),
        "rdp_busy": float(rdp.mean()),
        "rdp_effective_cycles": float(rdp_eff.mean()),
        "rdp_bus_contention_cycles": float(rdp_bus_cycles.mean()),
        "rdp_ms": float(rdp_ms_f.mean()),
        "mem_ms": float(mem_ms_f.mean()),
        "bottleneck_share": {name: float((bottleneck == i).mean()) for i, name in enumerate(("cpu", "rsp", "rdp", "rdram"))},
        "rdp_fill_cycles": _delta_mean(rows, "rdp_fill_cycles"),
        "rdp_fill_imrd_cycles": _delta_mean(rows, "rdp_fill_imrd_cycles"),
        "rdp_fill_2cycle_cycles": _delta_mean(rows, "rdp_fill_2cycle_cycles"),
        "rdp_fill_decal_cycles": _delta_mean(rows, "rdp_fill_decal_cycles"),
        "rdp_fill_copy_cycles": _delta_mean(rows, "rdp_fill_copy_cycles"),
        "rdp_color_addr": int(last.get("rdp_color_addr", 0)),
        "rdp_z_addr": int(last.get("rdp_z_addr", 0)),
        "rdp_page_miss_cycles": _delta_mean(rows, "rdp_page_miss_cycles"),
        "rdp_rdram_page_misses": _delta_mean(rows, "rdp_rdram_page_misses"),
        "rdp_tmem_cycles": _delta_mean(rows, "rdp_tmem_cycles"),
        "rdp_sync_cycles": _delta_mean(rows, "rdp_sync_cycles"),
        "rdp_triangles": _delta_mean(rows, "rdp_triangles"),
        "rdp_pixels": _delta_mean(rows, "rdp_pixels"),
        "rdp_z_rejected_pixels": _delta_mean(rows, "rdp_z_rejected_pixels"),
        "rdp_tmem_loads": _delta_mean(rows, "rdp_tmem_loads"),
        "rdp_tmem_bytes": _delta_mean(rows, "rdp_tmem_bytes"),
        "rdp_syncs": _delta_mean(rows, "rdp_syncs"),
        "est_console_ms": est_console_ms,
        "est_console_p99_ms": float(np.percentile(console_ms, 99)),
        "est_fps": float(1000.0 / max(est_console_ms, 1e-9)),
        "est_fps_30hz": float(60.0 * len(fields) / fields.sum()),
        "frames_over_33ms": float((console_ms > 2 * FIELD_MS).mean()),
        "frames_under_16ms": float((console_ms <= FIELD_MS).mean()),
        "rdram_bytes": float(traffic.mean()),
        "rdram_bytes_by_device": per_device,
        "dcache_misses": _delta_mean(rows, "dcache_misses"),
        "icache_misses": _delta_mean(rows, "icache_misses"),
        "dcache_writebacks": _delta_mean(rows, "dcache_writebacks"),
        "uncached_reads": _delta_mean(rows, "uncached_reads"),
        "uncached_writes": _delta_mean(rows, "uncached_writes"),
        "cache_uncached_ops": int(run["result"].get("cache_uncached_ops", 0)),
        "cache_cde_unaligned_ops": int(run["result"].get("cache_cde_unaligned_ops", 0)),
        "cache_kseg1_dirty_synonyms": int(run["result"].get("cache_kseg1_dirty_synonyms", 0)),
        "dcache_coherence_errors": int(run["result"].get("dcache_coherence_errors", 0)),
        "footprint_bytes": run["result"]["footprint_bytes"],
        "highest_byte": (run["result"]["highest_line"] + 1) * 16,
    }


# --------------------------------------------------------------- comparisons

def _max_abs_diff(a, b):
    if isinstance(a, list):
        best = 0.0
        for x, y in zip(a, b):
            fx, fy = float(x), float(y)
            if not (math.isfinite(fx) and math.isfinite(fy)):
                return math.nan
            d = abs(fx - fy)
            if d > best:
                best = d
        return best
    fa, fb = float(a), float(b)
    if not (math.isfinite(fa) and math.isfinite(fb)):
        return math.nan
    return abs(fa - fb)


def compare_obs(ref, cand, frames, schema_name="pips-garden", cfg=None):
    if len(ref) != len(cand):
        return {
            "pass": False, "frame": 0, "field": "obs_bytes", "ref": len(ref), "cand": len(cand),
            "gameplay_score": 0.0, "failed_frames": frames,
        }
    n = len(ref) // frames
    gcfg = (cfg or {}).get("gameplay", {})
    if gcfg.get("mode", "bit_exact") != "player_equivalence":
        first_fail = None
        failed_frames = 0
        for i in range(frames):
            r, c = ref[i * n:(i + 1) * n], cand[i * n:(i + 1) * n]
            if r != c:
                failed_frames += 1
                if first_fail is None:
                    diff = contract.first_difference(r, c, schema_name)
                    first_fail = {"frame": i, "field": diff[0], "ref": diff[1], "cand": diff[2]}
        score = round(float(frames - failed_frames) / float(max(frames, 1)), 6)
        if first_fail is not None:
            return {"pass": False, **first_fail, "gameplay_score": score, "failed_frames": failed_frames}
        return {"pass": True, "gameplay_score": 1.0, "failed_frames": 0}

    ref_frames = [contract.decode(ref[i * n:(i + 1) * n], schema_name) for i in range(frames)]
    cand_frames = [contract.decode(cand[i * n:(i + 1) * n], schema_name) for i in range(frames)]
    exact_fields = gcfg.get("exact_fields", ["frame", "level_area"])
    win_fields = gcfg.get("window_exact_fields", ["mario_stats", "mario_action"])
    win = int(gcfg.get("window_frames", 1))
    float_tols = gcfg.get("float_tolerances", {})
    actor_tol = gcfg.get("actor_tolerance")
    actor_radius = float(gcfg.get("actor_radius", float("inf")))
    worst_drift = 0.0
    first_fail = None
    failed_frames = 0
    score_sum = 0.0

    for i in range(frames):
        rf, cf = ref_frames[i], cand_frames[i]
        frame_exact_ok = True
        frame_failed = False
        for fname in exact_fields:
            if cf.get(fname) != rf.get(fname):
                frame_exact_ok = False
                frame_failed = True
                if first_fail is None:
                    first_fail = {"frame": i, "field": fname, "ref": rf.get(fname), "cand": cf.get(fname)}
        lo, hi = max(0, i - win), min(frames - 1, i + win)
        for fname in win_fields:
            cval = cf.get(fname)
            if not any(cval == ref_frames[j].get(fname) for j in range(lo, hi + 1)):
                frame_exact_ok = False
                frame_failed = True
                if first_fail is None:
                    first_fail = {"frame": i, "field": fname, "ref": rf.get(fname), "cand": cval}
        max_excess_ratio = 0.0
        for fname, tol in float_tols.items():
            d = _max_abs_diff(rf.get(fname, 0.0), cf.get(fname, 0.0))
            ftol = max(float(tol), 1e-9)
            if not math.isfinite(d):
                frame_failed = True
                max_excess_ratio = math.inf
                if first_fail is None:
                    first_fail = {"frame": i, "field": fname, "ref": rf.get(fname), "cand": cf.get(fname),
                                  "diff": None, "tolerance": tol}
            else:
                if fname == "mario_pos" and d > worst_drift:
                    worst_drift = d
                if d > ftol:
                    frame_failed = True
                    r = d / ftol
                    if r > max_excess_ratio:
                        max_excess_ratio = r
                    if first_fail is None:
                        first_fail = {"frame": i, "field": fname, "ref": rf.get(fname), "cand": cf.get(fname),
                                      "diff": round(d, 4), "tolerance": tol}
        actor_miss = False
        if actor_tol is not None:
            miss = _unmatched_actor(rf, cf, float(actor_tol), actor_radius)
            if miss is not None:
                actor_miss = True
                frame_failed = True
                if first_fail is None:
                    first_fail = {"frame": i, "field": "actors", "ref": miss, "cand": None,
                                  "tolerance": actor_tol, "radius": actor_radius}
        if frame_failed:
            failed_frames += 1
        if not frame_exact_ok or not math.isfinite(max_excess_ratio):
            fscore = 0.0
        else:
            fscore = 1.0 if max_excess_ratio <= 1.0 else (1.0 / (1.0 + (max_excess_ratio ** 4)))
            if actor_miss:
                fscore *= 0.5
        score_sum += fscore

    # Final frame stats must match without window slack so coins/health/stars at route end are exact.
    if "mario_stats" in win_fields and cand_frames[-1].get("mario_stats") != ref_frames[-1].get("mario_stats"):
        if first_fail is None:
            first_fail = {"frame": frames - 1, "field": "mario_stats",
                          "ref": ref_frames[-1].get("mario_stats"), "cand": cand_frames[-1].get("mario_stats")}
        failed_frames = max(failed_frames, 1)
        score_sum = max(0.0, score_sum - 1.0)

    gp_score = round(score_sum / float(max(frames, 1)), 6)
    if first_fail is not None:
        return {
            "pass": False,
            **first_fail,
            "gameplay_score": gp_score,
            "failed_frames": failed_frames,
            "max_pos_drift": round(worst_drift, 4),
        }
    return {"pass": True, "max_pos_drift": round(worst_drift, 4), "gameplay_score": 1.0, "failed_frames": 0}


def _unmatched_actor(rf, cf, tol, radius):
    """Every reference actor within `radius` of Mario must have a candidate
    actor with the same action/state and a position within `tol`. Actors are
    matched as an unordered set: object-list order is an allocator detail the
    player never sees. Farther actors are not checked, so hibernating distant
    objects stays legal. Returns the first unmatched reference actor, or None.
    The harness records at most len(actor_state) actors in list order; past
    that the two builds may record different subsets, so such frames are only
    checked by actor_count."""
    count = rf.get("actor_count", 0)
    cap = len(rf.get("actor_state", []))
    if count != cf.get("actor_count") or count > cap:
        return None
    rp = np.asarray(rf["actor_pos"][:3 * count], dtype=np.float64).reshape(count, 3)
    cp = np.asarray(cf["actor_pos"][:3 * count], dtype=np.float64).reshape(count, 3)
    rs, cs = rf["actor_state"][:count], cf["actor_state"][:count]
    if rs == cs and np.abs(rp - cp).max(initial=0.0) <= tol:
        return None
    near = np.linalg.norm(rp - np.asarray(rf["mario_pos"], dtype=np.float64), axis=1) <= radius
    near_idx = [int(a) for a in np.flatnonzero(near)]
    if not near_idx:
        return None
    close = np.abs(rp[:, None, :] - cp[None, :, :]).max(axis=2) <= tol
    adj = {
        a: [int(b) for b in np.flatnonzero(close[a]) if cs[b] == rs[a]]
        for a in near_idx
    }
    # Exact bipartite maximum matching (Kuhn's augmenting-path DFS) so nearby
    # identical-state actors never falsely fail due to greedy matching order.
    match_b = {}

    def _augment(u, seen):
        for v in adj[u]:
            if v in seen:
                continue
            seen.add(v)
            if v not in match_b or _augment(match_b[v], seen):
                match_b[v] = u
                return True
        return False

    for a in near_idx:
        if not _augment(a, set()):
            return {"state": rs[a], "pos": rp[a].tolist()}
    return None


def decode_rgba16(buf, w, h):
    a = np.frombuffer(buf, dtype=">u2").reshape(h, w).astype(np.int16)
    return np.stack([(a >> 11) & 31, (a >> 6) & 31, (a >> 1) & 31], axis=-1)


def decode_rgba32(buf, w, h):
    a = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4).astype(np.int16)
    # Scale 8-bit channels onto 5-bit [0..31] units so channel_tolerance applies uniformly.
    return a[:, :, :3] >> 3


def decode_frame(buf, w, h, bpp):
    return decode_rgba32(buf, w, h) if bpp == 32 else decode_rgba16(buf, w, h)


def unmatched(a, b, tol):
    """Pixels of a with no pixel within tol (per channel) in b's 3x3 neighbourhood."""
    h, w, _ = a.shape
    pad = np.pad(b, ((1, 1), (1, 1), (0, 0)), mode="edge")
    best = np.full((h, w), 1 << 14, dtype=np.int16)
    for dy in range(3):
        for dx in range(3):
            d = np.abs(a - pad[dy:dy + h, dx:dx + w]).max(axis=-1)
            np.minimum(best, d, out=best)
    return best > tol


def mismatch(a, b, tol):
    """Pixels where a and b disagree beyond tolerance, in either direction."""
    return unmatched(a, b, tol) | unmatched(b, a, tol)


def reference_variants(entry, fallback=()):
    """Which stored video holds each accepted variant for one workload.

    A dict {"combo": stored}, where "" means the combination renders exactly
    like the baseline. Caches written before deduplication stored a plain list
    of variant ids (one video each), either per workload or once for the whole
    cache; both are still read."""
    v = entry.get("variants")
    if isinstance(v, dict):
        return v
    if isinstance(v, list):
        return {name: name for name in v}
    return {name: name for name in fallback}


def _reference_frame_sets(ref_dir, variants, frames, w, h, bpp):
    """Distinct reference frames per frame index: index 0 is the original
    picture, the rest are accepted variants.

    Each distinct picture counts once (a minimum over duplicates is unchanged),
    so grading memory is bounded by the distinct frames rather than one whole
    video per accepted combination, and repeated comparisons are skipped. The
    storage deduplication already collapsed identical combinations; this also
    collapses frames a variant shares with the original or another variant."""
    size = w * h * bpp // 8
    files = [ref_dir / "video.bin.z"] + [ref_dir / f"video.{v}.bin.z"
                                         for v in sorted(set(variants.values()) - {""})]
    seen = [dict() for _ in range(frames)]
    out = [[] for _ in range(frames)]
    for path in files:
        video = zlib.decompress(path.read_bytes())
        for i in range(frames):
            frame = video[i * size:(i + 1) * size]
            key = hashlib.sha1(frame).digest()
            if key not in seen[i]:
                seen[i][key] = True
                out[i].append(frame)
        del video
    return out


_FAST_VIDEO_LIB = None
_FAST_VIDEO_CHECKED = False


def _get_fast_video():
    global _FAST_VIDEO_LIB, _FAST_VIDEO_CHECKED
    if not _FAST_VIDEO_CHECKED:
        _FAST_VIDEO_CHECKED = True
        candidates = [
            pathlib.Path(__file__).with_name("_fast_video.so"),
            pathlib.Path("/opt/mario-eval/grader/_fast_video.so"),
        ]
        so = next((p for p in candidates if p.is_file()), None)
        if so is not None:
            lib = ctypes.CDLL(str(so))
            base_args = [
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_char_p),
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_double,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
            ]
            lib.compare_video_fast.argtypes = base_args
            lib.compare_video_fast.restype = ctypes.c_int
            if hasattr(lib, "compare_video_consistent"):
                lib.compare_video_consistent.argtypes = base_args + [ctypes.POINTER(ctypes.c_int)]
                lib.compare_video_consistent.restype = ctypes.c_int
            if hasattr(lib, "compare_video_v3"):
                lib.compare_video_v3.argtypes = base_args + [
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.POINTER(ctypes.c_double),
                ]
                lib.compare_video_v3.restype = ctypes.c_int
            _FAST_VIDEO_LIB = lib
    return _FAST_VIDEO_LIB


def _luma_and_uniform_py(rgb5):
    """5-bit RGB -> expanded 8-bit BT.601 luma and >=99.9% single-color check."""
    r8 = ((rgb5[:, :, 0] << 3) | (rgb5[:, :, 0] >> 2)).astype(np.float64)
    g8 = ((rgb5[:, :, 1] << 3) | (rgb5[:, :, 1] >> 2)).astype(np.float64)
    b8 = ((rgb5[:, :, 2] << 3) | (rgb5[:, :, 2] >> 2)).astype(np.float64)
    luma = 0.299 * r8 + 0.587 * g8 + 0.114 * b8
    keys = ((rgb5[:, :, 0].astype(np.int32) << 10)
            | (rgb5[:, :, 1].astype(np.int32) << 5)
            | rgb5[:, :, 2].astype(np.int32)).ravel()
    _, counts = np.unique(keys, return_counts=True)
    is_unif = bool(counts.size > 0 and (float(counts.max()) / float(keys.size)) >= 0.999)
    return luma, is_unif


def _block_ssim_defect_py(la, lb):
    """GBA Eval single-scale block-SSIM defect matching fast_video.cpp."""
    h, w = la.shape
    bs = 16 if w >= 320 else 10
    c1, c2 = 6.5025, 58.5225
    total = 0.0
    blocks = 0
    for y0 in range(0, h, bs):
        y1 = min(h, y0 + bs)
        for x0 in range(0, w, bs):
            x1 = min(w, x0 + bs)
            a = la[y0:y1, x0:x1]
            b = lb[y0:y1, x0:x1]
            mx, my = float(a.mean()), float(b.mean())
            vx = max(0.0, float((a * a).mean()) - mx * mx)
            vy = max(0.0, float((b * b).mean()) - my * my)
            cov = float((a * b).mean()) - mx * my
            den = (mx * mx + my * my + c1) * (vx + vy + c2)
            ssim = ((2.0 * mx * my + c1) * (2.0 * cov + c2)) / den if den > 0.0 else 1.0
            ssim = max(0.0, min(1.0, ssim))
            d = 1.0 - ssim
            if d < 0.15:
                d = 0.0
            total += d
            blocks += 1
    return total / float(blocks) if blocks else 0.0


def _compute_video_ssim_py(cand_raw, ref_raw, n_frames, w, h, bpp):
    """Python fallback for GBA Eval block-SSIM video scoring."""
    if cand_raw == ref_raw:
        return 1.0, 1.0, -1, 0.05, 0.0
    size = w * h * bpp // 8
    ref_lumas = []
    defects = []
    for i in range(n_frames):
        off = i * size
        rf = ref_raw[off:off + size]
        cf = cand_raw[off:off + size]
        rl, ru = _luma_and_uniform_py(decode_frame(rf, w, h, bpp))
        ref_lumas.append(rl)
        if cf == rf:
            defects.append(0.0)
        else:
            cl, cu = _luma_and_uniform_py(decode_frame(cf, w, h, bpp))
            defects.append(1.0 if (cu and not ru) else _block_ssim_defect_py(cl, rl))
    moving = []
    for i in range(n_frames - 1):
        off = i * size
        if ref_raw[off:off + size] != ref_raw[off + size:off + 2 * size]:
            md = _block_ssim_defect_py(ref_lumas[i], ref_lumas[i + 1])
            if md > 0.0:
                moving.append(md)
    tau = float(np.clip(np.quantile(moving, 0.90), 0.005, 0.35)) if moving else 0.05
    inv_tau = 1.0 / max(tau, 1e-12)
    scores = [1.0 / (1.0 + ((d * inv_tau) ** 4)) for d in defects]
    mean_score = float(sum(scores) / max(len(scores), 1))
    worst_score = min(scores) if scores else 1.0
    worst_frame = scores.index(worst_score) if worst_score < 1.0 else -1
    worst_defect = max(defects) if defects else 0.0
    return mean_score, worst_score, worst_frame, tau, worst_defect


def compare_video(ref_dir, variants, cand_path, ref_rows, cand_rows, cfg, max_threads=None):
    """Every frame of a workload must match, within tolerance, one consistent
    reference video — either the unmodified baseline ("orig") or a single
    accepted visual variant combination across all frames of the workload
    (preventing both per-pixel mixing and cross-frame variant flickering),
    verified with both 3x3 pixel tolerance and GBA Eval-style block-SSIM.
    """
    if len(ref_rows) != len(cand_rows):
        return {
            "pass": False, "frame": min(len(ref_rows), len(cand_rows)),
            "reason": "frame count changed", "ssim_score": 0.0,
        }
    w, h, bpp = ref_rows[0]["fb"]
    for i, row in enumerate(cand_rows):
        if row["fb"] != [w, h, bpp]:
            return {
                "pass": False, "frame": i,
                "reason": f"framebuffer format changed to {row['fb']}", "ssim_score": 0.0,
            }
    vcfg = cfg["video"]
    tol = vcfg["channel_tolerance"]
    limit = vcfg["max_bad_fraction"]
    min_ssim = vcfg.get("min_ssim_score")
    min_ssim_frame = vcfg.get("min_ssim_frame_score")
    ref_names = ["orig"] + sorted(set(variants.values()) - {""})
    files = [ref_dir / "video.bin.z"] + [ref_dir / f"video.{v}.bin.z" for v in ref_names[1:]]

    def _finalize_video(res):
        ok = bool(res["pass"])
        if min_ssim is not None and res.get("ssim_score", 1.0) < float(min_ssim):
            ok = False
        if min_ssim_frame is not None and res.get("worst_ssim_frame_score", 1.0) < float(min_ssim_frame):
            ok = False
        res["pass"] = ok
        if min_ssim is not None:
            res["min_ssim_score"] = float(min_ssim)
        if min_ssim_frame is not None:
            res["min_ssim_frame_score"] = float(min_ssim_frame)
        return res

    fast = _get_fast_video()
    if fast is not None and bpp in (16, 32):
        encoded = [os.fsencode(str(p)) for p in files]
        arr = (ctypes.c_char_p * len(encoded))(*encoded)
        out_pass = ctypes.c_int(0)
        out_worst_frac = ctypes.c_double(0.0)
        out_worst_frame = ctypes.c_int(-1)
        out_failed = ctypes.c_int(0)
        out_variant = ctypes.c_int(0)
        out_best_ref = ctypes.c_int(0)
        out_mean_frac = ctypes.c_double(0.0)
        out_ssim = ctypes.c_double(1.0)
        out_worst_ssim = ctypes.c_double(1.0)
        out_worst_ssim_frame = ctypes.c_int(-1)
        out_ssim_tau = ctypes.c_double(0.05)
        out_worst_ssim_defect = ctypes.c_double(0.0)
        threads = max(1, max_threads if max_threads is not None else (os.cpu_count() or 4))
        has_v3 = hasattr(fast, "compare_video_v3")
        if has_v3:
            rc = fast.compare_video_v3(
                os.fsencode(str(cand_path)), arr, len(encoded),
                len(ref_rows), w, h, bpp, int(tol), float(limit), int(threads),
                ctypes.byref(out_pass), ctypes.byref(out_worst_frac),
                ctypes.byref(out_worst_frame), ctypes.byref(out_failed),
                ctypes.byref(out_variant), ctypes.byref(out_best_ref),
                ctypes.byref(out_mean_frac), ctypes.byref(out_ssim),
                ctypes.byref(out_worst_ssim), ctypes.byref(out_worst_ssim_frame),
                ctypes.byref(out_ssim_tau), ctypes.byref(out_worst_ssim_defect),
            )
            best_idx = out_best_ref.value
            matched = ref_names[best_idx] if 0 <= best_idx < len(ref_names) else "orig"
        elif hasattr(fast, "compare_video_consistent"):
            rc = fast.compare_video_consistent(
                os.fsencode(str(cand_path)), arr, len(encoded),
                len(ref_rows), w, h, bpp, int(tol), float(limit), int(threads),
                ctypes.byref(out_pass), ctypes.byref(out_worst_frac),
                ctypes.byref(out_worst_frame), ctypes.byref(out_failed),
                ctypes.byref(out_variant), ctypes.byref(out_best_ref),
            )
            best_idx = out_best_ref.value
            matched = ref_names[best_idx] if 0 <= best_idx < len(ref_names) else "orig"
        else:
            rc = fast.compare_video_fast(
                os.fsencode(str(cand_path)), arr, len(encoded),
                len(ref_rows), w, h, bpp, int(tol), float(limit), int(threads),
                ctypes.byref(out_pass), ctypes.byref(out_worst_frac),
                ctypes.byref(out_worst_frame), ctypes.byref(out_failed),
                ctypes.byref(out_variant),
            )
            matched = None
        if rc == 0:
            res = {
                "pass": bool(out_pass.value),
                "worst_bad_fraction": float(out_worst_frac.value),
                "worst_frame": int(out_worst_frame.value),
                "max_bad_fraction": limit,
                "failed_frames": int(out_failed.value),
                "variant_frames": int(out_variant.value),
            }
            if matched is not None:
                res["matched_variant"] = matched
            if has_v3:
                res["mean_bad_fraction"] = round(float(out_mean_frac.value), 6)
                res["ssim_score"] = round(float(out_ssim.value), 6)
                res["worst_ssim_frame_score"] = round(float(out_worst_ssim.value), 6)
                res["worst_ssim_frame"] = int(out_worst_ssim_frame.value)
                res["ssim_tau"] = round(float(out_ssim_tau.value), 6)
                res["worst_ssim_defect"] = round(float(out_worst_ssim_defect.value), 6)
            return _finalize_video(res)
        raise GraderError(f"compare_video_fast failed (rc={rc}) on {cand_path}")

    n_frames = len(ref_rows)
    size = w * h * bpp // 8
    cand_raw = pathlib.Path(cand_path).read_bytes()
    orig_raw = zlib.decompress(files[0].read_bytes())
    if cand_raw == orig_raw:
        return _finalize_video({
            "pass": True, "worst_bad_fraction": 0.0, "mean_bad_fraction": 0.0, "worst_frame": -1,
            "max_bad_fraction": limit, "failed_frames": 0, "variant_frames": 0,
            "matched_variant": "orig",
            "ssim_score": 1.0, "worst_ssim_frame_score": 1.0, "worst_ssim_frame": -1,
            "ssim_tau": 0.05, "worst_ssim_defect": 0.0,
        })

    n_refs = len(files)
    orig_fracs = [0.0] * n_frames
    orig_exact = [False] * n_frames
    any_nonzero = False
    for i in range(n_frames):
        off = i * size
        cf, of = cand_raw[off:off + size], orig_raw[off:off + size]
        if cf == of:
            orig_exact[i] = True
            continue
        frac = float(mismatch(decode_frame(cf, w, h, bpp), decode_frame(of, w, h, bpp), tol).mean())
        orig_fracs[i] = frac
        if frac > 0.0:
            any_nonzero = True
    if not any_nonzero:
        ms, ws, wf, tau, wd = _compute_video_ssim_py(cand_raw, orig_raw, n_frames, w, h, bpp)
        return _finalize_video({
            "pass": True, "worst_bad_fraction": 0.0, "mean_bad_fraction": 0.0, "worst_frame": -1,
            "max_bad_fraction": limit, "failed_frames": 0, "variant_frames": 0,
            "matched_variant": "orig",
            "ssim_score": round(ms, 6), "worst_ssim_frame_score": round(ws, 6),
            "worst_ssim_frame": wf, "ssim_tau": round(tau, 6), "worst_ssim_defect": round(wd, 6),
        })

    ref_raws = [orig_raw] + [zlib.decompress(p.read_bytes()) for p in files[1:]]
    frac_mat = [[0.0] * n_frames for _ in range(n_refs)]
    exact_mat = [[False] * n_frames for _ in range(n_refs)]
    frac_mat[0] = orig_fracs
    exact_mat[0] = orig_exact
    for i in range(n_frames):
        off = i * size
        cf = cand_raw[off:off + size]
        c_dec = None
        seen = {hashlib.sha1(ref_raws[0][off:off + size]).digest(): orig_fracs[i]}
        for r in range(1, n_refs):
            rf = ref_raws[r][off:off + size]
            if cf == rf:
                exact_mat[r][i] = True
                frac_mat[r][i] = 0.0
                continue
            key = hashlib.sha1(rf).digest()
            vf = seen.get(key)
            if vf is None:
                if c_dec is None:
                    c_dec = decode_frame(cf, w, h, bpp)
                vf = float(mismatch(c_dec, decode_frame(rf, w, h, bpp), tol).mean())
                seen[key] = vf
            frac_mat[r][i] = vf

    best_key = (n_frames + 1, 2.0, n_refs)
    best_r = 0
    best_res = None
    for r in range(n_refs):
        r_worst = 0.0
        r_sum = 0.0
        r_wframe = -1
        r_failed = 0
        r_variant = 0
        for i in range(n_frames):
            f = frac_mat[r][i]
            r_sum += f
            if f > limit:
                r_failed += 1
            if r > 0 and not exact_mat[0][i] and (exact_mat[r][i] or (orig_fracs[i] > limit and f <= limit)):
                r_variant += 1
            if f > r_worst:
                r_worst = f
                r_wframe = i
        key = (r_failed, r_worst, r)
        if key < best_key:
            best_key = key
            best_r = r
            best_res = {
                "pass": r_worst <= limit,
                "worst_bad_fraction": r_worst,
                "mean_bad_fraction": round(r_sum / float(n_frames), 6),
                "worst_frame": r_wframe,
                "max_bad_fraction": limit,
                "failed_frames": r_failed,
                "variant_frames": r_variant,
                "matched_variant": ref_names[r],
            }
    ms, ws, wf, tau, wd = _compute_video_ssim_py(cand_raw, ref_raws[best_r], n_frames, w, h, bpp)
    best_res.update({
        "ssim_score": round(ms, 6),
        "worst_ssim_frame_score": round(ws, 6),
        "worst_ssim_frame": wf,
        "ssim_tau": round(tau, 6),
        "worst_ssim_defect": round(wd, 6),
    })
    return _finalize_video(best_res)


def _sanitize_json(obj):
    """Ensure every nested value is strict RFC 8259 JSON (no NaN/Infinity)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj


@functools.lru_cache(maxsize=8)
def _mel_filterbank(sample_rate, n_fft=1024, n_mel=40, fmin=80.0, fmax_cap=8000.0):
    hz_to_mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)
    mel_to_hz = lambda m: 700.0 * (10.0 ** (m / 2595.0) - 1.0)
    fmax = min(sample_rate / 2.0, fmax_cap)
    mels = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mel + 2)
    bins = mel_to_hz(mels) * n_fft / sample_rate
    k = np.arange(n_fft // 2 + 1, dtype=np.float64)[None, :]
    lo, mid, hi = bins[:-2, None], bins[1:-1, None], bins[2:, None]
    up = np.where((k > lo) & (k <= mid), (k - lo) / np.maximum(mid - lo, 1e-9), 0.0)
    dn = np.where((k > mid) & (k < hi), (hi - k) / np.maximum(hi - mid, 1e-9), 0.0)
    win = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n_fft, dtype=np.float64) / (n_fft - 1.0))
    return up + dn, win


def _logmel_audio_check(a, b, acfg):
    """GBA Eval-style 40-band log-mel spectral similarity check with CMN,
    per-replay 90th-percentile adaptive tau (floor 25.0), null-frame hard-0,
    and loudness (RMS ratio) guards across every channel.

    Tolerates 1-16 sample phase/timing shifts from legitimate RSP audio
    optimizations while catching dropped channels, missing sound effects,
    gain hacking, desync, or audio corruption.
    """
    sample_rate = int(acfg.get("sample_rate", 32000))
    channels = max(1, int(acfg.get("channels", 2)))
    n_fft = 1024
    hop = max(1, sample_rate // 60)
    fb, win = _mel_filterbank(sample_rate, n_fft=n_fft)
    silence_rms = float(acfg.get("logmel_silence_rms", 100.0))
    null_rms = 2.0
    delta_floor = 25.0
    rms_err_limit = float(acfg.get("max_rms_ratio_err", 0.15))

    min_mean = 1.0
    min_frame = 1.0
    worst_rms_err = 0.0
    worst_rms_ratio = 1.0
    frame_rms_ok = True
    any_active = False

    for ch in range(channels):
        ra = a[ch::channels]
        rb = b[ch::channels]
        if len(ra) < n_fft:
            continue
        n_frames = 1 + (len(ra) - n_fft) // hop
        idx = np.arange(n_frames)[:, None] * hop + np.arange(n_fft)[None, :]
        r_win = ra[idx]
        c_win = rb[idx]
        r_rms = np.sqrt(np.mean(r_win * r_win, axis=1))
        c_rms = np.sqrt(np.mean(c_win * c_win, axis=1))
        r_sil = r_rms < silence_rms
        c_sil = c_rms < silence_rms
        active = ~(r_sil & c_sil)
        if not active.any():
            continue
        any_active = True

        r_spec = np.abs(np.fft.rfft(r_win * win[None, :], axis=1)) ** 2
        c_spec = np.abs(np.fft.rfft(c_win * win[None, :], axis=1)) ** 2
        r_lm = np.log(r_spec @ fb.T + 1e-10)
        c_lm = np.log(c_spec @ fb.T + 1e-10)
        r_cmn = r_lm - r_lm.mean(axis=1, keepdims=True)
        c_cmn = c_lm - c_lm.mean(axis=1, keepdims=True)

        adj_active = ~(r_sil[1:] & r_sil[:-1])
        adj_diffs = np.abs(r_cmn[1:] - r_cmn[:-1]).sum(axis=1)[adj_active]
        tau = max(float(np.quantile(adj_diffs, 0.90)) if len(adj_diffs) else 0.0, delta_floor)

        d = np.abs(r_cmn - c_cmn).sum(axis=1)
        fscore = 1.0 / (1.0 + (d / tau) ** 4)
        fscore = np.where((r_rms < null_rms) != (c_rms < null_rms), 0.0, fscore)
        act_scores = fscore[active]
        ch_mean = float(act_scores.mean())
        ch_min = float(act_scores.min())
        if ch_mean < min_mean:
            min_mean = ch_mean
        if ch_min < min_frame:
            min_frame = ch_min

        # Guard loudness: CMN is gain-invariant, so enforce both overall channel
        # RMS consistency and per-frame active loudness bounds.
        r_tot = float(np.sqrt(np.mean(ra * ra)))
        c_tot = float(np.sqrt(np.mean(rb * rb)))
        if r_tot >= silence_rms:
            ratio = c_tot / r_tot
            err = abs(ratio - 1.0)
            if err > worst_rms_err:
                worst_rms_err = err
                worst_rms_ratio = ratio
        loud = r_rms >= max(2.0 * silence_rms, 128.0)
        if loud.any():
            fratio = c_rms[loud] / r_rms[loud]
            if float(fratio.min()) < 0.50 or float(fratio.max()) > 2.00:
                frame_rms_ok = False

    min_score = float(acfg.get("min_logmel_score", 0.95))
    min_frame_score = float(acfg.get("min_logmel_frame_score", 0.75))
    ok = (not any_active) or (
        min_mean >= min_score
        and min_frame >= min_frame_score
        and worst_rms_err <= rms_err_limit
        and frame_rms_ok
    )
    return {
        "pass": ok,
        "logmel_score": round(min_mean, 6),
        "worst_logmel_frame_score": round(min_frame, 6),
        "min_logmel_score": min_score,
        "min_logmel_frame_score": min_frame_score,
        "rms_ratio": round(worst_rms_ratio, 4),
        "frame_rms_ok": frame_rms_ok,
    }


def _continuous_audio_score(lm, silence_bad_frames=0, total_frames=1):
    rms_err = abs(float(lm.get("rms_ratio", 1.0)) - 1.0)
    rms_pen = 1.0 if rms_err <= 0.15 else (1.0 / (1.0 + ((rms_err / 0.15) ** 4)))
    if not lm.get("frame_rms_ok", True):
        rms_pen *= 0.85
    sil_pen = max(0.0, float(total_frames - silence_bad_frames) / float(max(total_frames, 1)))
    return round(float(lm.get("logmel_score", 1.0)) * rms_pen * sil_pen, 6)


def compare_audio(ref, cand, ref_rows, cand_rows, cfg):
    au_bytes = ref_rows[0]["au_len"]
    for i, row in enumerate(cand_rows):
        if row["au_len"] != au_bytes:
            return {"pass": False, "frame": i, "reason": f"audio bytes/frame {row['au_len']} != {au_bytes}", "audio_score": 0.0}
    acfg = cfg["audio"]
    if len(ref) != len(cand):
        return {"pass": False, "reason": "audio length differs", "audio_score": 0.0}
    if ref == cand:
        return {
            "pass": True,
            "mode": "exact",
            "snr_db": None,
            "worst_frame_snr_db": None,
            "worst_frame": -1,
            "min_snr_db": acfg["min_snr_db"],
            "min_frame_snr_db": acfg["min_frame_snr_db"],
            "logmel_score": 1.0,
            "audio_score": 1.0,
        }
    a = np.frombuffer(ref, dtype=">i2").astype(np.float64)
    b = np.frombuffer(cand, dtype=">i2").astype(np.float64)
    err = a - b
    snr = math.inf if not err.any() else 10 * math.log10(max((a * a).sum(), 1.0) / (err * err).sum())
    snr_out = round(snr, 4) if math.isfinite(snr) else None
    per = au_bytes // 2
    n_au_frames = max(1, len(a) // per)
    worst = (math.inf, -1)
    any_nonsilent = False
    first_sil_fail = None
    sil_bad_frames = 0
    for i in range(len(a) // per):
        fa, fb = a[i * per:(i + 1) * per], b[i * per:(i + 1) * per]
        rms = math.sqrt((fa * fa).mean())
        if rms <= acfg["silence_rms"]:
            if np.abs(fb).max() > acfg["silence_max_abs"]:
                sil_bad_frames += 1
                if first_sil_fail is None:
                    first_sil_fail = i
            continue
        any_nonsilent = True
        e = fa - fb
        if e.any():
            fsnr = 10 * math.log10((fa * fa).sum() / (e * e).sum())
            if fsnr < worst[0]:
                worst = (fsnr, i)
    lm = _logmel_audio_check(a, b, acfg)
    audio_score = _continuous_audio_score(lm, silence_bad_frames=sil_bad_frames, total_frames=n_au_frames)
    if first_sil_fail is not None:
        return {
            "pass": False, "frame": first_sil_fail, "reason": "sound where the baseline is silent",
            "snr_db": snr_out, "logmel_score": lm["logmel_score"], "audio_score": audio_score,
        }
    worst_out = round(worst[0], 4) if math.isfinite(worst[0]) else None
    snr_ok = (not any_nonsilent) or (snr >= acfg["min_snr_db"] and worst[0] >= acfg["min_frame_snr_db"])
    if snr_ok:
        return {
            "pass": True,
            "mode": "snr",
            "snr_db": snr_out,
            "worst_frame_snr_db": worst_out,
            "worst_frame": worst[1],
            "min_snr_db": acfg["min_snr_db"],
            "min_frame_snr_db": acfg["min_frame_snr_db"],
            "logmel_score": lm["logmel_score"],
            "audio_score": audio_score,
        }
    if acfg.get("min_logmel_score") is not None:
        return {
            "pass": lm["pass"],
            "mode": "logmel",
            "snr_db": snr_out,
            "worst_frame_snr_db": worst_out,
            "worst_frame": worst[1],
            "min_snr_db": acfg["min_snr_db"],
            "min_frame_snr_db": acfg["min_frame_snr_db"],
            "audio_score": audio_score,
            **{k: v for k, v in lm.items() if k != "pass"},
        }
    return {
        "pass": False,
        "mode": "snr",
        "snr_db": snr_out,
        "worst_frame_snr_db": worst_out,
        "worst_frame": worst[1],
        "min_snr_db": acfg["min_snr_db"],
        "min_frame_snr_db": acfg["min_frame_snr_db"],
        "logmel_score": lm["logmel_score"],
        "audio_score": audio_score,
    }


# ------------------------------------------------------------------- corpus

def workloads(corpus, cfg, split, heldout_dir):
    items = []
    if split in ("public", "all"):
        items += [dict(w, replay=str(pathlib.Path(corpus) / w["replay"]))
                  for w in cfg["workloads"] if w["split"] == "public"]
    if split in ("heldout", "all"):
        if not heldout_dir:
            raise GraderError("held-out split requested but --heldout not given")
        for p in sorted(pathlib.Path(heldout_dir).glob("*.txt")):
            items.append({"id": f"heldout-{p.stem}", "split": "heldout", "replay": str(p)})
    return items


def run_all(rom, items, frames, out_dir, max_fields, timeout):
    for stale in ("/tmp/n64run-home", "/tmp/n64run-saves"):
        shutil.rmtree(stale, ignore_errors=True)
    jobs = int(os.environ.get("MEV_JOBS", os.cpu_count() or 4))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(jobs, len(items)))) as pool:
        futures = {w["id"]: pool.submit(run_workload, rom, w["replay"], frames,
                                        pathlib.Path(out_dir) / w["id"], max_fields(w["id"]), timeout, False)
                   for w in items}
        return {k: f.result() for k, f in futures.items()}


# ---------------------------------------------------------------- precompute

def patched_copy(source, patch_files):
    """Copy source to a scratch dir and apply one or more patches in order."""
    if isinstance(patch_files, (str, pathlib.Path)):
        patch_files = [patch_files]
    work = pathlib.Path(tempfile.mkdtemp(prefix="mev-variant-"))
    _copy_source(source, work / "src")
    for patch_file in patch_files:
        proc = subprocess.run(["patch", "-s", "-p1", "--no-backup-if-mismatch", "-i", str(patch_file)], cwd=work / "src",
                              capture_output=True, text=True)
        if proc.returncode != 0:
            shutil.rmtree(work, ignore_errors=True)
            raise GraderError(f"patch {patch_file} does not apply: {proc.stdout}{proc.stderr}")
    return work


def essential_atoms(atoms):
    """The atoms of a combination that actually change its rendering.

    An atom may declare `subsumed_by`: other atoms whose change already
    includes its effect, so the combination renders exactly like the same one
    without it. `full-detail` only forces Mario's high-polygon model, and
    `no-lod` removes every level-of-detail switch (Mario's included), so
    `full-detail+no-lod` is `no-lod` frame for frame, on every route (checked
    against every precomputed combination). Dropping such atoms means those
    combinations are never built, stored or compared twice."""
    keep = list(atoms)
    while True:
        ids = {v["id"] for v in keep}
        reduced = [v for v in keep if not (ids - {v["id"]}) & set(v.get("subsumed_by", []))]
        if len(reduced) == len(keep):
            return keep
        keep = reduced


def variant_combinations(cfg):
    """Every distinct non-empty combination of the atomic accepted visual changes.

    The video gate matches each frame as a whole against one reference, so a
    submission that uses several accepted changes needs a reference with
    exactly that combination. Combinations another combination already renders
    identically are skipped (see essential_atoms), and an atom may list the
    "workloads" it can change (e.g. one course's scenery); elsewhere the
    combination looks exactly like the combination without it. Smaller
    combinations come first. Returns [(id, [atom, ...]), ...]."""
    atoms = cfg.get("accepted_visual_variants", [])
    out, seen = [], set()
    for r in range(1, len(atoms) + 1):
        for combo in itertools.combinations(atoms, r):
            essential = essential_atoms(combo)
            vid = "+".join(v["id"] for v in essential)
            if not vid or vid in seen:
                continue
            seen.add(vid)
            out.append((vid, essential))
    return out


def effective_variant(atoms, workload):
    """Id of the combination that renders this workload identically to `atoms`
    (the atoms that can change it), or None for the unmodified baseline.
    Held-out routes may visit any course, so every atom counts for them."""
    def affects(v):
        return "workloads" not in v or workload["split"] != "public" or workload["id"] in v["workloads"]
    # Drop the atoms that cannot change this workload first: subsumption only
    # holds between atoms that are both part of the combination here.
    return "+".join(v["id"] for v in essential_atoms([v for v in atoms if affects(v)])) or None


def precompute(args):
    corpus = pathlib.Path(args.corpus)
    cfg = json.loads((corpus / "grader.json").read_text())
    cache = pathlib.Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    rom, err = build(args.source, cfg, cache / "build.log")
    if rom is None:
        raise GraderError(f"baseline failed to build ({err}); see build.log")
    try:
        items = workloads(args.corpus, cfg, args.split, args.heldout)
        generous = lambda _id: cfg["frames"] * 600 + 2400
        results = run_all(rom, items, cfg["frames"], cache / "runs", generous, cfg["run_timeout_s"])
        index = {
            "rom_sha256": sha256(rom),
            "contract": cfg.get("contract", "pips-garden"),
            "protected": {},
            "workloads": {},
            "variants": [],
        }
        for f in cfg["protected_files"]:
            index["protected"][f] = sha256(pathlib.Path(args.source) / f)
        for w in items:
            res = results[w["id"]]
            if res.get("status") != "completed":
                raise GraderError(f"baseline did not complete {w['id']}: {res}")
            run_dir = cache / "runs" / w["id"]
            video = (run_dir / "video.bin").read_bytes()
            (run_dir / "video.bin.z").write_bytes(zlib.compress(video, 6))
            (run_dir / "video.bin").unlink()
            index["workloads"][w["id"]] = {
                "split": w["split"],
                "replay_sha256": sha256(w["replay"]),
                "vi_fields": res["vi_fields"],
                "metrics": metrics(load_run(run_dir)),
            }
    finally:
        shutil.rmtree(rom.parent, ignore_errors=True)

    # Accepted visual variants: the baseline with each distinct combination of
    # the listed visual changes applied. Each must leave gameplay bit-exact and
    # audio within the audio gate (a microcode swap shifts RSP task timing,
    # which can move a few samples by a few LSBs); only its video is kept, as an
    # extra reference for the video gate. A combination whose video is
    # byte-identical to one already stored is recorded as an alias of it
    # (video_alias) instead of being written again, and the gate compares
    # against distinct frames only, so storage and grading memory both shrink.
    video_alias = {w["id"]: {} for w in items}   # -> {variant id: stored variant id or "" (baseline)}
    video_seen = {}                              # (workload, sha1 of the video) -> stored variant id or ""
    for w in items:
        raw = zlib.decompress((cache / "runs" / w["id"] / "video.bin.z").read_bytes())
        video_seen[(w["id"], hashlib.sha1(raw).hexdigest())] = ""
    stored_variants = set()

    for variant_id, atoms in variant_combinations(cfg):
        own = []
        for w in items:
            same = effective_variant(atoms, w)
            if same == variant_id:
                own.append(w)
            else:
                # Renders like a smaller combination here; alias its stored video.
                video_alias[w["id"]][variant_id] = video_alias[w["id"]].get(same or "", same or "")
        if not own:
            continue
        vwork = patched_copy(args.source, [(corpus / v["patch"]).resolve() for v in atoms])
        vrom = None
        try:
            vrom, verr = build(vwork / "src", cfg, cache / f"build-{variant_id}.log")
            if vrom is None:
                raise GraderError(f"variant {variant_id} failed to build: {verr}")
            vdir = cache / "variant-runs" / variant_id
            vres = run_all(vrom, own, cfg["frames"], vdir, generous, cfg["run_timeout_s"])
            for w in own:
                wid = w["id"]
                if vres[wid].get("status") != "completed":
                    raise GraderError(f"variant {variant_id} did not complete {wid}")
                base_run, var_run = load_run(cache / "runs" / wid), load_run(vdir / wid)
                if base_run["obs"] != var_run["obs"]:
                    raise GraderError(f"variant {variant_id} changes gameplay on {wid}; "
                                      "an accepted visual change must be visual only")
                au = compare_audio(base_run["audio"], var_run["audio"], base_run["rows"], var_run["rows"], cfg)
                if not au["pass"]:
                    raise GraderError(f"variant {variant_id} changes audio on {wid}: {au}")
                if base_run["audio"] != var_run["audio"] and au.get("snr_db") is not None:
                    print(f"variant {variant_id} {wid}: audio SNR {au['snr_db']:.1f} dB ({au.get('mode', 'snr')})", file=sys.stderr)
                video = (vdir / wid / "video.bin").read_bytes()
                digest = hashlib.sha1(video).hexdigest()
                if (wid, digest) in video_seen:
                    video_alias[wid][variant_id] = video_seen[(wid, digest)]
                else:
                    (cache / "runs" / wid / f"video.{variant_id}.bin.z").write_bytes(zlib.compress(video, 6))
                    video_seen[(wid, digest)] = variant_id
                    video_alias[wid][variant_id] = variant_id
                    stored_variants.add(variant_id)
            shutil.rmtree(vdir, ignore_errors=True)
        finally:
            if vrom is not None:
                shutil.rmtree(vrom.parent, ignore_errors=True)
            shutil.rmtree(vwork, ignore_errors=True)

    index["variants"] = sorted(stored_variants)
    for w in items:
        index["workloads"][w["id"]]["variants"] = video_alias[w["id"]]

    # Optional GCC -O2 (IEEE) reference calibration, so summary.json can report
    # both speedup vs vanilla (-O0 / IDO) and speedup beyond compiler flags.
    o2_patch = args.o2_patch or cfg.get("o2_reference_patch")
    if o2_patch:
        pfile = pathlib.Path(o2_patch)
        if not pfile.is_absolute():
            pfile = (corpus / pfile).resolve()
        if pfile.exists():
            owork = patched_copy(args.source, pfile)
            orom = None
            try:
                orom, oerr = build(owork / "src", cfg, cache / "build-o2-ref.log")
                if orom is None:
                    raise GraderError(f"o2 reference patch failed to build: {oerr}")
                odir = cache / "o2-runs"
                ores = run_all(orom, items, cfg["frames"], odir, generous, cfg["run_timeout_s"])
                o2_metrics = {}
                for w in items:
                    if ores[w["id"]].get("status") != "completed":
                        raise GraderError(f"o2 reference did not complete {w['id']}")
                    o2_metrics[w["id"]] = metrics(load_run(odir / w["id"]))
                shutil.rmtree(odir, ignore_errors=True)
                index["o2_reference"] = o2_metrics
            finally:
                if orom is not None:
                    shutil.rmtree(orom.parent, ignore_errors=True)
                shutil.rmtree(owork, ignore_errors=True)

    (cache / "index.json").write_text(json.dumps(index, indent=1))
    print(json.dumps({k: round(v["metrics"]["est_console_ms"], 2) for k, v in index["workloads"].items()}, indent=1))
    print("accepted visual variants:", index["variants"])
    if "o2_reference" in index:
        print("recorded GCC -O2 reference metrics")


def export_public(args):
    """Stage a strictly public-only copy of cache/reference for the agent container."""
    corpus = pathlib.Path(args.corpus)
    cfg = json.loads((corpus / "grader.json").read_text())
    src_cache = pathlib.Path(args.cache)
    dst_cache = pathlib.Path(args.out)
    if dst_cache.exists():
        shutil.rmtree(dst_cache)
    (dst_cache / "runs").mkdir(parents=True, exist_ok=True)

    index = json.loads((src_cache / "index.json").read_text())
    pub_ids = {w["id"] for w in cfg["workloads"] if w["split"] == "public"}
    missing = sorted(pub_ids - set(index["workloads"]))
    if missing:
        raise GraderError(f"missing public workloads in cache: {missing}")

    out_index = {
        "rom_sha256": index["rom_sha256"],
        "contract": index.get("contract", cfg.get("contract", "pips-garden")),
        "protected": index["protected"],
        "workloads": {wid: index["workloads"][wid] for wid in sorted(pub_ids)},
        "variants": index.get("variants", []),
    }
    if "o2_reference" in index:
        out_index["o2_reference"] = {wid: index["o2_reference"][wid]
                                     for wid in sorted(pub_ids) if wid in index["o2_reference"]}
    for wid in sorted(pub_ids):
        shutil.copytree(src_cache / "runs" / wid, dst_cache / "runs" / wid)
    (dst_cache / "index.json").write_text(json.dumps(out_index, indent=1))


# --------------------------------------------------------------------- grade

def failure_details(gates):
    failures = []
    for name, gate in gates.items():
        if gate["pass"]:
            continue
        if "workloads" not in gate:
            failures.append({"gate": name, **{k: v for k, v in gate.items() if k != "pass"}})
            continue
        for workload, result in gate["workloads"].items():
            if not result["pass"]:
                failures.append({"gate": name, "workload": workload,
                                 **{k: None if isinstance(v, float) and not math.isfinite(v) else v
                                    for k, v in result.items() if k not in ("pass", "host_seconds")}})
    return failures


def play_runtime_smoke(rom, out, timeout, cfg=None):
    """Compare idle and controller-driven execution of the same linked PLAY ROM,
    and verify PLAY=1 hardware safety (4 MB RAM, CACHE/KSEG1 invariants, SP/DP
    DMA D-cache coherence) and active RSP audio output."""
    fields = 1200
    out.mkdir(parents=True, exist_ok=True)
    replay = out / "controller.txt"
    replay.write_text("".join(
        ("." if i < 120 else "S" if i % 120 < 50 else "A" if i % 120 < 100 else ".") + " 0 0\n"
        for i in range(fields)
    ))
    hw_cfg = (cfg or {}).get("hardware", {})
    limit_ram = hw_cfg.get("rdram_bytes")
    max_syn = int(hw_cfg.get("max_kseg1_dirty_synonyms", 0))
    max_coh = None
    if "max_dcache_coherence_errors" in hw_cfg:
        max_coh = int(hw_cfg["max_dcache_coherence_errors"]) * 3
    elif "max_dcache_coherence_errors_per_frame" in hw_cfg:
        # 1,200 VI fields is ~600 30Hz game frames on SM64.
        max_coh = int(float(hw_cfg["max_dcache_coherence_errors_per_frame"]) * (fields // 2) + 32)

    results = {}
    for mode, extra in (("idle", []), ("controller", ["--replay", str(replay)])):
        path = pathlib.Path(tempfile.mkdtemp(prefix=f"{mode}-", dir=out))
        # Let n64run create its output directory; nall rewrites existing paths.
        capture = path / "capture"
        cmd = ["n64run", "--rom", str(rom), "--out", str(capture), "--play-fields", str(fields), *extra]
        with (path / "stderr.txt").open("w") as errors:
            try:
                run = subprocess.run(cmd, stderr=errors, timeout=timeout)
            except subprocess.TimeoutExpired:
                return {"pass": False, "status": "host_timeout", "scenario": mode}
        report = capture / "result.json"
        result = json.loads(report.read_text()) if report.is_file() else {"status": "runner_error"}
        results[mode] = result
        if run.returncode or result["status"] != "completed" or result.get("vi_fields") != fields:
            return {"pass": False, "status": result["status"], "scenario": mode,
                    "returncode": run.returncode, "scenarios": results}
        highest_byte = (int(result.get("highest_line", -1)) + 1) * 16
        if limit_ram is not None and highest_byte > limit_ram:
            return {"pass": False, "status": "play_rdram_overflow", "scenario": mode,
                    "highest_byte": highest_byte, "limit_bytes": limit_ram, "scenarios": results}
        if int(result.get("cache_uncached_ops", 0)) > 0 or int(result.get("cache_cde_unaligned_ops", 0)) > 0:
            return {"pass": False, "status": "play_cache_hazard", "scenario": mode, "scenarios": results}
        if int(result.get("cache_kseg1_dirty_synonyms", 0)) > max_syn:
            return {"pass": False, "status": "play_kseg1_dirty_synonym", "scenario": mode, "scenarios": results}
        if max_coh is not None and int(result.get("dcache_coherence_errors", 0)) > max_coh:
            return {"pass": False, "status": "play_dma_coherence_hazard", "scenario": mode,
                    "dcache_coherence_errors": result.get("dcache_coherence_errors"),
                    "max_dcache_coherence_errors": max_coh, "scenarios": results}
        if cfg and cfg.get("contract") == "sm64" and "play_rsp_aud_cycles" in result and int(result["play_rsp_aud_cycles"]) == 0:
            return {"pass": False, "status": "play_audio_silent", "scenario": mode, "scenarios": results}
    different = results["idle"]["play_final_video_hash"] != results["controller"]["play_final_video_hash"]
    return {"pass": different, "status": "completed" if different else "no_controller_response",
            "scenarios": results}


def grader_fingerprint(corpus, cfg, index):
    """Cryptographic fingerprint tying summary.json to the exact grader,
    emulator binary, corpus config, and reference ROM."""
    grader_dir = pathlib.Path(__file__).parent
    grader_files = sorted(
        [str(p) for p in grader_dir.rglob("*.py")]
        + [str(p) for p in grader_dir.rglob("*.so")]
    )
    opt_so = pathlib.Path("/opt/mario-eval/grader/_fast_video.so")
    if opt_so.is_file() and str(opt_so) not in grader_files:
        grader_files.append(str(opt_so))
    n64run = shutil.which("n64run")
    corpus_cfg = pathlib.Path(corpus) / "grader.json"
    return {
        "grader_version": cfg.get("version"),
        "grader_sha256": _digest(grader_files),
        "n64run_sha256": sha256(n64run) if n64run and pathlib.Path(n64run).is_file() else None,
        "corpus_config_sha256": sha256(corpus_cfg) if corpus_cfg.is_file() else None,
        "reference_rom_sha256": index.get("rom_sha256"),
    }


def _workload_section(w):
    if w.get("section"):
        return w["section"]
    if w.get("split") == "public":
        return "public"
    if w["id"].startswith("heldout-mash-"):
        return "heldout_mash"
    return "heldout_scripted"


def _geomean(ratios):
    return math.exp(sum(math.log(max(r, 1e-12)) for r in ratios) / len(ratios))


def _section_weighted_geomean(items, ratio_by_id, section_weights):
    """Compute section-weighted geometric mean and per-section breakdown.

    Renormalizes weights across present sections so public-only checks score
    100% on public while full 25-route runs weight scripted courses above
    random button-mashing regardless of how many mash seeds exist.
    """
    by_sec = {}
    for w in items:
        by_sec.setdefault(_workload_section(w), []).append(w["id"])

    raw_weights = {}
    if section_weights:
        for sec in by_sec:
            wgt = float(section_weights.get(sec, 0.0))
            if wgt > 0.0:
                raw_weights[sec] = wgt
    if not raw_weights:
        # Unweighted fallback: proportional to workload count per section
        total = float(len(items))
        norm_weights = {sec: len(wids) / total for sec, wids in by_sec.items()}
    else:
        total_w = sum(raw_weights.values())
        norm_weights = {sec: raw_weights.get(sec, 0.0) / total_w for sec in by_sec}

    log_sum = 0.0
    sec_geos = {}
    for sec, wids in by_sec.items():
        s_geo = _geomean([ratio_by_id[wid] for wid in wids])
        sec_geos[sec] = (len(wids), norm_weights[sec], s_geo)
        if norm_weights[sec] > 0.0:
            log_sum += norm_weights[sec] * math.log(max(s_geo, 1e-12))
    return math.exp(log_sum), sec_geos


def _section_weighted_mean(items, val_by_id, section_weights):
    """Section-weighted arithmetic mean matching _section_weighted_geomean weights."""
    by_sec = {}
    for w in items:
        by_sec.setdefault(_workload_section(w), []).append(w["id"])
    raw_weights = {}
    if section_weights:
        for sec in by_sec:
            wgt = float(section_weights.get(sec, 0.0))
            if wgt > 0.0:
                raw_weights[sec] = wgt
    if not raw_weights:
        total = float(max(len(items), 1))
        norm_weights = {sec: len(wids) / total for sec, wids in by_sec.items()}
    else:
        total_w = sum(raw_weights.values())
        norm_weights = {sec: raw_weights.get(sec, 0.0) / total_w for sec in by_sec}
    acc = 0.0
    for sec, wids in by_sec.items():
        if norm_weights[sec] > 0.0 and wids:
            acc += norm_weights[sec] * (sum(float(val_by_id[wid]) for wid in wids) / float(len(wids)))
    return acc


def _hardware_score(hw):
    if hw.get("pass"):
        return 1.0
    ram_ok = 1.0 if hw.get("highest_byte", 0) <= hw.get("limit_bytes", 1) else 0.0
    bad_ops = (int(hw.get("cache_uncached_ops", 0))
               + int(hw.get("cache_cde_unaligned_ops", 0))
               + max(0, int(hw.get("cache_kseg1_dirty_synonyms", 0)) - int(hw.get("max_kseg1_dirty_synonyms", 0))))
    cache_ok = 1.0 / (1.0 + float(bad_ops))
    max_coh = hw.get("max_dcache_coherence_errors")
    coh = int(hw.get("dcache_coherence_errors", 0))
    if max_coh is None or coh <= max_coh:
        coh_ok = 1.0
    else:
        excess = float(coh - max_coh) / max(1.0, float(max_coh))
        coh_ok = 1.0 / (1.0 + excess * excess)
    return round(ram_ok * cache_ok * coh_ok, 6)


def _gated_workload_axis_scores(gp, vd, au, hw):
    """Ensure any workload failing a binary gate receives <= 0.5 on that fidelity
    axis so subtle cheats (e.g. -ffast-math failing 0.2% pixel diff while keeping
    block-SSIM ~ 1.0) can never outscore a valid submission on effective_speedup."""
    gp_raw = float(gp.get("gameplay_score", 1.0 if gp.get("pass") else 0.0))
    gp_s = gp_raw if gp.get("pass") else round(min(gp_raw, 0.5 * gp_raw), 6)

    vid_raw = float(vd.get("ssim_score", 1.0 if vd.get("pass") else 0.0))
    if vd.get("pass"):
        vid_s = vid_raw
    elif "worst_bad_fraction" in vd and "max_bad_fraction" in vd:
        lim = max(float(vd["max_bad_fraction"]), 1e-9)
        wbf = float(vd["worst_bad_fraction"])
        px_pen = 1.0 / (1.0 + (wbf / lim) ** 4)
        vid_s = round(min(vid_raw * px_pen, 0.5 * vid_raw), 6)
    else:
        vid_s = 0.0

    aud_raw = float(au.get("audio_score", 1.0 if au.get("pass") else 0.0))
    aud_s = aud_raw if au.get("pass") else round(min(aud_raw, 0.5 * aud_raw), 6)

    hw_raw = float(hw.get("hardware_score", 1.0 if hw.get("pass") else 0.0))
    hw_s = hw_raw if hw.get("pass") else round(min(hw_raw, 0.5 * hw_raw), 6)
    return gp_s, vid_s, aud_s, hw_s


_ENGINE_AGNOSTIC_FILES = (
    "src/engine/math_util.c",
    "src/engine/surface_collision.c",
    "src/engine/surface_load.c",
    "src/engine/graph_node.c",
)
_RE_COURSE_SPECIAL_CASE = re.compile(
    r"\b(?:gCurrCourseNum|gCurrLevelNum|COURSE_(?:BOB|WF|JRB|DDD|BITFS|RR))\b"
)


def detect_suspicious_source_patterns(src):
    """Non-blocking diagnostic check for public-course hardcoding inside
    course-agnostic engine modules."""
    root = pathlib.Path(src)
    hits = []
    for rel in _ENGINE_AGNOSTIC_FILES:
        p = root / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Strip C comments so documentation notes do not trigger false positives.
        clean = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        clean = re.sub(r"//[^\n]*", "", clean)
        found = sorted(set(_RE_COURSE_SPECIAL_CASE.findall(clean)))
        if found:
            hits.append({"file": rel, "tokens": found})
    return hits


def classify_failure_attribution(summary, cfg):
    """Deterministic numerical failure taxonomy so run failures and regressions
    are attributable directly from summary.json without reading transcripts."""
    status = summary.get("status")
    if status == "valid":
        return None
    gates = summary.get("gates", {})
    diag = summary.get("diagnostics", {})
    profiles = summary.get("profiles", {})
    tc = summary.get("toolchain") or (summary.get("capability_ruler") or {}).get("toolchain") or {}

    categories = []
    subcategories = []

    integ = gates.get("integrity")
    if integ and not integ.get("pass"):
        categories.append("harness_or_integrity_violation")
        if integ.get("modified"):
            subcategories.append("protected_file_modified")
        if integ.get("violations"):
            subcategories.append("static_integrity_violation")

    bld = gates.get("build")
    if bld and not bld.get("pass"):
        b_reason = str(bld.get("reason") or summary.get("reason") or "")
        if "ELF harness check" in b_reason or "benchmark harness" in b_reason or "integrity audit" in b_reason:
            if "harness_or_integrity_violation" not in categories:
                categories.append("harness_or_integrity_violation")
            subcategories.append("elf_or_play_harness_tampering")
        elif "PLAY=1" in b_reason:
            categories.append("console_play_divergence")
            subcategories.append("play_rom_build_failed")
        else:
            categories.append("build_failure")
            subcategories.append("build_timeout" if "timed out" in b_reason else "compile_or_link_error")

    play_rt = gates.get("play_runtime")
    if play_rt and not play_rt.get("pass"):
        if "console_play_divergence" not in categories:
            categories.append("console_play_divergence")
        subcategories.append(f"play_runtime:{play_rt.get('status', 'failed')}")

    if diag.get("public_valid") is True and diag.get("heldout_valid") is False:
        categories.append("public_to_heldout_overfitting")
        secs = diag.get("sections", {})
        if secs.get("heldout_scripted", {}).get("valid") is False:
            subcategories.append("unseen_course_mechanics")
        if secs.get("heldout_mash", {}).get("valid") is False:
            subcategories.append("high_entropy_input_fragility")

    ex_gate = gates.get("execution")
    if ex_gate and not ex_gate.get("pass"):
        ex_failed = [v for v in ex_gate.get("workloads", {}).values() if not v.get("pass")]
        fault_excs = sorted({str(v.get("first_fault_exc")) for v in ex_failed if v.get("first_fault_exc")})
        if "TRAP" in fault_excs or any(int(v.get("cpu_trap_exceptions", 0) or 0) > 0 for v in ex_failed):
            categories.append("cpu_isa_trap")
            subcategories.append("cpu_trap_exception(TRAP)")
        else:
            categories.append("crash_or_hang")
        for exc in fault_excs:
            if exc == "TRAP":
                continue
            elif exc in ("ADEL", "ADES"):
                subcategories.append(f"unaligned_memory_fault({exc})")
            elif exc in ("TLBL", "TLBS", "TLBM"):
                subcategories.append(f"tlb_or_invalid_ptr_fault({exc})")
            elif exc == "RI":
                subcategories.append("illegal_instruction_fault(RI)")
            elif exc == "BP":
                subcategories.append("breakpoint_or_assert(BP)")
            elif exc in ("OV", "FPE"):
                subcategories.append(f"arithmetic_or_fpu_trap({exc})")
            else:
                subcategories.append(f"cpu_exception({exc})")
        if not fault_excs and int(tc.get("trap_insns", 0) or 0) > 0:
            subcategories.append("elf_contains_mips_trap_insns")
        ex_statuses = sorted({str(v.get("status", "failed")) for v in ex_failed})
        for st in ex_statuses:
            subcategories.append(f"execution:{st}")
        if not fault_excs and any(st in ("field_limit", "timeout") for st in ex_statuses):
            subcategories.append("infinite_loop_or_deadlock")

    hw_gate = gates.get("hardware")
    if hw_gate and not hw_gate.get("pass"):
        hw_wls = [v for v in hw_gate.get("workloads", {}).values() if not v.get("pass")]
        if hw_wls:
            categories.append("hardware_safety_violation")
            if any(v.get("highest_byte", 0) > v.get("limit_bytes", 0x400000) for v in hw_wls):
                subcategories.append("rdram_4mb_overflow")
            if any(v.get("cache_uncached_ops", 0) > 0 for v in hw_wls):
                subcategories.append("kseg1_uncached_cache_op")
            if any(v.get("cache_cde_unaligned_ops", 0) > 0 for v in hw_wls):
                subcategories.append("unaligned_cache_cde")
            if any(v.get("cache_kseg1_dirty_synonyms", 0) > v.get("max_kseg1_dirty_synonyms", 0) for v in hw_wls):
                subcategories.append("kseg1_dirty_synonym")
            if any(
                v.get("max_dcache_coherence_errors") is not None
                and v.get("dcache_coherence_errors", 0) > v["max_dcache_coherence_errors"]
                for v in hw_wls
            ):
                subcategories.append("dma_dcache_coherence")

    gp_gate = gates.get("gameplay")
    if gp_gate and not gp_gate.get("pass"):
        gp_wls = [v for v in gp_gate.get("workloads", {}).values() if not v.get("pass")]
        if gp_wls:
            categories.append("physics_or_state_desync")
            gp_fields = sorted({
                str(v.get("field") or v.get("reason") or "desync")
                for v in gp_wls
            })
            for fld in gp_fields:
                subcategories.append(f"gameplay:{fld}")

    vd_gate = gates.get("video")
    if vd_gate and not vd_gate.get("pass"):
        vd_wls = [v for v in vd_gate.get("workloads", {}).values() if not v.get("pass")]
        if vd_wls:
            categories.append("visual_regression")
            subtle = all(
                float(v.get("ssim_score", 0.0)) >= 0.99 and float(v.get("worst_bad_fraction", 1.0)) <= 0.02
                for v in vd_wls
            )
            subcategories.append("subpixel_or_edge_drift" if subtle else "structural_visual_corruption")

    au_gate = gates.get("audio")
    if au_gate and not au_gate.get("pass"):
        au_wls = [v for v in au_gate.get("workloads", {}).values() if not v.get("pass")]
        if au_wls:
            categories.append("audio_regression")
            if any("silent" in str(v.get("reason", "")) for v in au_wls):
                subcategories.append("audio:unexpected_sound_in_silence")
            elif any(v.get("reason") for v in au_wls):
                subcategories.append("audio:format_or_length_mismatch")
            else:
                subcategories.append("audio:spectral_or_snr_degradation")

    bad_profiles = sorted([p for p, v in profiles.items() if not v.get("valid", True)])
    if bad_profiles:
        categories.append("profile_budget_regression")
        for bp in bad_profiles:
            subcategories.append(f"budget:{bp}")

    if not categories and status == "invalid":
        categories.append("unclassified_invalid")

    if not categories:
        return None

    return {
        "primary_category": categories[0],
        "categories": categories,
        "subcategories": subcategories,
        "public_only_pass": bool(diag.get("public_valid") is True and diag.get("heldout_valid") is False),
    }


def _build_capability_ruler(items, completed, passed_ids, summary, cfg, index, section_weights, gen_ratio, toolchain=None):
    """Multi-dimensional numerical capability decomposition across subsystems
    and evaluation splits (emitted on both valid and invalid runs)."""
    if not completed:
        return {"verified": False, "toolchain": toolchain} if toolchain else None
    subsystems = {
        "console": "est_console_ms",
        "stutter_p99": "est_console_p99_ms",
        "cpu": "cpu_effective_cycles",
        "rsp": "rsp_busy",
        "rsp_gfx": "rsp_gfx_ms",
        "rsp_aud": "rsp_aud_ms",
        "rdp_effective": "rdp_effective_cycles",
        "rdp_raw": "rdp_busy",
        "rdram_traffic": "rdram_bytes",
        "memory_footprint": "footprint_bytes",
    }
    sub_speedups = {}
    sub_cost_saved = {}
    for label, mkey in subsystems.items():
        if all(mkey in summary["workloads"][w["id"]]["ratios"] for w in completed):
            r_map = {w["id"]: summary["workloads"][w["id"]]["ratios"][mkey] for w in completed}
            geo, _ = _section_weighted_geomean(completed, r_map, section_weights)
            sub_speedups[label] = round(1.0 / geo, 6) if geo > 0 else 0.0
            sub_cost_saved[label] = round(1.0 - geo, 6)

    bn_counts = {"cpu": 0, "rsp": 0, "rdp": 0, "mem": 0}
    for w in completed:
        m = summary["workloads"][w["id"]]["metrics"]
        pairs = [
            ("cpu", float(m.get("cpu_ms", 0.0))),
            ("rsp", float(m.get("rsp_ms", 0.0))),
            ("rdp", float(m.get("rdp_ms", 0.0))),
            ("mem", float(m.get("mem_ms", 0.0))),
        ]
        dom = max(pairs, key=lambda kv: kv[1])[0]
        bn_counts[dom] += 1
    n_comp = float(len(completed))
    bn_share = {k: round(v / n_comp, 4) for k, v in bn_counts.items()}

    p_metric = cfg["profiles"].get("console", next(iter(cfg["profiles"].values())))["metric"]
    o2_ref = index.get("o2_reference", {})
    raw_vs_o2 = None
    compiler_tier_progress = None
    if o2_ref and all(w["id"] in o2_ref for w in completed):
        o2_cand_r = {
            w["id"]: (summary["workloads"][w["id"]]["metrics"][p_metric] / o2_ref[w["id"]][p_metric]
                      if o2_ref[w["id"]].get(p_metric) else 1.0)
            for w in completed
        }
        o2_geo, _ = _section_weighted_geomean(completed, o2_cand_r, section_weights)
        if o2_geo > 0:
            raw_vs_o2 = round(1.0 / o2_geo, 6)
        raw_sp = sub_speedups.get("console", 0.0)
        if raw_sp > 0 and raw_vs_o2 and raw_vs_o2 > 0:
            # o2_sp_vs_vanilla = raw_sp / raw_vs_o2
            o2_sp = raw_sp / raw_vs_o2
            if o2_sp > 1.001:
                compiler_tier_progress = round(
                    min(1.0, max(0.0, math.log(max(raw_sp, 1.0)) / math.log(o2_sp))), 4
                )

    splits = {}
    by_sec = {}
    for w in items:
        by_sec.setdefault(_workload_section(w), []).append(w)
    for sec, sec_items in by_sec.items():
        comp_sec = [w for w in sec_items if w["id"] in summary["workloads"]]
        passed_sec = [w for w in sec_items if w["id"] in passed_ids]
        sec_sp = None
        if len(comp_sec) == len(sec_items) and comp_sec:
            s_geo = _geomean([summary["workloads"][w["id"]]["ratios"][p_metric] for w in comp_sec])
            sec_sp = round(1.0 / s_geo, 6) if s_geo > 0 else 0.0
        splits[sec] = {
            "passed": len(passed_sec),
            "total": len(sec_items),
            "pass_rate": round(len(passed_sec) / float(max(len(sec_items), 1)), 4),
            **({"raw_console_speedup": sec_sp} if sec_sp is not None else {}),
        }

    all_passed = (len(passed_ids) == len(items))
    return {
        "verified": all_passed,
        **({"toolchain": toolchain} if toolchain else {}),
        "subsystem_speedups": sub_speedups,
        "subsystem_cost_saved": sub_cost_saved,
        "dominant_bottleneck_share": bn_share,
        **({"raw_vs_o2_speedup": raw_vs_o2} if raw_vs_o2 is not None else {}),
        **({"compiler_tier_progress": compiler_tier_progress} if compiler_tier_progress is not None else {}),
        "splits": splits,
        **({"generalization_ratio": gen_ratio} if gen_ratio is not None else {}),
    }


def grade(args):
    t0 = time.time()
    corpus = pathlib.Path(args.corpus)
    cfg = json.loads((corpus / "grader.json").read_text())
    if args.play_smoke and not cfg.get("play_rom"):
        raise GraderError("PLAY runtime smoke is not supported for this target")
    cache = pathlib.Path(args.cache)
    index = json.loads((cache / "index.json").read_text())
    schema_name = cfg.get("contract", index.get("contract", "pips-garden"))
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "version": cfg["version"],
        "target": cfg.get("target", schema_name),
        "fingerprint": grader_fingerprint(corpus, cfg, index),
        "gates": {},
        "workloads": {},
        "rewards": {},
        "speedups": {},
        "cost_saved": {},
    }

    def finish(status, reason=None):
        summary["status"] = status
        if reason:
            summary["reason"] = reason
        if status == "invalid":
            summary["failures"] = failure_details(summary["gates"])
            summary["rewards"] = {p: -1.0 for p in cfg["profiles"]}
            summary["speedups"] = {p: 0.0 for p in cfg["profiles"]}
            summary["cost_saved"] = {p: 0.0 for p in cfg["profiles"]}
            summary.setdefault("fidelity", {
                "execution": 0.0,
                "gameplay": 0.0,
                "video_ssim": 0.0,
                "audio": 0.0,
                "hardware": 0.0,
                "overall": 0.0,
                "effective_speedups": {p: 0.0 for p in cfg["profiles"]},
                "effective_cost_saved": {p: 0.0 for p in cfg["profiles"]},
            })
        attr = classify_failure_attribution(summary, cfg)
        if attr is not None:
            summary["failure_attribution"] = attr
        summary["grader_seconds"] = round(time.time() - t0, 1)
        (out / "summary.json").write_text(json.dumps(_sanitize_json(summary), indent=1, allow_nan=False))
        return summary

    # 1. integrity
    changed = [f for f in cfg["protected_files"]
               if not (pathlib.Path(args.source) / f).exists()
               or sha256(pathlib.Path(args.source) / f) != index["protected"][f]]
    audit_errs = audit_submission_integrity(args.source, cfg)
    summary["gates"]["integrity"] = {"pass": not changed and not audit_errs, "modified": changed,
                                     **({"violations": audit_errs} if audit_errs else {})}
    if changed:
        return finish("invalid", f"protected files modified: {changed}")
    if audit_errs:
        return finish("invalid", f"integrity audit failed: {audit_errs[0]}")

    # 2. build. Private measurements require a separate build container.
    # Public local checks can build in-process with an artifact integrity check.
    isolated = args.built is not None
    if not isolated and (args.split != "public" or args.heldout):
        raise GraderError("held-out grading requires an isolated build; use scripts/grade.sh")
    items = workloads(args.corpus, cfg, args.split, args.heldout)
    if getattr(args, "workloads", None):
        if args.split != "public" or args.heldout:
            raise GraderError("--workloads is only allowed on public local checks")
        wanted = [x.strip() for x in args.workloads.split(",") if x.strip()]
        by_id = {w["id"]: w for w in items}
        unknown = [x for x in wanted if x not in by_id]
        if unknown:
            raise GraderError(f"unknown workloads: {unknown} (available: {sorted(by_id)})")
        items = [by_id[x] for x in wanted]
    missing = [w["id"] for w in items if w["id"] not in index["workloads"]]
    if missing:
        raise GraderError(f"no baseline reference for {missing}; run precompute with this split")
    replay_hashes = {w["id"]: sha256(w["replay"]) for w in items}
    mismatches = [wid for wid, digest in replay_hashes.items()
                  if index["workloads"][wid]["replay_sha256"] != digest]
    if mismatches:
        raise GraderError(f"replay differs from the baseline reference: {mismatches}")
    summary["workload_set"] = hashlib.sha256(
        json.dumps(replay_hashes, sort_keys=True).encode()
    ).hexdigest()
    trusted = None if isolated else measurement_artifacts(args.corpus, cache, items)
    if isolated:
        rom, build_err = load_submission_build(pathlib.Path(args.built))
    else:
        rom, build_err = build(args.source, cfg, out / "build.log", keep_play=args.play_smoke)
    if isolated and rom is not None and args.play_smoke and not (rom.parent / "play.z64").is_file():
        raise GraderError("PLAY=1 ROM missing from build handoff")
    summary["gates"]["build"] = {"pass": rom is not None, **({"reason": build_err} if build_err else {})}
    if rom is None:
        return finish("invalid", build_err or "build failed; see build.log")
    if not isolated and measurement_artifacts(args.corpus, cache, items) != trusted:
        raise GraderError("the submission's build modified grading artifacts "
                          "(the emulator, the grader, the corpus, the reference cache or the replays)")
    try:
        build_meta = {}
        meta_file = rom.parent / "built.meta.json"
        if meta_file.is_file():
            try:
                build_meta = json.loads(meta_file.read_text())
            except Exception:
                build_meta = {}
        if build_meta:
            summary["toolchain"] = build_meta
        summary["rom_sha256"] = sha256(rom)
        summary["rom_bytes"] = rom.stat().st_size
        if args.play_smoke:
            result = play_runtime_smoke(rom.parent / "play.z64", out / "play-smoke", cfg["run_timeout_s"], cfg=cfg)
            summary["gates"]["play_runtime"] = result
            if not result["pass"]:
                return finish("invalid", f"PLAY=1 runtime smoke failed: {result['status']}")

        # 3. run
        budget = lambda wid: int(index["workloads"][wid]["vi_fields"] * cfg["max_fields_factor"]) + 600
        results = run_all(rom, items, cfg["frames"], out / "runs", budget, cfg["run_timeout_s"])
    finally:
        if not isolated:
            shutil.rmtree(rom.parent, ignore_errors=True)

    execution, gameplay, video, audio, hardware = {}, {}, {}, {}, {}
    completed = []
    for w in items:
        wid, res = w["id"], results[w["id"]]
        execution[wid] = {"pass": res.get("status") == "completed", **res}
        if execution[wid]["pass"]:
            completed.append(w)

    ncpus = int(os.environ.get("MEV_JOBS", os.cpu_count() or 4))
    gate_workers = max(1, min(ncpus, len(completed))) if completed else 1
    vid_threads = max(1, min(ncpus, max(8, (ncpus * 2) // gate_workers)))

    def _verify_one(w):
        wid = w["id"]
        cand = load_run(out / "runs" / wid)
        ref_dir = cache / "runs" / wid
        ref = load_run(ref_dir)
        gp = compare_obs(ref["obs"], cand["obs"], cfg["frames"], schema_name, cfg)
        vd = compare_video(ref_dir, reference_variants(index["workloads"][wid], index.get("variants", [])),
                           cand["video_path"], ref["rows"], cand["rows"], cfg, max_threads=vid_threads)
        au = compare_audio(ref["audio"], cand["audio"], ref["rows"], cand["rows"], cfg)
        m = metrics(cand)
        max_coh = cfg["hardware"].get("max_dcache_coherence_errors")
        if max_coh is None and "max_dcache_coherence_errors_per_frame" in cfg["hardware"]:
            max_coh = int(cfg["hardware"]["max_dcache_coherence_errors_per_frame"] * cfg["frames"])
        coh_ok = True if max_coh is None else (m.get("dcache_coherence_errors", 0) <= max_coh)
        max_syn = int(cfg["hardware"].get("max_kseg1_dirty_synonyms", 0))
        syn_ok = (m.get("cache_kseg1_dirty_synonyms", 0) <= max_syn)
        hw = {"pass": (m["highest_byte"] <= cfg["hardware"]["rdram_bytes"]
                       and m.get("cache_uncached_ops", 0) == 0
                       and m.get("cache_cde_unaligned_ops", 0) == 0
                       and syn_ok
                       and coh_ok),
              "highest_byte": m["highest_byte"], "limit_bytes": cfg["hardware"]["rdram_bytes"],
              "cache_uncached_ops": m.get("cache_uncached_ops", 0),
              "cache_cde_unaligned_ops": m.get("cache_cde_unaligned_ops", 0),
              "cache_kseg1_dirty_synonyms": m.get("cache_kseg1_dirty_synonyms", 0),
              "max_kseg1_dirty_synonyms": max_syn,
              "dcache_coherence_errors": m.get("dcache_coherence_errors", 0),
              **({"max_dcache_coherence_errors": max_coh} if max_coh is not None else {})}
        hw["hardware_score"] = _hardware_score(hw)
        # Recompute baseline metrics directly from ref's frames.jsonl so candidate
        # and baseline are always guaranteed to share the exact same metrics() model.
        base = metrics(ref)
        wl_entry = {
            "metrics": m,
            "ratios": {k: (m[k] / base[k] if base.get(k) else 1.0) for k in RATIO_KEYS},
        }
        (out / "runs" / wid / "video.bin").unlink()
        return wid, gp, vd, au, hw, wl_entry

    with concurrent.futures.ThreadPoolExecutor(max_workers=gate_workers) as pool:
        for wid, gp, vd, au, hw, wl_entry in pool.map(_verify_one, completed):
            gameplay[wid] = gp
            video[wid] = vd
            audio[wid] = au
            hardware[wid] = hw
            summary["workloads"][wid] = wl_entry

    summary["gates"]["execution"] = {
        "pass": len(execution) == len(items) and all(v["pass"] for v in execution.values()),
        "workloads": execution,
    }
    for name, table in (("gameplay", gameplay), ("video", video),
                        ("audio", audio), ("hardware", hardware)):
        gate_entry = {
            "pass": bool(table) and all(v["pass"] for v in table.values()),
            "workloads": table,
        }
        if len(table) < len(items):
            gate_entry["evaluated"] = len(table)
            gate_entry["skipped"] = len(items) - len(table)
        summary["gates"][name] = gate_entry

    # Continuous 5-axis fidelity scores (computed on BOTH valid and invalid runs
    # for fine-grained diagnostic signal; strict headline rewards stay binary).
    section_weights = cfg.get("section_weights")
    target_frames = max(1, int(cfg["frames"]))
    exec_scores = {}
    gp_scores = {}
    vid_scores = {}
    aud_scores = {}
    hw_scores = {}
    for w in items:
        wid = w["id"]
        ex = execution.get(wid, {})
        if ex.get("pass"):
            exec_scores[wid] = 1.0
            gp_s, vid_s, aud_s, hw_s = _gated_workload_axis_scores(
                gameplay.get(wid, {}), video.get(wid, {}), audio.get(wid, {}), hardware.get(wid, {})
            )
            gp_scores[wid] = gp_s
            vid_scores[wid] = vid_s
            aud_scores[wid] = aud_s
            hw_scores[wid] = hw_s
        else:
            done_f = max(0, int(ex.get("frames", 0)))
            exec_scores[wid] = round(0.5 * min(1.0, float(done_f) / float(target_frames)), 6)
            gp_scores[wid] = 0.0
            vid_scores[wid] = 0.0
            aud_scores[wid] = 0.0
            hw_scores[wid] = 0.0

    fid_exec = round(_section_weighted_mean(items, exec_scores, section_weights), 6)
    fid_gp = round(_section_weighted_mean(items, gp_scores, section_weights), 6)
    fid_vid = round(_section_weighted_mean(items, vid_scores, section_weights), 6)
    fid_aud = round(_section_weighted_mean(items, aud_scores, section_weights), 6)
    fid_hw = round(_section_weighted_mean(items, hw_scores, section_weights), 6)
    fid_overall = round(fid_exec * fid_gp * fid_vid * fid_aud * fid_hw, 6)

    effective_speedups = {}
    effective_cost_saved = {}
    if completed:
        gate_factor = fid_overall ** 8
        for profile, pcfg in cfg["profiles"].items():
            mkey = pcfg["metric"]
            r_by_id = {w["id"]: summary["workloads"][w["id"]]["ratios"][mkey] for w in completed}
            raw_geo, _ = _section_weighted_geomean(completed, r_by_id, section_weights)
            raw_sp = (1.0 / raw_geo) if raw_geo > 0 else 0.0
            effective_speedups[profile] = round(raw_sp * gate_factor, 6)
            effective_cost_saved[profile] = round(max(0.0, 1.0 - raw_geo) * gate_factor, 6)
    else:
        effective_speedups = {p: 0.0 for p in cfg["profiles"]}
        effective_cost_saved = {p: 0.0 for p in cfg["profiles"]}

    pub_items = [w for w in items if w["split"] == "public"]
    ho_items = [w for w in items if w["split"] != "public"]
    gen_ratio = None
    if pub_items and ho_items and all(w["id"] in summary["workloads"] for w in pub_items) and all(w["id"] in summary["workloads"] for w in ho_items):
        p_key = cfg["profiles"].get("console", next(iter(cfg["profiles"].values())))["metric"]
        pub_geo = _geomean([summary["workloads"][w["id"]]["ratios"][p_key] for w in pub_items])
        ho_r = {w["id"]: summary["workloads"][w["id"]]["ratios"][p_key] for w in ho_items}
        ho_geo, _ = _section_weighted_geomean(ho_items, ho_r, section_weights)
        if pub_geo > 0 and ho_geo > 0:
            gen_ratio = round((1.0 / ho_geo) / (1.0 / pub_geo), 6)

    summary["fidelity"] = {
        "execution": fid_exec,
        "gameplay": fid_gp,
        "video_ssim": fid_vid,
        "audio": fid_aud,
        "hardware": fid_hw,
        "overall": fid_overall,
        "effective_speedups": effective_speedups,
        "effective_cost_saved": effective_cost_saved,
        **({"generalization_ratio": gen_ratio} if gen_ratio is not None else {}),
    }

    # Diagnostic sub-metrics preserved even on invalid runs (headline reward stays -1.0).
    passed_wls = [
        w for w in items
        if execution.get(w["id"], {}).get("pass")
        and gameplay.get(w["id"], {}).get("pass")
        and video.get(w["id"], {}).get("pass")
        and audio.get(w["id"], {}).get("pass")
        and hardware.get(w["id"], {}).get("pass")
    ]
    passed_ids = {w["id"] for w in passed_wls}
    sec_diag = {}
    for w in items:
        sec = _workload_section(w)
        rec = sec_diag.setdefault(sec, {"passed": 0, "total": 0})
        rec["total"] += 1
        if w["id"] in passed_ids:
            rec["passed"] += 1
    for rec in sec_diag.values():
        rec["valid"] = (rec["passed"] == rec["total"])
    suspicious_patterns = detect_suspicious_source_patterns(args.source)
    diag = {
        "workloads_total": len(items),
        "workloads_completed": len(completed),
        "workloads_passed": len(passed_wls),
        "sections": sec_diag,
        "public_valid": all(w["id"] in passed_ids for w in pub_items) if pub_items else None,
        "heldout_valid": all(w["id"] in passed_ids for w in ho_items) if ho_items else None,
        **({"generalization_ratio": gen_ratio} if gen_ratio is not None else {}),
        **({"suspicious_source_patterns": suspicious_patterns} if suspicious_patterns else {}),
    }
    if pub_items and all(w["id"] in summary["workloads"] for w in pub_items):
        diag["unverified_public_speedups"] = {
            profile: round(1.0 / _geomean([summary["workloads"][w["id"]]["ratios"][pcfg["metric"]] for w in pub_items]), 6)
            for profile, pcfg in cfg["profiles"].items()
        }
    if passed_wls:
        diag["unverified_passed_speedups"] = {
            profile: round(1.0 / _geomean([summary["workloads"][w["id"]]["ratios"][pcfg["metric"]] for w in passed_wls]), 6)
            for profile, pcfg in cfg["profiles"].items()
        }
    summary["diagnostics"] = diag
    cap_ruler = _build_capability_ruler(
        items, completed, passed_ids, summary, cfg, index, section_weights, gen_ratio,
        toolchain=summary.get("toolchain"),
    )
    if cap_ruler is not None:
        summary["capability_ruler"] = cap_ruler

    failed = [g for g, v in summary["gates"].items() if not v["pass"]]
    if failed:
        return finish("invalid", f"failed gates: {failed}")

    # 4. rewards and unbounded/log speedups, one per profile
    speed_ratios = [summary["workloads"][w["id"]]["ratios"]["cpu_effective_cycles"] for w in items]
    rdp_ratios = [summary["workloads"][w["id"]]["ratios"]["rdp_busy"] for w in items]
    footprint_ratios = [summary["workloads"][w["id"]]["ratios"]["footprint_bytes"] for w in items]
    o2_ref = index.get("o2_reference", {})

    for profile, pcfg in cfg["profiles"].items():
        metric_key = pcfg["metric"]
        ratio_by_id = {w["id"]: summary["workloads"][w["id"]]["ratios"][metric_key] for w in items}
        ratios = [ratio_by_id[w["id"]] for w in items]
        unweighted_geo = _geomean(ratios)
        geo, sec_geos = _section_weighted_geomean(items, ratio_by_id, section_weights)
        entry = {
            "metric": metric_key,
            "geomean_ratio": geo,
            "unweighted_geomean_ratio": unweighted_geo,
        }
        worst = max(ratios)
        worst_id = items[ratios.index(worst)]["id"]
        if worst > 1.0 + pcfg["max_workload_regression"] + 1e-12:
            entry.update(valid=False, reason=f"{metric_key} regressed {100 * (worst - 1):.3g}% on {worst_id} "
                                             f"(limit {100 * pcfg['max_workload_regression']:g}%)")
        elif "speed_budget" in pcfg and max(speed_ratios) > 1.0 + pcfg["speed_budget"] + 1e-12:
            slow_id = items[speed_ratios.index(max(speed_ratios))]["id"]
            entry.update(valid=False, reason=f"frame time regressed {100 * (max(speed_ratios) - 1):.3g}% on {slow_id} "
                                             f"(budget {100 * pcfg['speed_budget']:g}%)")
        elif "rdp_budget" in pcfg and max(rdp_ratios) > 1.0 + pcfg["rdp_budget"] + 1e-12:
            rdp_id = items[rdp_ratios.index(max(rdp_ratios))]["id"]
            entry.update(valid=False, reason=f"rdp_busy regressed {100 * (max(rdp_ratios) - 1):.3g}% on {rdp_id} "
                                             f"(budget {100 * pcfg['rdp_budget']:g}%)")
        elif "footprint_budget" in pcfg and max(footprint_ratios) > 1.0 + pcfg["footprint_budget"] + 1e-12:
            mem_id = items[footprint_ratios.index(max(footprint_ratios))]["id"]
            entry.update(valid=False, reason=f"footprint_bytes regressed {100 * (max(footprint_ratios) - 1):.3g}% on {mem_id} "
                                             f"(budget {100 * pcfg['footprint_budget']:g}%)")
        else:
            entry.update(valid=True)

        # Reward is log-scaled so that 2x, 4x and 8x stay clearly apart:
        # log2(speedup) / reward_log2_scale (default 4, so 16x scores 1.0).
        # Not capped above; any failed gate or budget scores -1.
        scale = cfg.get("reward_log2_scale", 4.0)
        entry["speedup"] = round(1.0 / geo, 6) if entry["valid"] and geo > 0 else 0.0
        entry["unweighted_speedup"] = round(1.0 / unweighted_geo, 6) if entry["valid"] and unweighted_geo > 0 else 0.0
        entry["cost_saved"] = round(1.0 - geo, 6) if entry["valid"] else 0.0
        entry["unweighted_cost_saved"] = round(1.0 - unweighted_geo, 6) if entry["valid"] else 0.0
        entry["log2_speedup"] = round(-math.log2(geo), 6) if entry["valid"] and geo > 0 else None
        entry["reward"] = max(-1.0, entry["log2_speedup"] / scale) if entry["valid"] else -1.0

        sec_summary = {}
        has_o2 = bool(o2_ref) and all(w["id"] in o2_ref for w in items)
        o2_sec_geos = {}
        if has_o2:
            o2_ratio_by_id = {
                w["id"]: (summary["workloads"][w["id"]]["metrics"][metric_key] / o2_ref[w["id"]][metric_key]
                          if o2_ref[w["id"]].get(metric_key) else 1.0)
                for w in items
            }
            o2_unweighted_geo = _geomean([o2_ratio_by_id[w["id"]] for w in items])
            o2_geo, o2_sec_geos = _section_weighted_geomean(items, o2_ratio_by_id, section_weights)
            entry["vs_o2_ratio"] = o2_geo
            entry["vs_o2_speedup"] = round(1.0 / o2_geo, 6) if entry["valid"] and o2_geo > 0 else 0.0
            entry["vs_o2_cost_saved"] = round(1.0 - o2_geo, 6) if entry["valid"] else 0.0
            entry["unweighted_vs_o2_speedup"] = (
                round(1.0 / o2_unweighted_geo, 6) if entry["valid"] and o2_unweighted_geo > 0 else 0.0
            )

        for sec, (cnt, wgt, s_geo) in sec_geos.items():
            s_entry = {
                "count": cnt,
                "weight": round(wgt, 6),
                "speedup": round(1.0 / s_geo, 6) if s_geo > 0 else 0.0,
                "cost_saved": round(1.0 - s_geo, 6),
            }
            if sec in o2_sec_geos and o2_sec_geos[sec][2] > 0:
                s_entry["vs_o2_speedup"] = round(1.0 / o2_sec_geos[sec][2], 6)
                s_entry["vs_o2_cost_saved"] = round(1.0 - o2_sec_geos[sec][2], 6)
            sec_summary[sec] = s_entry
        entry["sections"] = sec_summary
        if pub_items and ho_items:
            p_pub_geo = _geomean([ratio_by_id[w["id"]] for w in pub_items])
            p_ho_geo, _ = _section_weighted_geomean(ho_items, {w["id"]: ratio_by_id[w["id"]] for w in ho_items}, section_weights)
            if p_pub_geo > 0 and p_ho_geo > 0:
                entry["generalization_ratio"] = round((1.0 / p_ho_geo) / (1.0 / p_pub_geo), 6)

        summary["rewards"][profile] = entry["reward"]
        summary["speedups"][profile] = entry["speedup"]
        summary["cost_saved"][profile] = entry["cost_saved"]
        summary.setdefault("profiles", {})[profile] = entry
    return finish("valid")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("precompute")
    p_pre.add_argument("source")
    p_pre.add_argument("--corpus", required=True)
    p_pre.add_argument("--cache", required=True)
    p_pre.add_argument("--split", default="public", choices=["public", "heldout", "all"])
    p_pre.add_argument("--heldout")
    p_pre.add_argument("--o2-patch")

    p_build = sub.add_parser("build")
    p_build.add_argument("source")
    p_build.add_argument("--config", required=True)
    p_build.add_argument("--out", required=True)
    p_build.add_argument("--play-smoke", action="store_true", help="retain the linked PLAY=1 ROM")

    p_grd = sub.add_parser("grade")
    p_grd.add_argument("source")
    p_grd.add_argument("--corpus", required=True)
    p_grd.add_argument("--cache", required=True)
    p_grd.add_argument("--split", default="public", choices=["public", "heldout", "all"])
    p_grd.add_argument("--heldout")
    p_grd.add_argument("--out", required=True)
    p_grd.add_argument("--built", help="isolated build handoff directory")
    p_grd.add_argument("--workloads", help="comma-separated public workload IDs (local checks only)")
    p_grd.add_argument("--play-smoke", action="store_true", help="require the PLAY=1 ROM to boot and render")

    p_exp = sub.add_parser("export-public")
    p_exp.add_argument("--corpus", required=True)
    p_exp.add_argument("--cache", required=True)
    p_exp.add_argument("--out", required=True)

    args = ap.parse_args()
    try:
        if args.cmd == "precompute":
            precompute(args)
        elif args.cmd == "build":
            build_submission(args)
        elif args.cmd == "export-public":
            export_public(args)
        else:
            s = grade(args)
            print(json.dumps({
                "status": s["status"],
                "reason": s.get("reason"),
                **({"failure_attribution": s["failure_attribution"]} if s.get("failure_attribution") else {}),
                **({"failures": s["failures"]} if s.get("failures") else {}),
                **({"fidelity": s["fidelity"]} if s.get("fidelity") else {}),
                "rewards": s["rewards"],
                "speedups": s.get("speedups"),
                "cost_saved": s.get("cost_saved"),
            }, indent=1))
    except GraderError as e:
        print(json.dumps({"status": "grader_error", "reason": str(e)}), file=sys.stderr)
        if args.cmd == "grade":
            pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
            (pathlib.Path(args.out) / "summary.json").write_text(
                json.dumps({"status": "grader_error", "reason": str(e)}, indent=1))
        sys.exit(3)


if __name__ == "__main__":
    main()
