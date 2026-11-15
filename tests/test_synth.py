from __future__ import annotations

import re
from pathlib import Path

from callrag import synth

CALLS = synth.generate(40, seed=7)


def test_generation_is_deterministic_and_stable_when_extended() -> None:
    assert synth.generate(40, seed=7) == CALLS
    longer = synth.generate(60, seed=7)
    by_id = {c.call_id: c for c in longer}
    assert all(by_id[c.call_id] == c for c in CALLS)  # more calls never change earlier ones
    assert synth.generate(40, seed=8) != CALLS


def test_three_tenants_with_their_own_ids() -> None:
    assert {c.tenant_id for c in CALLS} == {"delta-plumbing", "valley-air", "brightline-electric"}
    assert len({c.call_id for c in CALLS}) == len(CALLS) == 120
    assert all(c.call_id.startswith(c.tenant_id) for c in CALLS)


def test_the_answer_key_points_at_the_planted_values() -> None:
    for call in CALLS:
        assert call.pii, call.call_id
        for item in call.pii:
            assert call.turns[item.turn].text[item.start : item.end] == item.value


def test_planted_values_are_obviously_fake() -> None:
    for call in CALLS:
        for item in call.pii:
            digits = re.sub(r"\D", "", item.value)
            if item.kind == "PHONE" and item.form != "spoken":
                assert digits[3:8] == "55501", item.value  # the reserved 555-01xx range
            if item.kind == "EMAIL" and item.form == "written":
                assert item.value.endswith("@example.com")
            if item.kind == "CARD":
                assert digits.startswith("400000") and synth.luhn_valid(digits)


def test_confirmation_codes_fail_the_card_check_digit() -> None:
    codes = [
        m.group(1)
        for c in synth.generate(200, seed=7)
        for t in c.turns
        if (m := re.search(r"confirmation code is ([\d ]+)\.", t.text))
    ]
    assert len(codes) > 50
    assert not any(synth.luhn_valid(code.replace(" ", "")) for code in codes)


def test_luhn() -> None:
    assert synth.luhn_valid("4242424242424242")
    assert not synth.luhn_valid("4242424242424241")


def test_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    synth.write_jsonl(CALLS, path)
    assert list(synth.read_jsonl(path)) == CALLS


def test_committed_sample_matches_the_generator() -> None:
    sample = Path(__file__).resolve().parents[1] / "data" / "sample_calls.jsonl"
    assert list(synth.read_jsonl(sample)) == synth.generate(2, seed=7)
