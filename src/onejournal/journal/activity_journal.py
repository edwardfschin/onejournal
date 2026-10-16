"""Saved Journal read model carried atomically by an incremental import.

The existing immutable JSON ledger holds the typed rows alongside its evidence
and checkpoint. Readers select the newest account import only while its base
history activation still matches. No report or portfolio release is changed.
"""
from collections import Counter
from dataclasses import asdict
from datetime import UTC
from hashlib import sha256
import json

from onejournal.journal.schwab_evidence_assembly import canonical_schwab_evidence_json


CONTRACT = 'onejournal.activity-journal.v1'
RELATIONS = (
    'trade_episodes', 'phase1_journal_materialized_episodes',
    'phase1_journal_materialized_episode_fills', 'phase1_journal_projected_episodes',
    'phase1_journal_projected_instruments', 'phase1_journal_projected_executions',
    'phase1_journal_lifecycle_reconciliation_runs', 'phase1_journal_episode_lifecycle_states',
)


def _digest(value):
    return sha256(canonical_schwab_evidence_json(value).encode()).hexdigest()


def current_family_records(con, family):
    """Presentation evidence for exact-cutoff history plus its retained increments."""
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='phase1_schwab_snapshot_evidence_imports'").fetchone()[0]:
        return None
    sources = con.execute('''SELECT c.source_account_id,c.activation_uid,s.artifact_json
        FROM phase1_journal_current_revision_ids c
        JOIN phase1_journal_all_history_revisions r USING (revision_uid)
        JOIN phase1_schwab_snapshot_evidence_imports s USING (assembly_uid)''').fetchall()
    if not sources:
        return None
    records = []
    for account, activation, body in sources:
        records.extend(next(f['records'] for f in json.loads(body)['families'] if f['family']==family))
        if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='incremental_activity_imports'").fetchone()[0]:
            for uid, body in con.execute('''SELECT import_uid,artifact_json FROM incremental_activity_imports
                WHERE source_broker='schwab' AND source_account_id=? ORDER BY import_sequence''', [account]).fetchall():
                if sha256(body.encode()).hexdigest()!=uid:
                    raise ValueError('Presentation activity checksum differs.')
                saved = json.loads(body)
                if saved['activation_uid']==activation:
                    records.extend(saved['records'].get(family, ()))
    return records


def build_relations(baseline, episodes, projection, trades, events, event_legs):
    rows = {name: [] for name in RELATIONS}
    uid = projection.materialization_uid
    timestamp = baseline.cutoff.astimezone(UTC)
    by_uid = {t['episode_uid']: t for t in trades}
    for episode in episodes:
        p = episode.preview
        t = by_uid[p.episode_uid]
        quality, reason = t['lifecycle_quality'], t['lifecycle_reason']
        row = dict(episode_uid=p.episode_uid, source_broker=p.source_broker,
            source_account_id=p.source_account_id, primary_symbol=p.primary_symbol,
            asset_class=p.asset_class, strategy_type=p.strategy_type, strategy_label=p.strategy_label,
            opened_at=p.opened_at.astimezone(UTC), status=p.status,
            fill_count=p.fill_count, leg_count=p.leg_count, leg_summary=p.leg_summary,
            cashflow_label=p.cashflow_label, updated_at=timestamp)
        row.update({key: value if quality == 'resolved' else None for key, value in (
            ('net_quantity', p.net_quantity), ('gross_cashflow', p.gross_cashflow),
            ('commission', p.total_commission), ('fees', p.total_fees))})
        rows['trade_episodes'].append(row)
        rows['phase1_journal_materialized_episodes'].append(dict(
            materialization_uid=uid, episode_uid=p.episode_uid, scope_uid=episode.scope_uid,
            lifecycle_quality=quality, reason_code=reason, source_fill_count=len(episode.fill_uids),
            episode_fingerprint=episode.episode_fingerprint))
        rows['phase1_journal_materialized_episode_fills'].extend(dict(
            materialization_uid=uid, episode_uid=p.episode_uid, leg_index=index, fill_uid=fill_uid)
            for index, fill_uid in enumerate(episode.fill_uids, 1))
        state = dict(reconciliation_uid=uid, episode_uid=p.episode_uid, prior_status=p.status,
            reconciled_status=t['episode_status'], lifecycle_quality=quality, reason_code=reason,
            position_reconciliation_status=t['position_reconciliation_status'], matched_terminal_event_count=0)
        rows['phase1_journal_episode_lifecycle_states'].append({**state, 'state_fingerprint': _digest(state)})
    for relation, values in (
        ('phase1_journal_projected_episodes', projection.episodes),
        ('phase1_journal_projected_instruments', projection.instruments),
        ('phase1_journal_projected_executions', projection.executions),
    ):
        for value in values:
            row = dict(projection_uid=projection.projection_uid, **asdict(value))
            if relation.endswith('executions'):
                row['net_amount_reconciled'] = True
            rows[relation].append(row)
    counts = Counter(t['episode_status'] for t in trades)
    run = dict(reconciliation_uid=uid, contract_version=CONTRACT,
        assembly_uid=baseline.assembly.assembly_uid, source_materialization_uid=uid,
        source_account_id=baseline.assembly.source_account_id, asof_date=baseline.cutoff.date(),
        episode_count=len(trades), closed_count=counts['closed'], open_count=counts['open'],
        review_required_count=counts['review_required'], terminal_event_count=len(events),
        terminal_event_leg_count=len(event_legs), matched_terminal_event_leg_count=0,
        final_status='review_required' if any(t['lifecycle_quality'] != 'resolved' for t in trades)
        else 'reconciled', reconciled_at=timestamp)
    rows['phase1_journal_lifecycle_reconciliation_runs'].append({**run, 'result_fingerprint': _digest(run)})
    return dict(contract_version=CONTRACT, relations=rows)


def current_relation(con, legacy_name, base_name):
    """Typed SQL only: no financial calculation or filesystem access on reads."""
    if legacy_name not in RELATIONS or not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='incremental_activity_imports'").fetchone()[0]:
        return base_name
    from onejournal.journal.storage import PostgresConnection
    if isinstance(con, PostgresConnection):
        if con.execute("SELECT count(*) FROM incremental_activity_imports WHERE artifact_json LIKE '%\"journal_view\"%'").fetchone()[0]:
            raise ValueError('Saved incremental Journal views require the Mac DuckDB runtime.')
        return base_name
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='phase1_journal_current_revision_ids'").fetchone()[0]:
        return base_name
    # The shape is taken from the established relation, including decimal types.
    structure = json.dumps({r[0]: r[1] for r in con.execute(f'DESCRIBE {base_name}').fetchall()}).replace("'", "''")
    heads = """SELECT i.*, CASE WHEN sha256(i.artifact_json)=i.import_uid
        THEN i.artifact_json::JSON ELSE error('Saved activity checksum differs') END AS body
        FROM incremental_activity_imports i
        JOIN phase1_journal_current_revision_ids c
          ON i.source_broker=c.source_broker AND i.source_account_id=c.source_account_id
        WHERE json_extract_string(i.artifact_json,'$.activation_uid')=c.activation_uid
          AND json_extract_string(i.artifact_json,'$.revision_uid')=c.revision_uid
          AND i.import_sequence=(SELECT max(t.import_sequence) FROM incremental_activity_imports t
             WHERE t.source_broker=i.source_broker AND t.source_account_id=i.source_account_id)
          AND json_extract_string(i.artifact_json,'$.journal_view.contract_version')='onejournal.activity-journal.v1'"""
    if legacy_name == 'trade_episodes':
        exclusion = 'b.source_broker=h.source_broker AND b.source_account_id=h.source_account_id'
    elif legacy_name == 'phase1_journal_lifecycle_reconciliation_runs':
        exclusion = 'b.source_account_id=h.source_account_id'
    else:
        exclusion = """EXISTS (SELECT 1 FROM journal_current_trade_episodes e
            WHERE e.episode_uid=b.episode_uid AND e.source_broker=h.source_broker
              AND e.source_account_id=h.source_account_id)"""
    return f"""(WITH activity_heads AS ({heads})
        SELECT unnest(json_transform_strict(j.value, '{structure}'))
        FROM activity_heads h, json_each(h.body, '$.journal_view.relations.{legacy_name}') j
        UNION ALL SELECT b.* FROM {base_name} b
        WHERE NOT EXISTS (SELECT 1 FROM activity_heads h WHERE {exclusion}))"""
