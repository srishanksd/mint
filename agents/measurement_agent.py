class MeasurementAgent:
    """
    Evaluates venture test funnel and generates data-driven strategic iteration recommendations.
    Uses strictly logged observations (views, clicks, orders, refunds, costs).
    Never fabricates metrics. If data is limited or absent, explicitly flags data as insufficient.
    """
    def evaluate_performance(self, views: int, clicks: int, orders_count: int, net_profit: float, budget: float, data_source: str = "verified_local_logs") -> dict:
        ctr = round((clicks / views * 100.0), 2) if views > 0 else 0.0
        conversion_rate = round((orders_count / clicks * 100.0), 2) if clicks > 0 else 0.0

        decision = "continue"
        explanation = ""

        # Check for zero or insufficient observation data
        if views == 0 and clicks == 0 and orders_count == 0:
            decision = "awaiting_traffic"
            explanation = "No traffic or test interactions recorded yet. Awaiting distribution or simulated sandbox events."
        elif views > 0 and views < 25 and orders_count == 0:
            decision = "insufficient_data"
            explanation = f"Sample size is too small ({views} views) to draw statistically valid conclusions. Gather additional traffic before changing direction."
        elif ctr < 2.0 and views >= 25:
            decision = "change_content_or_audience"
            explanation = f"Click-through rate ({ctr}%) is below 2.0% baseline. Audience exposure did not convert into landing engagement; test an alternate hook or target segment."
        elif orders_count == 0 and clicks >= 10:
            decision = "change_offer"
            explanation = f"Traffic captured ({clicks} clicks) but 0 purchases recorded. Review product pricing, landing clarity, or guarantee terms."
        elif net_profit > 0 and conversion_rate >= 2.5:
            decision = "continue"
            explanation = f"Positive unit economics: Net profit of ${net_profit:.2f} with {conversion_rate}% conversion rate. Recommend continuing or scaling approved budget."
        elif net_profit < -(budget * 0.7):
            decision = "stop"
            explanation = f"Substantial capital drawdown (-${abs(net_profit):.2f} against ${budget:.2f} budget). Recommend stopping experiment to prevent further loss."
        else:
            decision = "change_offer"
            explanation = "Moderate traction with break-even or marginal economics. Recommend offer refinement."

        return {
            "metrics": {
                "views": views,
                "clicks": clicks,
                "ctr_pct": ctr,
                "orders_count": orders_count,
                "conversion_rate_pct": conversion_rate,
                "net_profit": round(net_profit, 2),
                "data_source": data_source
            },
            "recommended_action": decision,
            "explanation": explanation,
            "is_insufficient_sample": (views < 25 and orders_count == 0 and views > 0),
            "provenance": "MeasurementAgent (deterministic funnel analytics)"
        }
