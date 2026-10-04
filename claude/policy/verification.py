"""Execute repository-declared checks and bind their receipts to checkout inputs."""

from __future__ import annotations

import hashlib
import contextlib
import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path


CONTRACT_PATH = Path(".harness/verification.json")


class VerificationError(Exception):
    pass


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def declaration(repo: Path) -> tuple[dict, str]:
    try:
        raw = (repo / CONTRACT_PATH).read_bytes()
        config = json.loads(raw)
    except (OSError, ValueError) as error:
        raise VerificationError(f"{CONTRACT_PATH}: {error}") from error
    commands = config.get("commands") if isinstance(config, dict) else None
    if not isinstance(commands, list) or not commands:
        raise VerificationError("commands must be a non-empty array of argv arrays")
    for argv in commands:
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
            or not argv[0].strip()
        ):
            raise VerificationError("each command must be a non-empty argv array")
    timeout = config.get("timeoutSeconds", 1800)
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise VerificationError("timeoutSeconds must be an integer from 1 to 86400")
    return {"commands": commands, "timeoutSeconds": timeout}, hashlib.sha256(raw).hexdigest()


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        raise VerificationError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def snapshot(repo: Path) -> dict:
    """Hash tracked/untracked inputs, including initialized submodules, not ignored outputs."""
    digest = hashlib.sha256()
    digest.update(git(repo, "diff", "--binary", "HEAD", "--"))
    # Include the index so changing the staged subject also invalidates evidence.
    digest.update(git(repo, "ls-files", "--stage", "-z"))
    paths = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    for relative in sorted(set(paths.split(b"\0")) - {b""}):
        path = repo / os.fsdecode(relative)
        try:
            if path.is_symlink():
                content = ["symlink", os.readlink(path)]
            elif path.is_file():
                content = ["file", path.stat().st_mode & 0o777, file_hash(path)]
            elif path.is_dir() and (path / ".git").exists():
                content = ["submodule", snapshot(path)]
            elif not path.exists():
                content = ["missing"]
            else:
                content = ["uninitialized-submodule"]
        except OSError as error:
            raise VerificationError(f"cannot fingerprint {relative!r}: {error}") from error
        digest.update(json.dumps([os.fsdecode(relative), content], sort_keys=True).encode())
    return {
        "subjectSha": git(repo, "rev-parse", "HEAD").decode().strip(),
        "inputHash": digest.hexdigest(),
    }


def run(repo: Path, directory: Path) -> dict:
    config, contract_hash = declaration(repo)
    before = snapshot(repo)
    directory.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=directory))
    checks = []
    for index, argv in enumerate(config["commands"]):
        log = output / f"{index + 1}.log"
        timed_out = False
        with log.open("wb") as stream:
            try:
                process = subprocess.Popen(
                    argv, cwd=repo, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                )
            except OSError as error:
                stream.write(str(error).encode())
                exit_code = 127
            else:
                try:
                    exit_code = process.wait(timeout=config["timeoutSeconds"])
                except subprocess.TimeoutExpired:
                    timed_out = True
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    exit_code = 124
                except BaseException:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise
        checks.append({
            "argv": argv, "exitCode": exit_code, "timedOut": timed_out,
            "log": str(log), "logHash": file_hash(log),
        })
    try:
        unchanged = before == snapshot(repo) and contract_hash == declaration(repo)[1]
    except VerificationError:
        unchanged = False
    passed = unchanged and all(check["exitCode"] == 0 for check in checks)
    receipt = output / "receipt.json"
    receipt.write_text(json.dumps({
        **before, "contractHash": contract_hash, "checks": checks,
        "inputsUnchanged": unchanged, "passed": passed,
    }, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "kind": "verification", "trust": "audit-only", "provider": "harness-kernel",
        "subjectSha": before["subjectSha"], "artifact": str(receipt),
        "digest": file_hash(receipt), "passed": passed,
    }


def require_current(evidence: list[dict], repo: Path) -> None:
    latest = next((entry for entry in reversed(evidence) if entry["kind"] == "verification"), None)
    if latest is None or latest.get("passed") is not True or latest.get("provider") != "harness-kernel":
        raise VerificationError("run the repository's mandatory verification first")
    try:
        config, contract_hash = declaration(repo)
        artifact = Path(latest["artifact"])
        if latest.get("digest") != file_hash(artifact):
            raise VerificationError("verification receipt was modified")
        receipt = json.loads(artifact.read_bytes())
        current = snapshot(repo)
        if (
            receipt.get("passed") is not True
            or receipt.get("inputsUnchanged") is not True
            or receipt.get("contractHash") != contract_hash
            or any(receipt.get(key) != value for key, value in current.items())
            or latest.get("subjectSha") != current["subjectSha"]
        ):
            raise VerificationError("verification is stale or unsuccessful; rerun mandatory checks")
        checks = receipt["checks"]
        if [check["argv"] for check in checks] != config["commands"]:
            raise VerificationError("verification did not execute every mandatory command")
        for check in checks:
            if check["exitCode"] != 0 or check["timedOut"] or file_hash(Path(check["log"])) != check["logHash"]:
                raise VerificationError("verification failed or its log was modified")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise VerificationError(f"verification evidence is unreadable: {error}") from error
