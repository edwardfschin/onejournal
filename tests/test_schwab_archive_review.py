from dataclasses import replace

import pytest

from onejournal.brokers.schwab.archive_review import (
    ArchiveReviewError, ArchiveTradeObservation, review_archive_trade_versions,
)
from onejournal.brokers.schwab.transactions_json import NORMALIZED_FILL_COLUMNS


ACCOUNT = "synthetic-archive-account"


def row(item="0", **changes):
    result = dict.fromkeys(NORMALIZED_FILL_COLUMNS, "")
    result.update(source_broker="schwab", source_account_id=ACCOUNT,
                  source_fill_id=f"schwab_txn:123:order:456:position:789:item:{item}",
                  asof="2025-01-02", filled_at="2025-01-02T14:30:00Z",
                  source_order_id="456", asset_class="stock", symbol="TEST",
                  side="buy", quantity="2", fill_price="10", commission="0",
                  fees="0", currency="USD", open_close="open")
    result.update(changes)
    return result


def observation(*rows, raw="a", record="b", **changes):
    return ArchiveTradeObservation("123", raw * 64, record * 64, rows, **changes)


def review(*observations, existing=()):
    return review_archive_trade_versions(observations, source_account_id=ACCOUNT,
                                         existing_rows=existing)


def test_equivalent_versions_retain_ids_all_lineage_and_item_multiplicity():
    one, two = row("0"), row("1")
    result = review(observation(one, two), observation(two, one, raw="c", record="d"))[0]
    assert result.status == "candidate" and len(result.new_rows) == 2
    assert {item["source_fill_id"] for item in result.rows} == {one["source_fill_id"], two["source_fill_id"]}
    assert result.source_raw_sha256s == ("a" * 64, "c" * 64)
    assert result.source_record_sha256s == ("b" * 64, "d" * 64)
    assert result == review(observation(two, one, raw="c", record="d"), observation(one, two))[0]
    with pytest.raises(TypeError):
        result.rows[0]["quantity"] = "3"


def test_changed_generated_ids_are_withheld_not_renamed():
    result = review(observation(row()), observation(row("1"), raw="c"))[0]
    assert result.reasons == ("generated_fill_identity_changed",)
    assert result.status == "withheld" and result.rows == result.new_rows == ()


@pytest.mark.parametrize("changes", [{"fill_price": "11"}, {"symbol": "OTHER"}, {"quantity": "3"}])
def test_changed_economics_or_names_withhold_entire_activity(changes):
    result = review(observation(row(), row("1")), observation(row(**changes), row("1")))[0]
    assert "normalized_version_conflict" in result.reasons
    assert result.new_rows == ()


def test_existing_exact_fill_is_reused_but_changed_content_is_withheld():
    existing = row()
    assert review(observation(existing), existing=(existing,))[0].status == "existing_replay"
    assert review(observation(existing), existing=(existing,))[0].new_rows == ()
    result = review(observation(row(fill_price="11")), existing=(existing,))[0]
    assert "existing_fill_content_conflict" in result.reasons
    assert result.rows == ()


def test_same_existing_activity_under_another_id_cannot_be_added_again():
    result = review(observation(row("1")), existing=(row(),))[0]
    assert result.reasons == ("existing_activity_identity_changed",)
    assert result.status == "withheld" and result.new_rows == ()
    partial = review(observation(row(), row("1")), existing=(row(),))[0]
    assert "existing_activity_content_conflict" in partial.reasons
    assert partial.rows == ()


def test_duplicate_ids_partial_adapter_exclusions_and_empty_versions_fail_closed():
    for source in (observation(row(), row()), observation(row(), adapter_exclusions=True), observation()):
        result = review(source)[0]
        assert result.status == "withheld" and not result.rows


def test_invalid_scope_lineage_and_activity_raise_value_free_errors():
    valid = observation(row())
    for source in (replace(valid, raw_sha256="bad"), replace(valid, activity_id=""),
                   replace(valid, activity_id="999"), observation(row(source_account_id="private-other-account"))):
        with pytest.raises(ArchiveReviewError) as caught:
            review(source)
        assert "private-other-account" not in str(caught.value)
    with pytest.raises(ArchiveReviewError):
        review(valid, existing=(row(), row()))
