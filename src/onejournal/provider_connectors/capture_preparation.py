"""Prepare reviewed, single-use owner-side runners without executing them.

This module has no provider, credential, network, filesystem-write or database
capability. It preserves reviewed runner behavior and private binding constants,
rebinding only an explicitly proposed run, window and source/runtime checksums.
It adds capture-date, HTTP-dependency and private-error guards. Prepared bytes
are not broker-access authorization.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import PurePosixPath
import re
from typing import Literal


class CapturePreparationError(ValueError):
    """A reviewed runner cannot safely be prepared for the proposed scope."""


@dataclass(frozen=True)
class CapturePreparation:
    kind: Literal["position", "history"]
    asof: date
    run_uid: str
    proposed_approval_id: str
    owner_run_root: PurePosixPath
    reviewed_source_sha256: str
    auth_sha256: str
    conf_sha256: str
    runtime_sha256: str
    window_start: date | None = None
    window_end: date | None = None


def _path_expression(path: PurePosixPath) -> ast.expr:
    return ast.Call(func=ast.Name(id="Path", ctx=ast.Load()), args=[ast.Constant(str(path))], keywords=[])


def prepare_capture_runner(source: bytes, spec: CapturePreparation) -> bytes:
    """Return one fixed runner; never import or execute the retained source."""
    digest = re.compile(r"[0-9a-f]{64}")
    for value in (spec.reviewed_source_sha256, spec.auth_sha256, spec.conf_sha256, spec.runtime_sha256):
        if not isinstance(value, str) or not digest.fullmatch(value):
            raise CapturePreparationError("exact source/runtime SHA-256 pins are required")
    if sha256(source).hexdigest() != spec.reviewed_source_sha256:
        raise CapturePreparationError("reviewed runner checksum mismatch")
    if not isinstance(spec.asof, date) or spec.kind not in {"position", "history"}:
        raise CapturePreparationError("explicit capture kind and as-of date are required")
    for value in (spec.run_uid, spec.proposed_approval_id):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", value):
            raise CapturePreparationError("a safe fresh run/approval identity is required")
    root = spec.owner_run_root
    if not root.is_absolute() or len(root.parts) < 4 or ".." in root.parts:
        raise CapturePreparationError("a named absolute owner run directory is required")
    if spec.kind == "history":
        if (spec.window_start is None or spec.window_end is None
            or not 1 <= (spec.window_end - spec.window_start).days + 1 <= 30
            or spec.window_end > spec.asof):
            raise CapturePreparationError("history needs an explicit 1–30 day window ending no later than as-of")
    elif spec.window_start is not None or spec.window_end is not None:
        raise CapturePreparationError("position preparation must not contain a history window")

    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeError, SyntaxError) as exc:
        raise CapturePreparationError("reviewed source is not valid Python") from exc
    assignments: dict[str, ast.Assign] = {}
    functions: dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in assignments:
                raise CapturePreparationError("runner has duplicate constants")
            assignments[name] = node
        elif isinstance(node, ast.FunctionDef):
            if node.name in functions:
                raise CapturePreparationError("runner has duplicate functions")
            functions[node.name] = node
    required = {"RUN_UID", "APPROVAL_ID", "OUTPUT_PARENT", "RUN_ROOT", "ACQUISITION_ROOT", "RUNNER_PATH",
                "EXPECTED_AUTH_SHA256", "EXPECTED_CONF_SHA256", "EXPECTED_PYTHON_SHA256"}
    if spec.kind == "history":
        required |= {"WINDOW_START", "WINDOW_END", "START_TIMESTAMP", "END_TIMESTAMP"}
    if not required <= assignments.keys() or not {"main", "_fetch"} <= functions.keys():
        raise CapturePreparationError("runner structure differs from the reviewed template")
    if any(name.startswith("_REFRESH_") for name in (*assignments, *functions)):
        raise CapturePreparationError("prepare from the retained source, not a previously prepared runner")
    for name, replacement in (("RUN_UID", spec.run_uid), ("APPROVAL_ID", spec.proposed_approval_id)):
        if ast.literal_eval(assignments[name].value) == replacement:
            raise CapturePreparationError("historical run/approval identities cannot be reused")

    # The owner-side output parent stays the reviewed private boundary.
    parent_value = assignments["OUTPUT_PARENT"].value
    if (not isinstance(parent_value, ast.Call) or not isinstance(parent_value.func, ast.Name)
        or parent_value.func.id != "Path" or len(parent_value.args) != 1
        or ast.literal_eval(parent_value.args[0]) != str(root.parent)):
        raise CapturePreparationError("new run must stay inside the reviewed owner output parent")
    filename = f"onejournal_mac_refresh_{spec.kind}.py"
    replacements: dict[str, ast.expr] = {
        "RUN_UID": ast.Constant(spec.run_uid), "APPROVAL_ID": ast.Constant(spec.proposed_approval_id),
        "RUN_ROOT": _path_expression(root), "ACQUISITION_ROOT": _path_expression(root / "acquisition"),
        "RUNNER_PATH": _path_expression(root / filename),
        "EXPECTED_AUTH_SHA256": ast.Constant(spec.auth_sha256),
        "EXPECTED_CONF_SHA256": ast.Constant(spec.conf_sha256),
        "EXPECTED_PYTHON_SHA256": ast.Constant(spec.runtime_sha256),
    }
    if spec.kind == "history":
        assert spec.window_start is not None and spec.window_end is not None
        replacements.update({
            "WINDOW_START": ast.Constant(spec.window_start.isoformat()),
            "WINDOW_END": ast.Constant(spec.window_end.isoformat()),
            "START_TIMESTAMP": ast.Constant(f"{spec.window_start.isoformat()}T00:00:00.000Z"),
            "END_TIMESTAMP": ast.Constant(f"{spec.window_end.isoformat()}T23:59:59.999Z"),
        })
    for name, expression in replacements.items():
        assignments[name].value = expression

    if spec.kind == "position":
        corrected = 0
        for node in ast.walk(functions["main"]):
            if isinstance(node, ast.Dict):
                for index, key in enumerate(node.keys):
                    if isinstance(key, ast.Constant) and key.value == "owner_refresh_before_capture_count":
                        if not isinstance(node.values[index], ast.Constant) or node.values[index].value != 1:
                            raise CapturePreparationError("historical refresh declaration differs from review")
                        node.values[index] = ast.Constant(0)
                        corrected += 1
        if corrected != 1:
            raise CapturePreparationError("historical position refresh declaration is missing or duplicated")

    guard = ast.parse(rf'''
_REFRESH_ASOF = {spec.asof.isoformat()!r}
def _REFRESH_require_capture_day(instant):
    from zoneinfo import ZoneInfo
    if (instant.tzinfo is None or instant.astimezone(UTC).date().isoformat() != _REFRESH_ASOF
        or instant.astimezone(ZoneInfo("America/New_York")).date().isoformat() != _REFRESH_ASOF):
        raise CaptureError("Capture date no longer matches the fixed UTC/New York scope; stop and reprepare.")
def _REFRESH_require_transport():
    from importlib.metadata import PackageNotFoundError, version
    import re
    for package, minimum in (("requests", (2, 33, 0)), ("urllib3", (2, 8, 0))):
        try:
            installed = version(package)
        except PackageNotFoundError:
            raise CaptureError("Capture HTTP dependencies need an approved current runtime; stop before credentials or GETs.") from None
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", installed)
        if match is None or tuple(map(int, match.groups())) < minimum:
            raise CaptureError("Capture HTTP dependencies need an approved current runtime; stop before credentials or GETs.")
''').body
    main_index = tree.body.index(functions["main"])
    tree.body[main_index:main_index] = guard
    functions["main"].body[0:0] = ast.parse("_REFRESH_require_capture_day(datetime.now(UTC))\n_REFRESH_require_transport()").body
    # Check immediately before each GET and after its response. Crossing a date
    # boundary leaves incomplete evidence; it cannot produce a complete manifest.
    fetch = functions["_fetch"]
    found = {"requested_at": 0, "received_at": 0}

    class GuardRequests(ast.NodeTransformer):
        def visit_Assign(self, node: ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in found:
                    found[name] += 1
                    return [node, ast.parse(f"_REFRESH_require_capture_day({name})").body[0]]
            return node

    GuardRequests().visit(fetch)
    if found != {"requested_at": 1, "received_at": 1}:
        raise CapturePreparationError("request timestamps differ from the reviewed runner")
    entries = [node for node in tree.body if isinstance(node, ast.If)
               and ast.dump(node.test) == ast.dump(ast.parse('if __name__ == "__main__": pass').body[0].test)]
    expected_entry = ast.parse('raise SystemExit(main())').body[0]
    if len(entries) != 1 or len(entries[0].body) != 1 or ast.dump(entries[0].body[0]) != ast.dump(expected_entry):
        raise CapturePreparationError("runner entry point differs from the reviewed source")
    # Network exceptions can embed the private account hash in their URL.
    # Never let an unhandled traceback publish those details to operator logs.
    entries[0].body = ast.parse('''
try:
    raise SystemExit(main())
except CaptureError as error:
    print("Capture stopped: " + str(error), file=sys.stderr)
    raise SystemExit(1) from None
except Exception:
    print("Capture stopped: owner-side failure; no automatic retry or complete manifest.", file=sys.stderr)
    raise SystemExit(1) from None
''').body
    ast.fix_missing_locations(tree)
    prepared = ("# Prepared offline; fresh owner execution approval is required.\n" + ast.unparse(tree) + "\n").encode()
    compile(prepared, "prepared-owner-capture", "exec")  # Compilation only, never execution.
    return prepared
