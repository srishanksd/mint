class StrategyAgent:
    """
    Deterministic scoring and strategy selection service for MINT.
    Evaluates candidate venture hypotheses against configurable budget thresholds,
    competition levels, and past experiment outcomes.
    
    All decisions are strictly derived from input parameters without LLM hallucination.
    """
    DEFAULT_CONFIG = {
        "storefront_low_budget_penalty": 15.0,
        "storefront_budget_threshold": 30.0,
        "high_competition_penalty": 8.0,
        "high_competition_budget_threshold": 50.0,
        "past_stop_penalty": 20.0,
        "past_change_penalty": 5.0,
    }

    def __init__(self, scoring_config: dict = None):
        self.config = dict(self.DEFAULT_CONFIG)
        if scoring_config:
            self.config.update(scoring_config)

    def select_strategy(self, candidates: list, budget: float, previous_outcomes: list = None,
                        scoring_config: dict = None) -> dict:
        if not candidates:
            return {
                "candidate": None,
                "selected_candidate": None,
                "reason": "No candidate opportunities provided.",
                "explanation": "No candidate opportunities provided."
            }

        cfg = dict(self.config)
        if scoring_config:
            cfg.update(scoring_config)

        # Analyze past experiment outcomes if available
        model_penalties = {}
        penalty_reasons = {}
        if previous_outcomes:
            for past in previous_outcomes:
                action = str(past.get("recommended_action", "")).lower()
                model = str(past.get("business_model", "")).lower()
                if not model:
                    continue
                if action == "stop":
                    pen = cfg["past_stop_penalty"]
                    model_penalties[model] = model_penalties.get(model, 0.0) + pen
                    penalty_reasons[model] = f"-{pen:.0f} pts from past experiment STOP recommendation"
                elif action in ("change_offer", "change_content_or_audience"):
                    pen = cfg["past_change_penalty"]
                    model_penalties[model] = model_penalties.get(model, 0.0) + pen
                    penalty_reasons[model] = f"-{pen:.0f} pts from past experiment iteration recommendation"

        best_candidate = None
        best_score = -9999.0
        best_breakdown = {}

        for cand in candidates:
            base_score = float(cand.get("demand_score", 70))
            model = str(cand.get("business_model", "digital_product")).lower()
            comp = str(cand.get("competition_level", "Medium"))

            adjustments = []
            net_score = base_score

            # 1. Budget sensitivity rule for storefront advertising
            if budget < cfg["storefront_budget_threshold"] and model == "storefront":
                pen = cfg["storefront_low_budget_penalty"]
                net_score -= pen
                adjustments.append(f"Storefront low budget penalty (-{pen:.0f} pts, budget ${budget:.2f} < ${cfg['storefront_budget_threshold']:.2f})")

            # 2. High competition penalty when operating under constrained budget
            if comp.lower() == "high" and budget < cfg["high_competition_budget_threshold"]:
                pen = cfg["high_competition_penalty"]
                net_score -= pen
                adjustments.append(f"High competition budget penalty (-{pen:.0f} pts, budget ${budget:.2f} < ${cfg['high_competition_budget_threshold']:.2f})")

            # 3. Historical performance feedback penalty
            if model in model_penalties:
                pen = model_penalties[model]
                net_score -= pen
                adjustments.append(f"Historical outcome penalty ({penalty_reasons.get(model, f'-{pen:.0f} pts')})")

            breakdown = {
                "base_demand_score": base_score,
                "adjustments": adjustments,
                "net_score": round(net_score, 2),
                "business_model": model,
                "competition_level": comp
            }

            if net_score > best_score:
                best_score = net_score
                best_candidate = cand
                best_breakdown = breakdown

        # Determine target audience dynamically from real input attributes
        target_audience = cand.get("target_audience") or cand.get("audience")
        if not target_audience:
            niche = best_candidate.get("niche", "").strip()
            title = best_candidate.get("title", "").strip()
            if niche:
                target_audience = f"Target practitioners & consumers in {niche}"
            else:
                target_audience = f"Target operators & consumers for {title}"

        # Construct factual explanation from real inputs
        adj_text = "; ".join(best_breakdown.get("adjustments", []))
        if not adj_text:
            adj_text = "No budget or historical penalties applied."

        explanation = (
            f"Selected '{best_candidate['title']}' ({best_candidate['business_model']}) with net score {best_score:.1f} "
            f"(base demand: {best_breakdown['base_demand_score']}, budget limit: ${budget:.2f}). "
            f"Scoring breakdown: {adj_text}"
        )

        return {
            "candidate": best_candidate,
            "target_audience": target_audience,
            "explanation": explanation,
            "scoring_breakdown": best_breakdown,
            "provenance": "StrategyAgent (deterministic configurable scoring engine)"
        }
