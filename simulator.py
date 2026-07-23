"""Educational market-making and limit-order-book simulator.

The project has two layers:
1. LimitOrderBook implements price-time-priority matching.
2. MarketMakingSimulator places inventory-aware quotes into that book and
   measures the resulting cash, inventory, fills, P&L, and drawdown.

This is deliberately a transparent research simulator, not a live trading
system or a claim about achievable real-world returns.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Deque, Dict, Iterable, Literal, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


Side = Literal["buy", "sell"]


@dataclass
class Order:
    """One order submitted to the exchange."""

    order_id: int
    trader_id: str
    side: Side
    quantity: int
    remaining: int
    timestamp: int
    price: Optional[float] = None


@dataclass(frozen=True)
class Trade:
    """One execution produced by the matching engine."""

    timestamp: int
    price: float
    quantity: int
    buyer_id: str
    seller_id: str
    buyer_order_id: int
    seller_order_id: int
    maker_order_id: int
    taker_order_id: int


class LimitOrderBook:
    """A small price-time-priority limit-order book.

    Prices are stored in price-level queues. The best price is selected first;
    orders at the same price are matched in FIFO order.
    """

    def __init__(self, price_decimals: int = 2) -> None:
        self.price_decimals = price_decimals
        self.bids: Dict[float, Deque[Order]] = defaultdict(deque)
        self.asks: Dict[float, Deque[Order]] = defaultdict(deque)
        self.order_lookup: Dict[int, Order] = {}
        self.trades: list[Trade] = []
        self._next_order_id = 1
        self._clock = 0

    def _normalise_price(self, price: float) -> float:
        return round(float(price), self.price_decimals)

    def _new_order(
        self,
        trader_id: str,
        side: Side,
        quantity: int,
        price: Optional[float],
    ) -> Order:
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if price is not None and price <= 0:
            raise ValueError("price must be positive")

        self._clock += 1
        order = Order(
            order_id=self._next_order_id,
            trader_id=trader_id,
            side=side,
            quantity=int(quantity),
            remaining=int(quantity),
            timestamp=self._clock,
            price=None if price is None else self._normalise_price(price),
        )
        self._next_order_id += 1
        return order

    @property
    def best_bid(self) -> Optional[float]:
        return max(self.bids) if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return min(self.asks) if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return round(self.best_ask - self.best_bid, self.price_decimals)

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    def submit_limit_order(
        self,
        trader_id: str,
        side: Side,
        price: float,
        quantity: int,
    ) -> tuple[int, list[Trade]]:
        """Submit a limit order, match it, and rest any unfilled quantity."""

        incoming = self._new_order(trader_id, side, quantity, price)
        new_trades = self._match(incoming)

        if incoming.remaining > 0:
            book_side = self.bids if side == "buy" else self.asks
            book_side[incoming.price].append(incoming)
            self.order_lookup[incoming.order_id] = incoming

        return incoming.order_id, new_trades

    def submit_market_order(
        self,
        trader_id: str,
        side: Side,
        quantity: int,
    ) -> tuple[int, list[Trade]]:
        """Submit an immediately executable order.

        Any quantity left after available liquidity is consumed is discarded.
        """

        incoming = self._new_order(trader_id, side, quantity, price=None)
        new_trades = self._match(incoming)
        return incoming.order_id, new_trades

    def _match(self, incoming: Order) -> list[Trade]:
        opposite = self.asks if incoming.side == "buy" else self.bids
        new_trades: list[Trade] = []

        while incoming.remaining > 0 and opposite:
            best_price = min(opposite) if incoming.side == "buy" else max(opposite)

            if incoming.price is not None:
                crosses = (
                    incoming.price >= best_price
                    if incoming.side == "buy"
                    else incoming.price <= best_price
                )
                if not crosses:
                    break

            queue = opposite[best_price]
            resting = queue[0]
            traded_quantity = min(incoming.remaining, resting.remaining)

            if incoming.side == "buy":
                buyer, seller = incoming, resting
            else:
                buyer, seller = resting, incoming

            trade = Trade(
                timestamp=self._clock,
                price=float(resting.price),
                quantity=traded_quantity,
                buyer_id=buyer.trader_id,
                seller_id=seller.trader_id,
                buyer_order_id=buyer.order_id,
                seller_order_id=seller.order_id,
                maker_order_id=resting.order_id,
                taker_order_id=incoming.order_id,
            )
            self.trades.append(trade)
            new_trades.append(trade)

            incoming.remaining -= traded_quantity
            resting.remaining -= traded_quantity

            if resting.remaining == 0:
                queue.popleft()
                self.order_lookup.pop(resting.order_id, None)
                if not queue:
                    del opposite[best_price]

        return new_trades

    def cancel_order(self, order_id: int) -> bool:
        """Cancel a resting order. Return False if it no longer exists."""

        order = self.order_lookup.pop(order_id, None)
        if order is None:
            return False

        book_side = self.bids if order.side == "buy" else self.asks
        queue = book_side[order.price]
        book_side[order.price] = deque(
            resting
            for resting in queue
            if resting.order_id != order_id
        )
        if not book_side[order.price]:
            del book_side[order.price]
        return True

    def cancel_all(self) -> int:
        """Cancel every resting order and return the number removed."""

        order_ids = list(self.order_lookup)
        for order_id in order_ids:
            self.cancel_order(order_id)
        return len(order_ids)

    def depth(self, side: Side, levels: int = 5) -> list[tuple[float, int]]:
        """Return aggregated quantity at the best price levels."""

        if levels <= 0:
            return []
        book_side = self.bids if side == "buy" else self.asks
        prices: Iterable[float] = sorted(
            book_side,
            reverse=(side == "buy"),
        )
        result = []
        for price in list(prices)[:levels]:
            result.append(
                (price, sum(order.remaining for order in book_side[price]))
            )
        return result


@dataclass(frozen=True)
class SimulationConfig:
    """Parameters controlling the market and the market maker."""

    n_steps: int = 1_000
    seed: int = 42
    initial_price: float = 100.0
    initial_cash: float = 100_000.0
    initial_inventory: int = 0
    tick_size: float = 0.01
    price_volatility: float = 0.035
    background_half_spread: float = 0.10
    background_levels: int = 4
    background_quantity_min: int = 4
    background_quantity_max: int = 10
    quote_quantity: int = 5
    half_spread: float = 0.06
    inventory_skew: float = 0.012
    max_inventory: int = 30
    market_order_probability: float = 0.68
    market_order_quantity_min: int = 1
    market_order_quantity_max: int = 7
    informed_order_probability: float = 0.22
    adverse_price_move: float = 0.018
    fee_per_share: float = 0.001


class MarketMakingSimulator:
    """Run one inventory-aware market-making experiment."""

    MARKET_MAKER_ID = "market_maker"

    def __init__(self, config: Optional[SimulationConfig] = None) -> None:
        self.config = config or SimulationConfig()
        self.rng = np.random.default_rng(self.config.seed)
        self.book = LimitOrderBook(price_decimals=2)
        self.cash = float(self.config.initial_cash)
        self.inventory = int(self.config.initial_inventory)
        self.fair_price = float(self.config.initial_price)
        self.submitted_quote_volume = 0
        self.filled_quote_volume = 0
        self.submitted_quote_orders = 0
        self.filled_quote_order_ids: set[int] = set()
        self.market_maker_trades: list[Trade] = []
        self.records: list[dict[str, float]] = []

    def _round_to_tick(self, price: float) -> float:
        tick = self.config.tick_size
        return round(round(price / tick) * tick, 2)

    def calculate_quotes(self) -> tuple[Optional[float], Optional[float]]:
        """Calculate post-only quotes with an inventory-adjusted centre."""

        cfg = self.config
        centre = self.fair_price - cfg.inventory_skew * self.inventory
        bid = self._round_to_tick(centre - cfg.half_spread)
        ask = self._round_to_tick(centre + cfg.half_spread)

        # Keep quotes passive: do not cross the background market.
        if self.book.best_ask is not None:
            bid = min(bid, self._round_to_tick(self.book.best_ask - cfg.tick_size))
        if self.book.best_bid is not None:
            ask = max(ask, self._round_to_tick(self.book.best_bid + cfg.tick_size))

        bid_quote = None if self.inventory >= cfg.max_inventory else bid
        ask_quote = None if self.inventory <= -cfg.max_inventory else ask
        return bid_quote, ask_quote

    def _seed_background_liquidity(self) -> None:
        """Build several external bid and ask levels around fair value."""

        cfg = self.config
        for level in range(cfg.background_levels):
            distance = cfg.background_half_spread + level * 2 * cfg.tick_size
            bid_price = self._round_to_tick(self.fair_price - distance)
            ask_price = self._round_to_tick(self.fair_price + distance)
            bid_quantity = int(
                self.rng.integers(
                    cfg.background_quantity_min,
                    cfg.background_quantity_max + 1,
                )
            )
            ask_quantity = int(
                self.rng.integers(
                    cfg.background_quantity_min,
                    cfg.background_quantity_max + 1,
                )
            )
            self.book.submit_limit_order(
                trader_id=f"external_bid_{level}",
                side="buy",
                price=bid_price,
                quantity=bid_quantity,
            )
            self.book.submit_limit_order(
                trader_id=f"external_ask_{level}",
                side="sell",
                price=ask_price,
                quantity=ask_quantity,
            )

    def _place_market_maker_quotes(
        self,
    ) -> tuple[Optional[float], Optional[float]]:
        cfg = self.config
        bid_quote, ask_quote = self.calculate_quotes()

        if bid_quote is not None:
            self.book.submit_limit_order(
                self.MARKET_MAKER_ID,
                "buy",
                bid_quote,
                cfg.quote_quantity,
            )
            self.submitted_quote_orders += 1
            self.submitted_quote_volume += cfg.quote_quantity

        if ask_quote is not None:
            self.book.submit_limit_order(
                self.MARKET_MAKER_ID,
                "sell",
                ask_quote,
                cfg.quote_quantity,
            )
            self.submitted_quote_orders += 1
            self.submitted_quote_volume += cfg.quote_quantity

        return bid_quote, ask_quote

    def _process_external_order(self) -> tuple[Optional[Side], bool, list[Trade]]:
        cfg = self.config
        if self.rng.random() >= cfg.market_order_probability:
            return None, False, []

        side: Side = "buy" if self.rng.random() < 0.5 else "sell"
        quantity = int(
            self.rng.integers(
                cfg.market_order_quantity_min,
                cfg.market_order_quantity_max + 1,
            )
        )
        informed = bool(self.rng.random() < cfg.informed_order_probability)
        _, trades = self.book.submit_market_order(
            trader_id="external_taker",
            side=side,
            quantity=quantity,
        )
        return side, informed, trades

    def _apply_market_maker_trades(self, trades: Iterable[Trade]) -> None:
        fee = self.config.fee_per_share
        for trade in trades:
            market_maker_order_id: Optional[int] = None

            if trade.buyer_id == self.MARKET_MAKER_ID:
                self.inventory += trade.quantity
                self.cash -= trade.price * trade.quantity
                market_maker_order_id = trade.buyer_order_id
            elif trade.seller_id == self.MARKET_MAKER_ID:
                self.inventory -= trade.quantity
                self.cash += trade.price * trade.quantity
                market_maker_order_id = trade.seller_order_id
            else:
                continue

            self.cash -= fee * trade.quantity
            self.filled_quote_volume += trade.quantity
            self.filled_quote_order_ids.add(market_maker_order_id)
            self.market_maker_trades.append(trade)

    def _move_fair_price(
        self,
        external_side: Optional[Side],
        informed: bool,
    ) -> None:
        cfg = self.config
        random_move = float(self.rng.normal(0.0, cfg.price_volatility))
        informed_move = 0.0
        if informed and external_side is not None:
            informed_move = (
                cfg.adverse_price_move
                if external_side == "buy"
                else -cfg.adverse_price_move
            )
        self.fair_price = max(1.0, self.fair_price + random_move + informed_move)

    def run(self) -> pd.DataFrame:
        """Run the configured number of steps and return the time series."""

        cfg = self.config
        initial_wealth = (
            cfg.initial_cash + cfg.initial_inventory * cfg.initial_price
        )

        for step in range(cfg.n_steps):
            self.book.cancel_all()
            self._seed_background_liquidity()
            bid_quote, ask_quote = self._place_market_maker_quotes()

            external_side, informed, trades = self._process_external_order()
            self._apply_market_maker_trades(trades)
            self._move_fair_price(external_side, informed)

            wealth = self.cash + self.inventory * self.fair_price
            quoted_spread = (
                round(ask_quote - bid_quote, 2)
                if bid_quote is not None and ask_quote is not None
                else np.nan
            )
            self.records.append(
                {
                    "step": step,
                    "fair_price": self.fair_price,
                    "bid_quote": np.nan if bid_quote is None else bid_quote,
                    "ask_quote": np.nan if ask_quote is None else ask_quote,
                    "quoted_spread": quoted_spread,
                    "inventory": self.inventory,
                    "cash": self.cash,
                    "wealth": wealth,
                    "pnl": wealth - initial_wealth,
                    "cumulative_trades": len(self.market_maker_trades),
                    "cumulative_filled_volume": self.filled_quote_volume,
                }
            )

        results = pd.DataFrame(self.records)
        running_peak = results["wealth"].cummax()
        results["drawdown"] = running_peak - results["wealth"]
        return results

    def metrics(self, results: pd.DataFrame) -> dict[str, float]:
        """Calculate the main strategy performance measurements."""

        if results.empty:
            raise ValueError("run the simulation before requesting metrics")

        return {
            "total_pnl": float(results["pnl"].iloc[-1]),
            "final_cash": float(results["cash"].iloc[-1]),
            "final_inventory": int(results["inventory"].iloc[-1]),
            "trade_count": len(self.market_maker_trades),
            "filled_volume": self.filled_quote_volume,
            "volume_fill_rate": (
                self.filled_quote_volume / self.submitted_quote_volume
                if self.submitted_quote_volume
                else 0.0
            ),
            "quote_order_fill_rate": (
                len(self.filled_quote_order_ids) / self.submitted_quote_orders
                if self.submitted_quote_orders
                else 0.0
            ),
            "average_quoted_spread": float(
                results["quoted_spread"].dropna().mean()
            ),
            "maximum_absolute_inventory": int(results["inventory"].abs().max()),
            "inventory_volatility": float(results["inventory"].std(ddof=0)),
            "maximum_drawdown": float(results["drawdown"].max()),
        }


def plot_dashboard(
    results: pd.DataFrame,
    metrics: dict[str, float],
    output_path: Path | str,
) -> None:
    """Save a six-panel summary of one simulation."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(3, 2, figsize=(15, 12), sharex=True)
    ax_price, ax_inventory, ax_pnl, ax_drawdown, ax_spread, ax_fills = axes.flat

    ax_price.plot(
        results["step"],
        results["fair_price"],
        color="#111827",
        linewidth=1.5,
        label="Fair price",
    )
    ax_price.plot(
        results["step"],
        results["bid_quote"],
        color="#2563eb",
        alpha=0.65,
        linewidth=0.8,
        label="Bid quote",
    )
    ax_price.plot(
        results["step"],
        results["ask_quote"],
        color="#dc2626",
        alpha=0.65,
        linewidth=0.8,
        label="Ask quote",
    )
    ax_price.set_title("Fair price and market-maker quotes")
    ax_price.set_ylabel("Price")
    ax_price.legend(frameon=True, ncol=3, fontsize=8)

    inventory = results["inventory"].to_numpy(dtype=float)
    steps = results["step"].to_numpy(dtype=float)
    ax_inventory.plot(steps, inventory, color="#7c3aed", linewidth=1.3)
    ax_inventory.fill_between(
        steps,
        0,
        inventory,
        where=inventory >= 0,
        color="#2563eb",
        alpha=0.20,
    )
    ax_inventory.fill_between(
        steps,
        0,
        inventory,
        where=inventory < 0,
        color="#dc2626",
        alpha=0.20,
    )
    ax_inventory.axhline(0, color="#111827", linewidth=0.8)
    ax_inventory.set_title("Inventory exposure")
    ax_inventory.set_ylabel("Shares")

    pnl = results["pnl"].to_numpy(dtype=float)
    ax_pnl.plot(steps, pnl, color="#059669", linewidth=1.5)
    ax_pnl.fill_between(
        steps,
        0,
        pnl,
        where=pnl >= 0,
        color="#10b981",
        alpha=0.20,
    )
    ax_pnl.fill_between(
        steps,
        0,
        pnl,
        where=pnl < 0,
        color="#ef4444",
        alpha=0.20,
    )
    ax_pnl.axhline(0, color="#111827", linewidth=0.8)
    ax_pnl.set_title(f"Mark-to-market P&L (final: {metrics['total_pnl']:.2f})")
    ax_pnl.set_ylabel("P&L")

    ax_drawdown.fill_between(
        steps,
        0,
        results["drawdown"].to_numpy(dtype=float),
        color="#ef4444",
        alpha=0.55,
    )
    ax_drawdown.set_title(
        f"Drawdown (maximum: {metrics['maximum_drawdown']:.2f})"
    )
    ax_drawdown.set_ylabel("Loss from peak")

    ax_spread.plot(
        steps,
        results["quoted_spread"],
        color="#d97706",
        linewidth=1.2,
    )
    observed_spreads = results["quoted_spread"].dropna()
    if not observed_spreads.empty:
        spread_min = float(observed_spreads.min())
        spread_max = float(observed_spreads.max())
        padding = max(0.01, (spread_max - spread_min) * 0.15)
        ax_spread.set_ylim(spread_min - padding, spread_max + padding)
    ax_spread.set_title("Quoted spread")
    ax_spread.set_ylabel("Ask minus bid")
    ax_spread.set_xlabel("Simulation step")

    ax_fills.plot(
        steps,
        results["cumulative_filled_volume"],
        color="#0891b2",
        linewidth=1.5,
        label="Filled volume",
    )
    ax_fills.plot(
        steps,
        results["cumulative_trades"],
        color="#64748b",
        linewidth=1.1,
        label="Executions",
    )
    ax_fills.set_title(
        f"Fills (volume fill rate: {metrics['volume_fill_rate']:.1%})"
    )
    ax_fills.set_ylabel("Cumulative count")
    ax_fills.set_xlabel("Simulation step")
    ax_fills.legend(frameon=True, fontsize=8)

    fig.suptitle(
        "Inventory-Aware Market-Making Simulation",
        fontsize=18,
        fontweight="bold",
        y=0.995,
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_order_book_snapshot(
    book: LimitOrderBook,
    output_path: Path | str,
    levels: int = 5,
) -> None:
    """Save the final order-book depth snapshot."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bids = book.depth("buy", levels)
    asks = book.depth("sell", levels)

    prices = sorted({price for price, _ in bids + asks})
    bid_lookup = dict(bids)
    ask_lookup = dict(asks)
    bid_values = [-bid_lookup.get(price, 0) for price in prices]
    ask_values = [ask_lookup.get(price, 0) for price in prices]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(prices, bid_values, height=0.008, color="#2563eb", label="Bid depth")
    ax.barh(prices, ask_values, height=0.008, color="#dc2626", label="Ask depth")
    ax.axvline(0, color="#111827", linewidth=0.8)
    ax.set_title("Final Limit-Order-Book Snapshot", fontsize=15, fontweight="bold")
    ax.set_xlabel("Quantity (bids shown to the left)")
    ax.set_ylabel("Price")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def compare_strategies(
    base_config: SimulationConfig,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Run four quoting policies using the same random seed."""

    variants = {
        "No inventory control": replace(
            base_config,
            inventory_skew=0.0,
        ),
        "Tight spread": replace(
            base_config,
            half_spread=0.04,
            inventory_skew=0.010,
        ),
        "Baseline": base_config,
        "Conservative": replace(
            base_config,
            half_spread=0.09,
            inventory_skew=0.018,
        ),
    }

    metric_rows = []
    histories: dict[str, pd.DataFrame] = {}
    for name, config in variants.items():
        simulator = MarketMakingSimulator(config)
        history = simulator.run()
        metric_rows.append({"strategy": name, **simulator.metrics(history)})
        histories[name] = history

    return pd.DataFrame(metric_rows), histories


def plot_strategy_comparison(
    comparison: pd.DataFrame,
    output_path: Path | str,
) -> None:
    """Save P&L, risk, and fill-rate comparisons."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    colours = ["#64748b", "#0891b2", "#2563eb", "#7c3aed"]
    names = comparison["strategy"]

    axes[0].bar(names, comparison["total_pnl"], color=colours)
    axes[0].axhline(0, color="#111827", linewidth=0.8)
    axes[0].set_title("Final P&L")
    axes[0].set_ylabel("P&L")

    axes[1].bar(
        names,
        comparison["maximum_absolute_inventory"],
        color=colours,
    )
    axes[1].set_title("Maximum absolute inventory")
    axes[1].set_ylabel("Shares")

    axes[2].bar(
        names,
        comparison["volume_fill_rate"] * 100,
        color=colours,
    )
    axes[2].set_title("Volume fill rate")
    axes[2].set_ylabel("Percent")

    for ax in axes:
        ax.tick_params(axis="x", rotation=25)

    fig.suptitle(
        "Quoting-Policy Trade-offs",
        fontsize=17,
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def run_project(output_directory: Path | str = "results") -> dict[str, float]:
    """Run the baseline experiment and write every project result."""

    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    config = SimulationConfig()
    simulator = MarketMakingSimulator(config)
    results = simulator.run()
    metrics = simulator.metrics(results)

    results.to_csv(output_directory / "simulation_history.csv", index=False)
    pd.DataFrame([metrics]).to_csv(
        output_directory / "summary_metrics.csv",
        index=False,
    )
    plot_dashboard(
        results,
        metrics,
        output_directory / "simulation_dashboard.png",
    )
    plot_order_book_snapshot(
        simulator.book,
        output_directory / "order_book_snapshot.png",
    )

    comparison, _ = compare_strategies(config)
    comparison.to_csv(
        output_directory / "strategy_comparison.csv",
        index=False,
    )
    plot_strategy_comparison(
        comparison,
        output_directory / "strategy_comparison.png",
    )
    return metrics


if __name__ == "__main__":
    project_results = run_project(Path(__file__).parent / "results")
    print("Baseline simulation complete")
    for metric_name, metric_value in project_results.items():
        if "rate" in metric_name:
            print(f"{metric_name:30s}: {metric_value:.2%}")
        else:
            print(f"{metric_name:30s}: {metric_value:.4f}")
