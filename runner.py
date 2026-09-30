"""Runs the engine (deobf/deob.py) on one script in a throwaway folder.

No Discord code in here, so it can be tested on its own. The engine is always
started with --no-devirt: behaviour trace only (what the script does to the
environment), never the devirtualizer.
"""
import asyncio
import os
import re
import signal
import sys
import tempfile
import time
from asyncio.subprocess import DEVNULL, PIPE
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEOB_SCRIPT = ROOT / "deobf" / "deob.py"

# (label, regex). Heuristic hints for triage, not a verdict.
INDICATORS = [
    ("Discord webhook URL", r"discord(?:app)?\.com/api/webhooks/"),
    ("HTTP request", r"\b(?:HttpGet|HttpGetAsync|HttpPost|HttpPostAsync|RequestAsync|http_request)\b|\brequest\s*\("),
    ("loadstring (runs other code)", r"\bloadstring\s*\("),
    (".ROBLOSECURITY / cookie access", r"ROBLOSECURITY|\bgetcookie\b"),
    ("Clipboard write", r"\b(?:setclipboard|toclipboard)\b"),
    ("Kick / Shutdown", r":Kick\s*\(|:Shutdown\s*\("),
    ("Teleport", r"TeleportService|:Teleport\s*\(|TeleportAsync"),
    ("Trade / purchase prompts", r"PromptPurchase|PromptProductPurchase|TradeService|:SendTradeRequest"),
]


@dataclass
class Result:
    ok: bool
    output: bytes = b""
    obfuscator: str = "unknown"
    seconds: float = 0.0
    hints: list = field(default_factory=list)   # [(label, count)]
    error: str = ""


def scan(text: str):
    hints = []
    for label, pattern in INDICATORS:
        n = len(re.findall(pattern, text))
        if n:
            hints.append((label, n))
    return hints


def _kill(proc):
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)   # engine + luau children share the session
        else:
            proc.kill()
    except ProcessLookupError:
        pass


def _short_error(stderr: str, tmp: str) -> str:
    lines = [l.strip() for l in stderr.replace(tmp, "<tmp>").splitlines() if l.strip()]
    bang = [l for l in lines if l.startswith("[!]")]
    picked = bang[-3:] if bang else lines[-3:]
    return " ".join(picked)[:400] or "The engine failed without a message."


async def run(data: bytes, timeout: int = 120, script: Path = DEOB_SCRIPT) -> Result:
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fowa_") as tmp:
        inp = os.path.join(tmp, "input.lua")     # never use the uploader's file name
        out = os.path.join(tmp, "result.lua")
        Path(inp).write_bytes(data)
        cmd = [sys.executable, "-W", "ignore", str(script), inp, "-o", out,
               "--no-devirt", "--no-pypy", "--timeout", str(max(20, timeout - 15))]
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=tmp, stdin=DEVNULL, stdout=DEVNULL, stderr=PIPE,
            start_new_session=True)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            _kill(proc)
            await proc.wait()
            return Result(False, seconds=time.monotonic() - t0,
                          error="Timed out after %ds. The script probably loops forever or is too heavy." % timeout)
        except asyncio.CancelledError:
            _kill(proc)
            raise
        _kill(proc)   # stray children, if any
        stderr = (err or b"").decode("utf-8", "replace")
        m = re.search(r"\[\*\] obfuscator: (.+)", stderr)
        label = re.sub(r"\s*\(detected, [0-9.]+\)\s*$", "", m.group(1)).strip() if m else "unknown"
        seconds = time.monotonic() - t0
        if proc.returncode == 0 and os.path.exists(out):
            body = Path(out).read_bytes()
            return Result(True, body, label, seconds, scan(body.decode("latin-1")))
        return Result(False, obfuscator=label, seconds=seconds, error=_short_error(stderr, tmp))
