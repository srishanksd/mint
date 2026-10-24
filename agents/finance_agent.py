class FinanceAgent:
    """
    Deterministic financial engine.
    Calculates gross revenue, processing fees, refunds, actual cash spend vs compute estimates,
    net profit, and partitions funds into compulsory reserve, reinvestment, and portfolio surplus.

    Strictly separates verified real commerce transactions from sandbox/test purchases:
    Sandbox test orders NEVER inflate real business gross revenue, net profit, compulsory reserves,
    or portfolio surplus allocations.
    """
    def __init__(self, reserve_ratio: float = 0.25, reinvestment_ratio: float = 0.40):
        # 25% of net profit held in cash reserve, 40% allocated for next business iteration
        self.reserve_ratio = reserve_ratio
        self.reinvestment_ratio = reinvestment_ratio

    def calculate_statement(self, starting_budget: float, actual_spend: float, orders: list, compute_estimates: float = 0.0) -> dict:
        """
        Orders list schema:
          [{'gross_amount': float, 'fee_amount': float, 'is_refunded': bool, 'refund_amount': float, 'is_test': bool}]
        actual_spend: cash expenses incurred.
        compute_estimates: non-cash operational compute estimates.
        """
        # Separate real transactions from sandbox/test orders
        real_orders = [o for o in orders if not o.get("is_test", False)]
        test_orders = [o for o in orders if o.get("is_test", False)]

        # --- Real Ledger (Official Business Financials) ---
        gross_revenue = 0.0
        total_fees = 0.0
        total_refunds = 0.0

        for order in real_orders:
            gross_revenue += float(order.get("gross_amount", 0.0))
            total_fees += float(order.get("fee_amount", 0.0))
            if order.get("is_refunded", False):
                total_refunds += float(order.get("refund_amount", order.get("gross_amount", 0.0)))

        # Net Realized Cash Flow from Sales = Gross - Fees - Refunds
        net_sales = gross_revenue - total_fees - total_refunds
        # Net Cash Profit = Net Sales - Actual Cash Spend
        net_profit = net_sales - actual_spend

        # Partitioning rules (Applied strictly only if cash profit > 0)
        if net_profit > 0:
            required_reserve = round(net_profit * self.reserve_ratio, 2)
            reinvestment_allocated = round(net_profit * self.reinvestment_ratio, 2)
            surplus_available = round(net_profit - required_reserve - reinvestment_allocated, 2)
        else:
            required_reserve = 0.0
            reinvestment_allocated = 0.0
            surplus_available = 0.0

        # --- Sandbox Test Summary (Tracked separately, never enters business balance) ---
        test_gross = 0.0
        test_fees = 0.0
        test_refunds = 0.0
        for t in test_orders:
            test_gross += float(t.get("gross_amount", 0.0))
            test_fees += float(t.get("fee_amount", 0.0))
            if t.get("is_refunded", False):
                test_refunds += float(t.get("refund_amount", t.get("gross_amount", 0.0)))

        return {
            "starting_budget": round(starting_budget, 2),
            "actual_spend": round(actual_spend, 2),
            "compute_estimates": round(compute_estimates, 2),
            "gross_revenue": round(gross_revenue, 2),
            "fees": round(total_fees, 2),
            "refunds": round(total_refunds, 2),
            "net_sales": round(net_sales, 2),
            "net_profit": round(net_profit, 2),
            "required_reserve": required_reserve,
            "reinvestment_allocated": reinvestment_allocated,
            "surplus_available": surplus_available,
            "is_simulated": len(real_orders) == 0,
            "real_orders_count": len(real_orders),
            "provenance": "FinanceAgent (deterministic ledger accounting)",
            "sandbox_summary": {
                "test_orders_count": len(test_orders),
                "test_gross": round(test_gross, 2),
                "test_fees": round(test_fees, 2),
                "test_refunds": round(test_refunds, 2),
                "test_net": round(test_gross - test_fees - test_refunds, 2)
            }
        }
