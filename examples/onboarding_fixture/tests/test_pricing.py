from pkg.pricing import Calculator


def test_discounted() -> None:
    assert Calculator().discounted(100, 10) == 90
