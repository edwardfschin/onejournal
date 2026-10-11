"""Pure position-binding preparation from verified transaction coverage.

No symbol parsing creates identity, multiplier or currency here. Existing
coverage supplies transaction-authoritative identities; retained mappings may
cover instruments without fills. This is identity intake, not P&L acceptance.
"""

from dataclasses import dataclass, replace
from hashlib import sha256

from onejournal.brokers.schwab.position_binding import (
    SchwabPositionPrivateBinding,
    schwab_position_private_binding_bytes,
)
from onejournal.brokers.schwab.positions_json import (
    SchwabPositionMapping,
    load_positions_json_bytes,
)
from onejournal.provider_connectors.external_acquisition import (
    ConvertedExternalPositionSnapshot,
    SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE,
    VerifiedExternalProviderAcquisition,
    convert_external_schwab_positions,
)
from onejournal.provider_connectors.lifecycle_coverage import (
    AssembledLifecycleCoverage,
    LIFECYCLE_COVERAGE_CONTRACT_VERSION,
    calculate_lifecycle_coverage_sha256,
    transaction_instrument_identity,
)


class PositionRefreshBindingError(ValueError):
    """Identity evidence cannot safely cover the complete current snapshot."""


def _key(symbol: str) -> str:
    # Same private join normalization as the lifecycle-coverage contract.
    return "".join(symbol.upper().split())


@dataclass(frozen=True)
class PreparedPositionRefreshBinding:
    binding: SchwabPositionPrivateBinding
    position: ConvertedExternalPositionSnapshot
    coverage_sha256: str
    reused_mapping_count: int
    new_mapping_count: int
    retired_mapping_count: int

    def privacy_safe_audit(self) -> dict[str, object]:
        return {
            "schema": "onejournal.position-refresh-binding-audit.v1",
            "binding_sha256": sha256(schwab_position_private_binding_bytes(self.binding)).hexdigest(),
            "position_manifest_sha256": self.position.external_manifest_sha256,
            "position_raw_sha256": self.position.snapshot.raw_sha256,
            "snapshot_uid": self.position.snapshot.snapshot_uid,
            "coverage_sha256": self.coverage_sha256,
            "position_count": len(self.binding.mappings),
            "reused_mapping_count": self.reused_mapping_count,
            "new_mapping_count": self.new_mapping_count,
            "retired_mapping_count": self.retired_mapping_count,
            "financial_acceptance": False,
            "final_status": "position_binding_prepared_unmaterialized",
        }


def prepare_position_refresh_binding(
    acquisition: VerifiedExternalProviderAcquisition,
    baseline: SchwabPositionPrivateBinding,
    coverage: AssembledLifecycleCoverage,
) -> PreparedPositionRefreshBinding:
    """Bind a complete snapshot without widening any position's eligibility."""
    schwab_position_private_binding_bytes(baseline)  # Canonical/unique input.
    if acquisition.manifest.profile != SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE:
        raise PositionRefreshBindingError("verified position acquisition is required")
    if coverage.contract_version != LIFECYCLE_COVERAGE_CONTRACT_VERSION or (
        calculate_lifecycle_coverage_sha256(coverage) != coverage.assembly_sha256
    ):
        raise PositionRefreshBindingError("coverage contract or fingerprint differs")
    if (coverage.source_broker, coverage.connection_uid, coverage.source_account_id) != (
        "schwab", baseline.connection_uid, baseline.source_account_id
    ) or acquisition.manifest.connection_uid != baseline.connection_uid:
        raise PositionRefreshBindingError("position, baseline and coverage scopes differ")
    (request,) = acquisition.manifest.requests
    if coverage.evaluated_at != request.received_at_utc:
        raise PositionRefreshBindingError("coverage cutoff differs from position receipt")
    payload = load_positions_json_bytes(acquisition.response_bytes[request.response_filename])
    account = payload.get("securitiesAccount")
    rows = account.get("positions") if isinstance(account, dict) else None
    if not isinstance(rows, list):
        raise PositionRefreshBindingError("an explicit complete position list is required")
    symbols = []
    for row in rows:
        instrument = row.get("instrument") if isinstance(row, dict) else None
        symbol = instrument.get("symbol") if isinstance(instrument, dict) else None
        if not isinstance(symbol, str) or not symbol.strip():
            raise PositionRefreshBindingError("position instrument symbol is missing")
        symbols.append(symbol)
    current_keys = {_key(symbol) for symbol in symbols}
    prior = {_key(item.provider_symbol): item.identity for item in baseline.mappings}
    assessed = {_key(item.source_instrument_id): item for item in coverage.positions}
    if len(current_keys) != len(symbols) or len(prior) != len(baseline.mappings) or (
        len(assessed) != len(coverage.positions) or current_keys != set(assessed)
    ):
        raise PositionRefreshBindingError("position and coverage membership is ambiguous")
    mappings = []
    for symbol in sorted(symbols):
        key = _key(symbol)
        identities = {
            transaction_instrument_identity(row)
            for row in coverage.transaction_rows
            if _key(row.get("option_symbol", "") if row.get("asset_class") == "option"
                    else row.get("symbol", "")) == key
        }
        if len(identities) > 1 or assessed[key].identity != next(iter(identities), None):
            raise PositionRefreshBindingError("coverage identity differs from transaction evidence")
        identity = next(iter(identities), None)
        if key in prior:
            if identity is not None and identity != prior[key]:
                raise PositionRefreshBindingError("retained identity conflicts with transaction evidence")
            identity = prior[key]
        if identity is None:
            raise PositionRefreshBindingError("new instrument lacks transaction-authoritative identity")
        mappings.append(SchwabPositionMapping(symbol, identity))
    binding = replace(baseline, mappings=tuple(mappings))
    schwab_position_private_binding_bytes(binding)
    position = convert_external_schwab_positions(
        acquisition,
        provider_account_hash=binding.provider_account_hash,
        provider_account_number=binding.provider_account_number,
        source_account_id=binding.source_account_id,
        mappings=binding.mappings,
    )
    snapshot_by_identity = {item.identity.key: item for item in position.snapshot.positions}
    for mapping in binding.mappings:
        target = assessed[_key(mapping.provider_symbol)]
        if snapshot_by_identity[mapping.identity.key].quantity != target.broker_quantity:
            raise PositionRefreshBindingError("coverage target differs from the complete snapshot")
    return PreparedPositionRefreshBinding(
        binding, position, coverage.assembly_sha256,
        len(current_keys & set(prior)), len(current_keys - set(prior)), len(set(prior) - current_keys),
    )
