from core.models import Quantity
from verification.numeric import (compare_quantity, extract_punishments, extract_quantities,
                                  words_to_number)


def test_words_to_number_indian_units():
    assert words_to_number("one lakh") == 100000
    assert words_to_number("five lakh") == 500000
    assert words_to_number("two crore") == 20000000
    assert words_to_number("twenty three") == 23


def test_words_to_number_amendment_artifact():
    # "two three" (a struck-through amendment in the consolidated PDF) -> keep the later value
    assert words_to_number("two three") == 3


def test_extract_duration_and_fine():
    qs = extract_quantities("imprisonment for a term which may extend to three years and a fine which may "
                            "extend to rupees one lakh")
    durations = [q for q in qs if q.kind == "duration"]
    money = [q for q in qs if q.kind == "money"]
    assert durations and durations[0].value == 3 and durations[0].qualifier == "max"
    assert money and money[0].value == 100000 and money[0].qualifier == "max"


def test_minimum_qualifier_detected():
    qs = extract_quantities("a mandatory minimum fine of five lakh rupees")
    assert qs[0].qualifier == "min" and qs[0].value == 500000


def test_age_detection():
    qs = extract_quantities("a child of the age of six to fourteen years")
    assert any(q.kind == "age" for q in qs)


def test_punishment_types():
    p = extract_punishments("shall be punished with death or imprisonment for life, and shall also be liable to fine")
    assert "death" in p and "fine" in p and "life_imprisonment" in p


def test_compare_qualifier_conflict():
    claim = Quantity(kind="money", value=100000, qualifier="min", applies_to="fine", raw="min 1 lakh")
    ev = [Quantity(kind="money", value=100000, qualifier="max", applies_to="fine", raw="up to 1 lakh")]
    verdict, _ = compare_quantity(claim, ev)
    assert verdict == "qualifier_conflict"


def test_compare_value_conflict():
    claim = Quantity(kind="duration", value=10, qualifier="max", applies_to="imprisonment", raw="10 years")
    ev = [Quantity(kind="duration", value=3, qualifier="max", applies_to="imprisonment", raw="3 years")]
    verdict, _ = compare_quantity(claim, ev)
    assert verdict == "value_conflict"
