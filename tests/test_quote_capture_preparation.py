from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
import io
import json
from pathlib import PurePosixPath
import unittest
from unittest.mock import patch

from onejournal.provider_connectors.capture_preparation import CapturePreparationError, prepare_capture_runner
from onejournal.provider_connectors.quote_capture_preparation import QuoteCapturePreparation, prepare_quote_capture_runner
from test_mac_refresh_capture_preparation import SOURCE as GUARD_TEMPLATE, specification


SOURCE = b'''
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import json, sys, stat
RUN_UID = "synthetic-old-run"
APPROVAL_ID = "synthetic-old-approval"
OUTPUT_PARENT = Path("/synthetic/private/captures")
RUN_ROOT = OUTPUT_PARENT / RUN_UID
ACQUISITION_ROOT = RUN_ROOT / "acquisition"
RUNNER_PATH = RUN_ROOT / "old.py"
SCOPE_PATH = RUN_ROOT / "old.json"
PYTHON_EXECUTABLE = Path("/synthetic/runtime/bin/python3.12")
EXPECTED_SCOPE_SHA256 = "old-scope"
EXPECTED_PROVIDER_SYMBOL_SCOPE_SHA256 = "old-symbol-scope"
EXPECTED_AUTH_SHA256 = "old-auth"
EXPECTED_CONF_SHA256 = "old-conf"
EXPECTED_PYTHON_SHA256 = "old-runtime"
QUOTES_URL = "https://synthetic.invalid/quotes"
MARKET_HOURS_URL = "https://synthetic.invalid/markets"
class CaptureError(RuntimeError): pass
def _canonical(value): return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\\n").encode()
def _finite_json(body, field): return json.loads(body)
def _scope(body): return None
def _validated_response(**kwargs): pass
def _request(session, *, url, params):
    requested_at = datetime.now(UTC)
    session.get()
    return requested_at, datetime.now(UTC), 200, "application/json", b"{}"
def main():
    _scope_document, symbols = _scope(scope_body)
    source_contract = {"eligible_count": 48, "unavailable_count": 10, "maximum_provider_get_count": 2,
                       "quote_get_count": 1, "market_hours_get_count": 1,
                       "profile": "schwab-read-only-bounded-batch-quotes-and-market-hours.v1"}
    requests_plan = ()
    captured = []
    for suffix, operation, url, params, market_date, filename in requests_plan:
        requested_at, received_at, status_code, content_type, body = _request(None, params=params, url=url)
        _validated_response(operation=operation, body=body, status_code=status_code,
                            content_type=content_type, symbols=symbols, market_date=market_date)
        captured.append((operation, market_date.isoformat(), len(dict(params).get("symbols", "").split(","))))
    if len(captured) != 2: raise CaptureError("incomplete capture")
    manifest = {"controls": {"provider_get_count": 2, "response_count": 2}}
    print(json.dumps({"eligible_count": 48, "unavailable_count": 10, "provider_get_count": 2}))
    return source_contract, captured, manifest
if __name__ == "__main__":
    raise SystemExit(main())
'''


class QuoteCapturePreparationTests(unittest.TestCase):
    def setUp(self):
        self.guards = prepare_capture_runner(GUARD_TEMPLATE, replace(specification(),
            capture_python=PurePosixPath('/synthetic/private/runtime/python-env/bin/python3.12')))
        symbols = [f"SYNTHETIC{i:02d}" for i in range(64)]
        canonical = lambda value: (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.scope = {"schema": "onejournal.mac-refresh-quote-scope-proposal.v1",
            "acquisition_day_utc": "2026-10-11", "proposed_get_budget": 5,
            "provider_symbols": symbols, "schedule_markets": ["equity", "option"],
            "schedule_dates_proposed": ["2026-10-09", "2026-10-10", "2026-10-11"],
            "batches": [{"provider_symbols": batch, "symbols_query": ",".join(batch), "fields": "quote,reference",
                         "scope_sha256": sha256(canonical(batch).removesuffix(b"\n")).hexdigest()}
                        for batch in (symbols[:50], symbols[50:])]}
        self.body = canonical(self.scope)
        self.spec = QuoteCapturePreparation(date(2026,10,11), "synthetic-fresh-quotes", "synthetic-fresh-approval",
            PurePosixPath('/synthetic/private/captures/quotes'),
            PurePosixPath('/synthetic/private/runtime/python-env/bin/python3.12'),
            sha256(SOURCE).hexdigest(), sha256(self.guards).hexdigest(), sha256(self.body).hexdigest(),
            sha256(canonical(symbols)).hexdigest(), 'a'*64, 'b'*64, 'c'*64)
        self.prepared = prepare_quote_capture_runner(SOURCE, self.guards, self.spec)
        self.values = {"__name__": "synthetic_runner"}
        exec(compile(self.prepared, "synthetic_runner", "exec"), self.values)

    def test_exact_five_requests_and_provider_date_not_proposal(self):
        self.assertEqual(self.prepared, prepare_quote_capture_runner(SOURCE, self.guards, self.spec))
        self.values['scope_body'] = self.body
        for name in ('_REFRESH_require_capture_day', '_REFRESH_require_transport', '_REFRESH_require_isolated_runtime'):
            self.values[name] = lambda *args: None
        observed = []
        timestamp = int(datetime(2026,10,9,20,tzinfo=UTC).timestamp()*1000)
        def request(session, *, params, url):
            query = dict(params)
            observed.append((url, params))
            body = {s: {"symbol": s, "quote": {"quoteTime": timestamp}}
                    for s in query['symbols'].split(',')} if 'symbols' in query else {
                        'equity': {'date': query['date']}, 'option': {'date': query['date']}}
            instant = datetime(2026,10,11,3,tzinfo=UTC)
            return instant, instant, 200, 'application/json', json.dumps(body).encode()
        self.values['_request'] = request
        receipts = []
        self.values['_secure_write'] = lambda path, body: receipts.append(json.loads(body))
        with patch('sys.stdout', io.StringIO()):
            contract, captures, manifest = self.values['main']()
        self.assertEqual(len(observed), 5)
        self.assertEqual([row[2] for row in captures[:2]], [50,14])
        self.assertEqual([row[1] for row in captures[:2]], ['2026-10-09']*2)
        self.assertEqual([row[1] for row in captures[2:]], self.scope['schedule_dates_proposed'])
        self.assertEqual(contract['maximum_provider_get_count'], 5)
        self.assertNotIn('eligible_count', contract)
        self.assertEqual(manifest['controls']['response_count'], 5)
        self.assertEqual(len(receipts), 5)
        self.assertTrue(all(row['financial_validation']=='not_yet_validated' for row in receipts))

    def test_changed_source_scope_or_reused_identity_rejected(self):
        for spec in (replace(self.spec, reviewed_source_sha256='d'*64),
                     replace(self.spec, reviewed_guards_sha256='d'*64),
                     replace(self.spec, run_uid='synthetic-old-run'),
                     replace(self.spec, owner_run_root=PurePosixPath('/other/private/captures/quotes'))):
            with self.assertRaises(CapturePreparationError): prepare_quote_capture_runner(SOURCE, self.guards, spec)
        for key, value in (('proposed_get_budget', 6), ('provider_symbols', self.scope['provider_symbols'][:-1]),
                           ('schedule_dates_proposed', ['2026-10-08','2026-10-10','2026-10-11'])):
            with self.assertRaises(self.values['CaptureError']):
                self.values['_scope'](json.dumps({**self.scope, key: value}).encode())

    def test_missing_mixed_or_error_quote_stops_without_retry(self):
        validate = self.values['_validated_response']
        def call(body, status=200):
            return validate(operation='quote', body=json.dumps(body).encode(), status_code=status,
                            content_type='application/json', symbols=('A','B'), market_date=None)
        timestamp = int(datetime(2026,10,9,20,tzinfo=UTC).timestamp()*1000)
        body = {s: {'symbol':s,'quote':{'quoteTime':timestamp}} for s in ('A','B')}
        self.assertEqual(call(body), date(2026,10,9))
        with self.assertRaises(self.values['CaptureError']): call(body, 401)
        with self.assertRaises(self.values['CaptureError']): call({'A':body['A']})
        body['B']['quote']['quoteTime'] = 0
        body['B']['quote']['tradeTime'] = timestamp
        with self.assertRaises(self.values['CaptureError']): call(body)
        body['B']['quote']['quoteTime'] = timestamp
        body['B']['quote']['quoteTime'] += 86400000
        with self.assertRaises(self.values['CaptureError']): call(body)

    def test_failed_get_has_private_intent_and_cannot_be_repeated(self):
        self.values['_REFRESH_require_capture_day'] = lambda *args: None
        recorded = set()
        def write(path, body):
            if path in recorded: raise FileExistsError('synthetic duplicate intent')
            recorded.add(path)
        self.values['_secure_write'] = write
        class FailedSession:
            calls = 0
            def get(self):
                self.calls += 1
                raise RuntimeError('synthetic transport failure')
        session = FailedSession()
        with self.assertRaises(RuntimeError):
            self.values['_request'](session, url='https://synthetic.invalid/quotes', params=(('symbols','A'),))
        self.assertEqual(len(recorded), 1)
        with self.assertRaises(FileExistsError):
            self.values['_request'](session, url='https://synthetic.invalid/quotes', params=(('symbols','A'),))
        self.assertEqual(session.calls, 1)


if __name__ == '__main__': unittest.main()
