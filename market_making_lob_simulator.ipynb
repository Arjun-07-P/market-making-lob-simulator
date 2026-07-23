"""Unit tests for price-time priority and simulator accounting."""

from math import isclose
import unittest

from simulator import LimitOrderBook, MarketMakingSimulator, SimulationConfig


class LimitOrderBookTests(unittest.TestCase):
    def test_better_price_matches_first_and_partial_quantity_remains(self) -> None:
        book = LimitOrderBook()
        expensive_id, _ = book.submit_limit_order(
            "seller_a",
            "sell",
            100.10,
            5,
        )
        best_id, _ = book.submit_limit_order("seller_b", "sell", 100.05, 8)

        _, trades = book.submit_market_order("buyer", "buy", 10)

        self.assertEqual(
            [(trade.price, trade.quantity) for trade in trades],
            [(100.05, 8), (100.10, 2)],
        )
        self.assertNotIn(best_id, book.order_lookup)
        self.assertEqual(book.order_lookup[expensive_id].remaining, 3)

    def test_fifo_applies_when_two_orders_have_the_same_price(self) -> None:
        book = LimitOrderBook()
        first_id, _ = book.submit_limit_order(
            "first_buyer",
            "buy",
            99.90,
            3,
        )
        second_id, _ = book.submit_limit_order(
            "second_buyer",
            "buy",
            99.90,
            3,
        )

        _, trades = book.submit_market_order("seller", "sell", 4)

        self.assertEqual(trades[0].buyer_id, "first_buyer")
        self.assertEqual(trades[0].quantity, 3)
        self.assertNotIn(first_id, book.order_lookup)
        self.assertEqual(book.order_lookup[second_id].remaining, 2)

    def test_non_crossing_limit_order_rests_and_can_be_cancelled(self) -> None:
        book = LimitOrderBook()
        book.submit_limit_order("seller", "sell", 100.10, 5)
        buy_id, trades = book.submit_limit_order("buyer", "buy", 100.00, 2)

        self.assertEqual(trades, [])
        self.assertEqual(book.best_bid, 100.00)
        self.assertEqual(book.best_ask, 100.10)
        self.assertTrue(book.cancel_order(buy_id))
        self.assertFalse(book.cancel_order(buy_id))
        self.assertIsNone(book.best_bid)

    def test_market_order_remainder_does_not_rest(self) -> None:
        book = LimitOrderBook()
        book.submit_limit_order("seller", "sell", 100.00, 2)

        market_id, trades = book.submit_market_order("buyer", "buy", 10)

        self.assertEqual(sum(trade.quantity for trade in trades), 2)
        self.assertNotIn(market_id, book.order_lookup)
        self.assertIsNone(book.best_ask)


class MarketMakingSimulatorTests(unittest.TestCase):
    def test_inventory_skew_moves_quotes_down_when_inventory_is_positive(
        self,
    ) -> None:
        config = SimulationConfig(n_steps=1, inventory_skew=0.02)
        simulator = MarketMakingSimulator(config)
        simulator._seed_background_liquidity()
        neutral_bid, neutral_ask = simulator.calculate_quotes()

        simulator.inventory = 10
        long_bid, long_ask = simulator.calculate_quotes()

        self.assertLess(long_bid, neutral_bid)
        self.assertLess(long_ask, neutral_ask)

    def test_final_wealth_obeys_cash_plus_inventory_times_price(self) -> None:
        config = SimulationConfig(n_steps=50, seed=7)
        simulator = MarketMakingSimulator(config)
        results = simulator.run()
        final = results.iloc[-1]

        self.assertTrue(
            isclose(
                final["wealth"],
                final["cash"] + final["inventory"] * final["fair_price"],
                rel_tol=1e-12,
            )
        )


if __name__ == "__main__":
    unittest.main()
