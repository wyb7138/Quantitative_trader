"""Position sizing utilities."""

from config import PORTFOLIO


def equal_weight(capital: float, n_positions: int) -> float:
    """Allocate capital equally across N positions, capped by max_position_pct."""
    n = max(1, n_positions)
    return min(capital / n, capital * PORTFOLIO["max_position_pct"])


def volatility_target(capital: float, annual_vol: float, target_vol: float = 0.15) -> float:
    """Size a position so its standalone vol equals target_vol of capital."""
    if annual_vol <= 0:
        return 0.0
    return capital * target_vol / annual_vol


def kelly(win_rate: float, win_loss_ratio: float, fraction: float = 0.5) -> float:
    """Fractional Kelly criterion.  Returns the fraction of capital to risk."""
    if win_loss_ratio <= 0:
        return 0.0
    k = win_rate - (1.0 - win_rate) / win_loss_ratio
    return max(0.0, k * fraction)
