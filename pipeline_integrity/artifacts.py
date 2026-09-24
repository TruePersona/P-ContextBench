"""Immutable attempt records with checked, replaceable output pointers."""

import hashlib
import inspect
import json
import sys
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from importlib import metadata
from pathlib import Path
from uuid import uuid4

CURRENT = ContextVar("pipeline_attempt", default=None)
CALL = ContextVar("pipeline_call", default=None)
SCHEMA = "pipeline-artifacts-v1"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
        return
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    temporary.replace(path)


def publish(path, value):
    """Retain every revision before replacing the convenient output pointer."""
    attempt = CURRENT.get()
    if attempt:
        number = len(list((attempt / "artifacts").glob("*.json"))) + 1
        write_json(attempt / "artifacts" / f"{number:04d}-{Path(path).name}", value, exclusive=True)
    write_json(path, value)


def provenance(path, *, allow_legacy=False, allow_rejected=False):
    path = Path(path)
    pointer = path.with_name(path.name + ".provenance.json")
    if not pointer.exists():
        if allow_legacy:
            return {"status": "historical_unbound", "artifact_sha256": file_digest(path)}
        raise ValueError(
            f"{path}: no bound provenance; explicitly import historical inputs with --allow-legacy-inputs"
        )
    ref = read_json(pointer)
    manifest_path = (pointer.parent / ref["manifest"]).resolve()
    manifest = read_json(manifest_path)
    if (
        ref.get("manifest_sha256") != digest(manifest)
        or manifest.get("schema") != SCHEMA
        or manifest.get("status")
        not in (("accepted", "rejected") if allow_rejected else ("accepted",))
        or manifest.get("outputs", {}).get(path.name) != file_digest(path)
    ):
        raise ValueError(f"{path}: stale or invalid artifact provenance")
    for name, expected in manifest["inputs"].items():
        if file_digest(manifest_path.parent / "inputs" / name) != expected["sha256"]:
            raise ValueError(f"{path}: changed source snapshot {name}")
        if expected.get("parent_manifest_sha256") != digest(
            read_json(manifest_path.parent / "parents" / (name + ".json"))
        ):
            raise ValueError(f"{path}: changed parent manifest {name}")
    for name, expected in manifest["outputs"].items():
        if file_digest(manifest_path.parent / "outputs" / name) != expected:
            raise ValueError(f"{path}: changed accepted output snapshot {name}")
    for name, expected in manifest.get("calls", {}).items():
        if file_digest(manifest_path.parent / "calls" / name) != expected:
            raise ValueError(f"{path}: changed raw inference record {name}")
    for name, expected in manifest.get("implementation_sha256", {}).items():
        if file_digest(manifest_path.parent / "code" / name) != expected:
            raise ValueError(f"{path}: changed implementation snapshot {name}")
    return manifest


def require_same_attempt(first, second, *, allow_legacy=False):
    a = provenance(first, allow_legacy=allow_legacy)
    b = provenance(second, allow_legacy=allow_legacy)
    if a.get("attempt_id") != b.get("attempt_id"):
        raise ValueError("Related artifacts were not produced by the same accepted attempt")


def distinct_models(first, second):
    if not first or not second or first.strip().lower() == second.strip().lower():
        raise ValueError(
            "Generation/answering and independent verification/judging require different model IDs"
        )


@contextmanager
def output_lock(directory, key):
    """OS locks release after interruption; stale lock files do not block resume."""
    import os

    path = Path(directory) / ".locks" / (key + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.write(b"0")
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def tracked(stage, *, inputs, outputs, base_arg, base_suffix):
    """Record execution without changing the stage's public call signature."""

    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            params = bound.arguments
            out = Path(params["output_dir"])
            attempt_id = uuid4().hex
            attempt = out / ".attempts" / stage / attempt_id
            attempt.mkdir(parents=True)
            manifest = {
                "schema": SCHEMA,
                "stage": stage,
                "attempt_id": attempt_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "configuration": {
                    k: str(v) if isinstance(v, Path) else v
                    for k, v in params.items()
                    if k not in inputs
                },
                "inputs": {},
                "outputs": {},
                "status": "running",
            }
            source = Path(inspect.getsourcefile(function))
            root = Path(__file__).resolve().parents[1]
            code = [
                source,
                root / "llm.py",
                root / "utils.py",
                root / "run.py",
                root / "requirements.txt",
                root / "requirements-dev.txt",
                root / "pyproject.toml",
                *Path(__file__).parent.glob("*.py"),
            ]
            for folder in root.glob("step[1-6]_*"):
                code.extend(folder.glob("*.py"))
                code.extend(folder.glob("*.txt"))
            code = sorted(set(code))
            manifest["runtime"] = {"python": sys.version, "packages": {}}
            for package in ("anthropic", "openai", "datasets"):
                try:
                    manifest["runtime"]["packages"][package] = metadata.version(package)
                except metadata.PackageNotFoundError:
                    manifest["runtime"]["packages"][package] = None
            manifest["implementation_sha256"] = {
                str(p.relative_to(root)): file_digest(p) for p in code
            }
            for path in code:
                snapshot = attempt / "code" / path.relative_to(root)
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(path.read_bytes())
            if stage == "step4":
                manifest["configuration"]["gate_policy"] = function.__globals__.get("GATE_POLICY")
            token = CURRENT.set(attempt)
            started = time.monotonic()
            try:
                for name in inputs:
                    path = params.get(name)
                    if path is None:
                        continue
                    path = Path(path)
                    data = path.read_bytes()
                    snapshot = attempt / "inputs" / name
                    snapshot.parent.mkdir(exist_ok=True)
                    snapshot.write_bytes(data)
                    manifest["inputs"][name] = {
                        "path": str(path.resolve()),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                    parent = provenance(path, allow_legacy=True)
                    manifest["inputs"][name]["provenance_status"] = parent["status"]
                    manifest["inputs"][name]["parent_manifest_sha256"] = digest(parent)
                    write_json(attempt / "parents" / (name + ".json"), parent, exclusive=True)
                result = function(*args, **kwargs)
                accepted = result == 0 if isinstance(result, int) else isinstance(result, Path)
                manifest["status"] = "accepted" if accepted else "rejected"
                if accepted or stage == "step4":
                    base = Path(params[base_arg]).stem.removesuffix(base_suffix)
                    names = (
                        [base + suffix for suffix in outputs]
                        if outputs is not None
                        else [result.name]
                    )
                    if stage == "step6":
                        suffix = (
                            f"_run{params['run_index']:02d}"
                            if params.get("run_index") is not None
                            else ""
                        )
                        answer_name = base + suffix + "_pass1_answers.json"
                        if answer_name not in names:
                            names.append(answer_name)
                    if stage == "step4" and params.get("decoy_count", 0):
                        names[0] = base + f"_decoy{params['decoy_count']}_app_logs.json"
                    for name in names:
                        path = out / name
                        if not accepted and not path.exists():
                            continue
                        data = path.read_bytes()
                        target = attempt / "outputs" / name
                        target.parent.mkdir(exist_ok=True)
                        target.write_bytes(data)
                        manifest["outputs"][name] = hashlib.sha256(data).hexdigest()
                return result
            except BaseException as exc:
                manifest["status"] = "error"
                manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
                raise
            finally:
                manifest["elapsed_seconds"] = time.monotonic() - started
                manifest["calls"] = {
                    p.name: file_digest(p) for p in sorted((attempt / "calls").glob("*.json"))
                }
                write_json(attempt / "manifest.json", manifest, exclusive=True)
                if manifest["status"] == "accepted" or (
                    stage == "step4" and manifest["status"] == "rejected"
                ):
                    for name in manifest["outputs"]:
                        write_json(
                            out / (name + ".provenance.json"),
                            {
                                "manifest": str((attempt / "manifest.json").relative_to(out)),
                                "manifest_sha256": digest(manifest),
                            },
                        )
                CURRENT.reset(token)

        @wraps(function)
        def serialized(*args, **kwargs):
            params = signature.bind(*args, **kwargs).arguments
            key = stage + "-" + Path(params[base_arg]).stem
            with output_lock(params["output_dir"], key):
                return wrapped(*args, **kwargs)

        return serialized

    return decorate


def record_call(function, configuration, prompt):
    """Preserve exact model input/output; unavailable usage is explicitly null."""
    attempt = CURRENT.get()
    if attempt is None:
        return function()
    call = {
        "call_id": uuid4().hex,
        "configuration": configuration,
        "prompt": prompt,
        "prompt_sha256": digest(prompt),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "usage": None,
    }
    started = time.monotonic()
    token = CALL.set(call)
    try:
        raw = function()
        call.update(status="returned", raw_response=raw)
        from utils import extract_json

        try:
            parsed = extract_json(raw)
            digest(parsed)
            call["parsed_response"] = parsed
            call["parse_status"] = "valid_json"
        except (ValueError, TypeError) as exc:
            call["parse_status"] = "invalid_json"
            call["parse_error"] = str(exc)
        return raw
    except BaseException as exc:
        call.update(status="error", error={"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        call["elapsed_seconds"] = time.monotonic() - started
        write_json(attempt / "calls" / (call["call_id"] + ".json"), call, exclusive=True)
        CALL.reset(token)


def transport_note(**values):
    call = CALL.get()
    if call is not None:
        call.setdefault("transport_attempts", []).append(values)
        if values.get("usage") is not None:
            call["usage"] = values["usage"]
