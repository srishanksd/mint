class PortfolioManager:
    """
    Simulated Investment Portfolio Allocation Engine.
    Partitions available surplus across defined asset classes based on user risk profiles.
    Guarantees sum(percentage) == 100% and exact monetary reconciliation.
    """
    PROFILES = {
        "conservative": [
            {"asset_class": "Short-Term Treasury Bills / Money Market", "ticker": "BIL", "pct": 50.0, "reason": "Capital preservation & liquid risk-free yield"},
            {"asset_class": "Broad Aggregate Bond Index", "ticker": "BND", "pct": 30.0, "reason": "Stable fixed-income ballast"},
            {"asset_class": "Total Global Equity Index", "ticker": "VT", "pct": 20.0, "reason": "Defensive equity exposure"}
        ],
        "balanced": [
            {"asset_class": "Core US Total Market Index", "ticker": "VTI", "pct": 45.0, "reason": "Long-term economic productivity capture"},
            {"asset_class": "Developed & Emerging Markets", "ticker": "VXUS", "pct": 20.0, "reason": "Global geographic diversification"},
            {"asset_class": "Intermediate High-Grade Bonds", "ticker": "BND", "pct": 25.0, "reason": "Downside shock mitigation"},
            {"asset_class": "Liquid Cash Equivalents", "ticker": "SHV", "pct": 10.0, "reason": "Tactical liquidity buffer"}
        ],
        "growth": [
            {"asset_class": "High-Efficiency Index ETF (S&P 500)", "ticker": "VOO", "pct": 55.0, "reason": "Leading enterprise compound growth"},
            {"asset_class": "Tech & Innovation Thematic ETF", "ticker": "QQQM", "pct": 25.0, "reason": "High secular growth multiplier"},
            {"asset_class": "Small-Cap Value Equity", "ticker": "AVUV", "pct": 15.0, "reason": "Factor premium exploration"},
            {"asset_class": "Digital Store of Value (Simulated BTC)", "ticker": "IBIT", "pct": 5.0, "reason": "Asymmetric macro hedge"}
        ]
    }

    def allocate(self, surplus_amount: float, risk_profile: str = "balanced", time_horizon: str = "medium") -> dict:
        profile_key = risk_profile.lower() if risk_profile.lower() in self.PROFILES else "balanced"
        specs = self.PROFILES[profile_key]

        allocated_items = []
        running_total = 0.0

        for i, item in enumerate(specs):
            if i == len(specs) - 1:
                # Assign exact residual to prevent rounding discrepancies
                item_amount = round(surplus_amount - running_total, 2)
            else:
                item_amount = round(surplus_amount * (item["pct"] / 100.0), 2)
                running_total += item_amount

            allocated_items.append({
                "asset_class": item["asset_class"],
                "ticker": item["ticker"],
                "percentage": item["pct"],
                "amount": max(0.0, item_amount),
                "reason": item["reason"]
            })

        total_pct = sum(item["percentage"] for item in allocated_items)

        return {
            "risk_profile": profile_key.capitalize(),
            "time_horizon": time_horizon,
            "total_surplus_allocated": round(surplus_amount, 2),
            "allocations": allocated_items,
            "total_percentage": round(total_pct, 1),
            "rebalancing_recommendation": f"Demonstration portfolio initialized for {profile_key} profile. Paper allocation verified.",
            "is_simulated": True,
            "provenance": "PortfolioManager (deterministic paper allocation engine)",
            "disclaimer": "Simulated demonstration portfolio. Does not constitute personal financial or investment advice."
        }
