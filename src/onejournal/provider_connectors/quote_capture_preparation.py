"""Offline preparation of the reviewed two-batch quote capture, never execution.

The retained private runner owns credentials and raw output on OneBot. This
compiler only changes explicit scope, identity and checksum pins; it cannot
import that runner, access credentials, fetch data or write files.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import PurePosixPath
import re

from .capture_preparation import CapturePreparationError, _path_expression


@dataclass(frozen=True)
class QuoteCapturePreparation:
    asof: date
    run_uid: str
    approval_id: str
    owner_run_root: PurePosixPath
    capture_python: PurePosixPath
    reviewed_source_sha256: str
    reviewed_guards_sha256: str
    scope_sha256: str
    symbol_scope_sha256: str
    auth_sha256: str
    conf_sha256: str
    runtime_sha256: str
    allowed_unavailable_symbol_sha256s: tuple[str, ...] = ()


def prepare_quote_capture_runner(source: bytes, guards_source: bytes,
                                 spec: QuoteCapturePreparation) -> bytes:
    """Compile a fixed 50+14 quote / three schedule request plan, without running it."""
    for field in (spec.reviewed_source_sha256, spec.reviewed_guards_sha256,
                  spec.scope_sha256, spec.symbol_scope_sha256, spec.auth_sha256,
                  spec.conf_sha256, spec.runtime_sha256):
        if not isinstance(field, str) or not re.fullmatch(r"[0-9a-f]{64}", field):
            raise CapturePreparationError("exact reviewed SHA-256 pins are required")
    if (sha256(source).hexdigest() != spec.reviewed_source_sha256
        or sha256(guards_source).hexdigest() != spec.reviewed_guards_sha256):
        raise CapturePreparationError("reviewed quote runner or capture guards changed")
    if (len(spec.allowed_unavailable_symbol_sha256s) > 4
        or len(set(spec.allowed_unavailable_symbol_sha256s)) != len(spec.allowed_unavailable_symbol_sha256s)
        or any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in spec.allowed_unavailable_symbol_sha256s)):
        raise CapturePreparationError("at most four exact unavailable instrument digests may be approved")
    for value in (spec.run_uid, spec.approval_id):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", value):
            raise CapturePreparationError("fresh safe run and approval identities are required")
    root, python = spec.owner_run_root, spec.capture_python
    if (not isinstance(spec.asof, date) or not root.is_absolute() or ".." in root.parts
        or len(root.parts) < 5 or not python.is_absolute() or ".." in python.parts
        or len(python.parts) < 6 or python.parts[-2:] != ("bin", "python3.12")
        or root in python.parents):
        raise CapturePreparationError("named separate private run and isolated runtime are required")
    try:
        tree, guards = ast.parse(source.decode()), ast.parse(guards_source.decode())
    except (UnicodeError, SyntaxError) as exc:
        raise CapturePreparationError("reviewed sources are not valid Python") from exc
    constants = {n.targets[0].id: n for n in tree.body if isinstance(n, ast.Assign)
                 and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    required = {"OUTPUT_PARENT", "RUN_UID", "APPROVAL_ID", "RUN_ROOT", "ACQUISITION_ROOT",
                "RUNNER_PATH", "SCOPE_PATH", "PYTHON_EXECUTABLE", "EXPECTED_SCOPE_SHA256",
                "EXPECTED_PROVIDER_SYMBOL_SCOPE_SHA256", "EXPECTED_AUTH_SHA256",
                "EXPECTED_CONF_SHA256", "EXPECTED_PYTHON_SHA256"}
    if not required <= constants.keys() or not {"main", "_scope", "_request", "_validated_response"} <= functions.keys():
        raise CapturePreparationError("reviewed quote runner structure changed")
    parent = constants["OUTPUT_PARENT"].value
    if (not isinstance(parent, ast.Call) or not isinstance(parent.func, ast.Name)
        or parent.func.id != "Path" or len(parent.args) != 1
        or ast.literal_eval(parent.args[0]) != str(root.parent)):
        raise CapturePreparationError("run must remain within the reviewed private owner boundary")
    for name, value in (("RUN_UID", spec.run_uid), ("APPROVAL_ID", spec.approval_id)):
        if ast.literal_eval(constants[name].value) == value:
            raise CapturePreparationError("historical run or approval cannot be reused")
    replacements = {
        "RUN_UID": ast.Constant(spec.run_uid), "APPROVAL_ID": ast.Constant(spec.approval_id),
        "RUN_ROOT": _path_expression(root), "ACQUISITION_ROOT": _path_expression(root / "acquisition"),
        "RUNNER_PATH": _path_expression(root / "onejournal_mac_refresh_quotes.py"),
        "SCOPE_PATH": _path_expression(root / "scope-proposal.json"),
        "PYTHON_EXECUTABLE": _path_expression(python),
        "EXPECTED_SCOPE_SHA256": ast.Constant(spec.scope_sha256),
        "EXPECTED_PROVIDER_SYMBOL_SCOPE_SHA256": ast.Constant(spec.symbol_scope_sha256),
        "EXPECTED_AUTH_SHA256": ast.Constant(spec.auth_sha256),
        "EXPECTED_CONF_SHA256": ast.Constant(spec.conf_sha256),
        "EXPECTED_PYTHON_SHA256": ast.Constant(spec.runtime_sha256),
    }
    for name, value in replacements.items():
        constants[name].value = value
    # Historical date constants are no longer authoritative: quote dates come
    # from provider timestamps, and schedule dates from the pinned proposal.
    for name in ("QUOTE_MARKET_DATE", "EVALUATION_MARKET_DATE"):
        if name in constants:
            tree.body.remove(constants[name])
    guard_names = {"_REFRESH_require_capture_day", "_REFRESH_require_transport", "_REFRESH_require_isolated_runtime"}
    guard_nodes = [n for n in guards.body if isinstance(n, ast.FunctionDef) and n.name in guard_names]
    if len(guard_nodes) != 3:
        raise CapturePreparationError("reviewed runtime guards are incomplete")
    tree.body[tree.body.index(functions["main"]):tree.body.index(functions["main"])] = [
        *ast.parse(f"_REFRESH_ASOF = {spec.asof.isoformat()!r}\n_REFRESH_ALLOWED_UNAVAILABLE = {spec.allowed_unavailable_symbol_sha256s!r}").body,
        *guard_nodes]
    scope = ast.parse(r'''
def _scope(body):
    document = _finite_json(body, "quote scope")
    if not isinstance(document, dict):
        raise CaptureError("quote scope must be an object")
    symbols = document.get("provider_symbols")
    batches = document.get("batches")
    dates = document.get("schedule_dates_proposed")
    if (document.get("schema") != "onejournal.mac-refresh-quote-scope-proposal.v1"
        or document.get("acquisition_day_utc") != _REFRESH_ASOF
        or document.get("proposed_get_budget") != 5
        or not isinstance(symbols, list) or len(symbols) != 64
        or any(not isinstance(s, str) or s != s.strip().upper() or not s or "," in s or len(s) > 64 for s in symbols)
        or symbols != sorted(set(symbols))
        or sha256(_canonical(symbols)).hexdigest() != EXPECTED_PROVIDER_SYMBOL_SCOPE_SHA256
        or not isinstance(batches, list) or len(batches) != 2
        or [b.get("provider_symbols") for b in batches] != [symbols[:50], symbols[50:]]
        or any(b.get("fields") != "quote,reference" or b.get("symbols_query") != ",".join(b["provider_symbols"])
               or b.get("scope_sha256") != sha256(_canonical(b["provider_symbols"]).removesuffix(b"\n")).hexdigest() for b in batches)
        or not isinstance(dates, list) or len(dates) != 3
        or dates != sorted(set(dates))
        or dates[-1] != _REFRESH_ASOF
        or (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days != 2
        or document.get("schedule_markets") != ["equity", "option"]):
        raise CaptureError("quote scope failed the approved 64-instrument / five-GET boundary")
    return document, tuple(symbols)
''').body[0]
    validation = ast.parse('''
def _validated_response(*, operation, body, status_code, content_type, symbols, market_date):
    if status_code != 200 or content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise CaptureError("provider response failed its status or JSON contract")
    payload = _finite_json(body, "provider response")
    if operation == "quote":
        if not isinstance(payload, dict) or set(payload) != set(symbols):
            raise CaptureError("quote response does not exactly match its approved batch")
        dates = set()
        for symbol in symbols:
            item = payload[symbol]
            quote = item.get("quote") if isinstance(item, dict) else None
            timestamp = quote.get("quoteTime") if isinstance(quote, dict) else None
            if (isinstance(item, dict) and item.get("symbol") == symbol and isinstance(quote, dict)
                and (timestamp is None or (not isinstance(timestamp, bool) and timestamp == 0))
                and sha256(symbol.encode()).hexdigest() in _REFRESH_ALLOWED_UNAVAILABLE):
                continue
            if (not isinstance(item, dict) or item.get("symbol") != symbol
                or isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0):
                raise CaptureError("quote identity or provider timestamp is invalid")
            dates.add(datetime.fromtimestamp(timestamp / 1000, UTC).astimezone(ZoneInfo("America/New_York")).date())
        if len(dates) != 1:
            raise CaptureError("quote batch has mixed provider dates; preserve evidence and review without retry")
        return dates.pop()
    if not isinstance(payload, dict) or set(payload) != {"equity", "option"} or market_date.isoformat() not in json.dumps(payload, sort_keys=True):
        raise CaptureError("market-hours response does not match its requested scope")
    return market_date
''').body[0]
    for name, node in (("_scope", scope), ("_validated_response", validation)):
        tree.body[tree.body.index(functions[name])] = node
    main = functions["main"]
    main.body[:0] = ast.parse("_REFRESH_require_capture_day(datetime.now(UTC))\n_REFRESH_require_isolated_runtime()\n_REFRESH_require_transport()").body
    profile = "schwab-read-only-bounded-batch-quotes-and-market-hours.v2"
    counts = {"maximum_provider_get_count": 5, "provider_get_count": 5, "response_count": 5,
              "quote_get_count": 2, "market_hours_get_count": 3, "instrument_count": 64}
    dicts_changed = 0
    for node in ast.walk(main):
        if isinstance(node, ast.Dict):
            keys = [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
            if "eligible_count" in keys or "provider_get_count" in keys:
                dicts_changed += 1
                for i in reversed(range(len(keys))):
                    if keys[i] in {"unavailable_count", "quote_market_date", "evaluation_market_date"}:
                        del node.keys[i], node.values[i]
                    elif keys[i] == "eligible_count":
                        node.keys[i], node.values[i] = ast.Constant("instrument_count"), ast.Constant(64)
                    elif keys[i] in counts:
                        node.values[i] = ast.Constant(counts[keys[i]])
        elif isinstance(node, ast.Constant) and node.value == "schwab-read-only-bounded-batch-quotes-and-market-hours.v1":
            node.value = profile
        elif isinstance(node, ast.Constant) and node.value == "eligible_scope_sha256":
            node.value = "quote_scope_sha256"
        elif isinstance(node, ast.Constant) and node.value in {
            "onejournal.pnl03v.bounded-batch-mark-source-contract.v1",
            "onejournal.pnl03v.bounded-batch-mark-capture-result.v1"}:
            node.value = str(node.value).removesuffix("v1") + "v2"
    if dicts_changed != 3:
        raise CapturePreparationError("reviewed capture contract/count declarations changed")
    contract_assignments = [n for n in ast.walk(main) if isinstance(n, ast.Assign)
                            and any(isinstance(t, ast.Name) and t.id == "source_contract" for t in n.targets)]
    if len(contract_assignments) != 1 or not isinstance(contract_assignments[0].value, ast.Dict):
        raise CapturePreparationError("reviewed source contract changed")
    contract_assignments[0].value.keys.append(ast.Constant("allowed_unavailable_symbol_sha256s"))
    contract_assignments[0].value.values.append(ast.Name(id="_REFRESH_ALLOWED_UNAVAILABLE", ctx=ast.Load()))
    plan = ast.parse('''
requests_plan = tuple(
    (f"quote_batch_{i + 1}", "quote", QUOTES_URL,
     (("symbols", batch["symbols_query"]), ("fields", "quote,reference")), None, f"quotes-batch-{i + 1}.json")
    for i, batch in enumerate(_scope_document["batches"])) + tuple(
    (f"market_hours_{d}", "market_hours", MARKET_HOURS_URL,
     (("markets", "equity"), ("markets", "option"), ("date", d)), date.fromisoformat(d), f"market-hours-{d}.json")
    for d in _scope_document["schedule_dates_proposed"])
''').body[0]
    replaced_plan = replaced_validation = replaced_count = 0
    for node in ast.walk(main):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "requests_plan":
            node.value = plan.value
            replaced_plan += 1
        if isinstance(node, ast.Compare) and ast.dump(node.left) == ast.dump(ast.parse("len(captured)", mode="eval").body):
            node.comparators = [ast.Constant(5)]
            replaced_count += 1
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "_validated_response":
            for keyword in node.value.keywords:
                if keyword.arg == "symbols":
                    keyword.value = ast.parse('tuple(dict(params)["symbols"].split(",")) if operation == "quote" else ()', mode="eval").body
            node.__class__ = ast.Assign
            node.targets = [ast.Name(id="market_date", ctx=ast.Store())]
            node.type_comment = None
            replaced_validation += 1
    if (replaced_plan, replaced_validation, replaced_count) != (1, 1, 1):
        raise CapturePreparationError("reviewed request plan changed")
    request = functions["_request"]
    for i, node in enumerate(request.body):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "requested_at" for t in node.targets):
            request.body[i + 1:i + 1] = ast.parse('''
_REFRESH_require_capture_day(requested_at)
# A durable intent prevents repeating a GET even if transport fails before
# a response exists. It is private run evidence, not an acquisition manifest.
_secure_write(RUN_ROOT / ("request-started-" + sha256(_canonical([url, list(params)])).hexdigest() + ".json"),
              _canonical({"method": "GET", "url": url, "query": list(params),
                          "requested_at_utc": requested_at.isoformat(), "attempt_count": 1}))
''').body
            break
    returns = [n for n in ast.walk(request) if isinstance(n, ast.Return)]
    if len(returns) != 1 or not isinstance(returns[0].value, ast.Tuple):
        raise CapturePreparationError("reviewed response timestamp structure changed")
    returns[0].value.elts[1] = ast.parse("_checked_receipt_time()", mode="eval").body
    tree.body.insert(tree.body.index(main), ast.parse('''
def _checked_receipt_time():
    instant = datetime.now(UTC)
    _REFRESH_require_capture_day(instant)
    return instant
''').body[0])
    # Retain timing/hash provenance before semantic validation can reject a
    # response. Never reconstruct a missing receipt from filesystem times.
    class PreserveReceipt(ast.NodeTransformer):
        def visit_For(self, node):
            if isinstance(node.target, ast.Tuple) and any(isinstance(n, ast.Name) and n.id == "suffix" for n in node.target.elts):
                for index, statement in enumerate(node.body):
                    if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "market_date" for t in statement.targets):
                        node.body[index:index] = ast.parse('''
_secure_write(RUN_ROOT / ("response-receipt-" + suffix + ".json"), _canonical({
    "request_uid": RUN_UID + ":" + suffix, "operation": operation, "method": "GET", "url": url,
    "query": [{"name": name, "value": value} for name, value in params],
    "requested_at_utc": requested_at.isoformat(), "received_at_utc": received_at.isoformat(),
    "status_code": status_code, "content_type": content_type, "response_filename": filename,
    "response_byte_count": len(body), "response_sha256": sha256(body).hexdigest(),
    "attempt_count": 1, "financial_validation": "not_yet_validated"}))
''').body
                        break
            return node
    PreserveReceipt().visit(main)
    entries = [n for n in tree.body if isinstance(n, ast.If)
               and ast.dump(n.test) == ast.dump(ast.parse('if __name__ == "__main__": pass').body[0].test)]
    if len(entries) != 1:
        raise CapturePreparationError("reviewed entry point changed")
    entries[0].body = ast.parse('''
try:
    raise SystemExit(main())
except CaptureError as error:
    print("Capture stopped: " + str(error), file=sys.stderr)
    raise SystemExit(1) from None
except Exception:
    print("Capture stopped: owner-side failure; preserve partial evidence, no retry.", file=sys.stderr)
    raise SystemExit(1) from None
''').body
    ast.fix_missing_locations(tree)
    result = ("# Prepared offline for an explicitly approved five-GET scope.\n" + ast.unparse(tree) + "\n").encode()
    compile(result, "prepared-quote-capture", "exec")
    return result
