from __future__ import annotations

import pytest

from callrag.redact import redact


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Sure, maria.lopez12@example.com.", "Sure, [EMAIL]."),
        ("it is maria dot lopez12 at example dot com", "it is [EMAIL]"),
        ("(916) 555-0142, that's my cell.", "[PHONE], that's my cell."),
        ("Call 916-555-0142 or 530.555.0199", "Call [PHONE] or [PHONE]"),
        ("my number is 9165550142", "my number is [PHONE]"),
        ("+1 916 555 0142", "[PHONE]"),
        (
            "nine one six five five five zero one four two, call or text",
            "[PHONE], call or text",
        ),
        ("Use 4000 0012 3456 7899, expires 04/29.", "Use [CARD], expires 04/29."),
        ("Use 4000-0012-3456-7899 please", "Use [CARD] please"),
        ("card 4000001234567899 on file", "card [CARD] on file"),
        ("It is 4730 Alder Lane, Marlow, CA 95794.", "It is [ADDRESS]."),
        ("We are at 88 Quail Hollow Court, Apt 12B.", "We are at [ADDRESS]."),
        ("it's 1420 copper ridge drive in town", "it's [ADDRESS] in town"),
        ("Hi, my name is Maria Lopez. The sink", "Hi, my name is [NAME]. The sink"),
        ("Hello, this is Omar.", "Hello, this is [NAME]."),
        ("but my husband Victor will be home", "but my husband [NAME] will be home"),
        ("Ask for Dr. Haddad", "Ask for Dr. [NAME]"),
    ],
)
def test_what_gets_redacted(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "I have you down for Tuesday between 8 and 10.",
        "Your job number is J-48213.",
        "There is an 89 dollar dispatch fee.",
        "The model is RHEEM-XG50T06EC and it is twelve years old.",
        "It says 100 amps on the main, maybe thirty feet away.",
        "Three blinks, then a pause.",
        "This is Thursday's appointment, right?",
        "It's Really loud at startup.",
        "your confirmation code is 8830 2219 4471 0036.",  # 16 digits, wrong check digit
        "One, two, three breakers tripped.",  # spoken digits, but too few to be a number
    ],
)
def test_what_is_left_alone(text: str) -> None:
    assert redact(text) == text


def test_names_the_business_already_holds_are_removed_everywhere() -> None:
    known = ("Maria Lopez", "Priya")
    text = "Thanks, Maria. Ms Lopez, this is Priya again. MARIA LOPEZ, right?"
    assert redact(text, known) == "Thanks, [NAME]. Ms [NAME], this is [NAME] again. [NAME], right?"
    # A known name must match as a whole word: "Maria" is not removed from "Mariah".
    assert redact("Mariah called", known) == "Mariah called"


def test_a_card_number_is_one_redaction_not_a_card_and_a_phone() -> None:
    assert redact("4000 0012 3456 7899") == "[CARD]"


def test_redaction_is_stable_when_applied_twice() -> None:
    text = "Hi, my name is Maria Lopez, (916) 555-0142, 12 Birch Way, maria@example.com."
    once = redact(text)
    assert redact(once) == once
    assert once == "Hi, my name is [NAME], [PHONE], [ADDRESS], [EMAIL]."


# The three tests below pin behaviour the README lists as limits. If one starts failing because
# the redactor improved, update the README and docs/eval.md with it.


def test_limit_a_ten_digit_serial_number_is_redacted_as_a_phone() -> None:
    assert redact("the serial number is 2043118822.") == "the serial number is [PHONE]."


def test_limit_a_name_with_no_cue_is_missed() -> None:
    assert redact("I will be at work. Naomi will let the technician in.") == (
        "I will be at work. Naomi will let the technician in."
    )


def test_limit_an_address_described_in_words_is_missed() -> None:
    text = "it is the blue house on Alder past the school."
    assert redact(text) == text
