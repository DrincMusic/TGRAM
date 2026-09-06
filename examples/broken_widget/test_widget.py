from widget import discounted_price


def test_twenty_percent_discount() -> None:
    assert discounted_price(100, 20) == 80


def test_ten_percent_discount() -> None:
    assert discounted_price(50, 10) == 45
