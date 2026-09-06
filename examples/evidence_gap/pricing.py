def discounted_price(price: float, discount_percent: float) -> float:
    """Apply the product contract's discount calculation."""
    return price * (1 - discount_percent / 100)
