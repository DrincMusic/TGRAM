from pkg.util import clamp


class Calculator:
    def discounted(self, price: float, percent: float) -> float:
        return clamp(price * (1 - percent / 100))
