import random
import json
from datetime import datetime
from services.ai_service import AIService

class OpportunityScout:
    """
    Curates and synthesizes initial digital venture hypotheses for MINT.
    
    Principles:
    - Never claims to have conducted live market scraping, empirical traffic measurement, or verified sales.
    - AI-generated opportunities are explicitly labelled as unverified hypotheses.
    - Curated offline fixtures are explicitly labelled as simulated baseline fixtures.
    - Demand scores are heuristic prioritization weights, not empirical market verification.
    """
    CURATED_SEED_OPPORTUNITIES = [
        {
            "title": "Minimalist Notion Productivity System for Solo Founders",
            "niche": "Digital Tools / Productivity",
            "business_model": "digital_product",
            "evidence": "Curated benchmark fixture based on solopreneur workflow pattern (simulated; not live market research).",
            "demand_score": 88,
            "competition_level": "Medium",
            "source_type": "curated_market_fixture",
            "source_ref": "Internal Seed Repository: solopreneur_tools_v1",
            "confidence": "baseline_unverified",
            "is_verified": 0,
            "is_simulated": 1
        },
        {
            "title": "Ergonomic Desk Setup & Micro-Break Timer Kit",
            "niche": "Remote Work Lifestyle",
            "business_model": "affiliate",
            "evidence": "Curated benchmark fixture representing remote desk ergonomics (simulated; not live market research).",
            "demand_score": 92,
            "competition_level": "High",
            "source_type": "curated_market_fixture",
            "source_ref": "Internal Seed Repository: remote_work_affiliate_v1",
            "confidence": "baseline_unverified",
            "is_verified": 0,
            "is_simulated": 1
        },
        {
            "title": "AI Workflow Automation Cheatsheet for Local Businesses",
            "niche": "B2B SMB Technology",
            "business_model": "digital_product",
            "evidence": "Curated benchmark fixture representing non-technical automation cheatsheets (simulated; not live market research).",
            "demand_score": 84,
            "competition_level": "Low",
            "source_type": "curated_market_fixture",
            "source_ref": "Internal Seed Repository: smb_automation_cheatsheets_v1",
            "confidence": "baseline_unverified",
            "is_verified": 0,
            "is_simulated": 1
        },
        {
            "title": "High-Protein 15-Minute Meal Prep Quick Guide",
            "niche": "Health & Nutrition",
            "business_model": "storefront",
            "evidence": "Curated benchmark fixture representing nutrition prep guide (simulated; not live market research).",
            "demand_score": 79,
            "competition_level": "High",
            "source_type": "curated_market_fixture",
            "source_ref": "Internal Seed Repository: nutrition_quick_guides_v1",
            "confidence": "baseline_unverified",
            "is_verified": 0,
            "is_simulated": 1
        }
    ]

    def scout(self, goal: str = "", target_niche: str = "") -> list:
        # Check if AI provider is available
        status = AIService.get_provider_status()
        provider = status.get("active_provider")

        if provider != "unconfigured":
            prompt = (
                f"You are Opportunity Scout for MINT Venture Engine. "
                f"Propose 3 unverified digital venture hypotheses for this goal: '{goal}'. "
                f"Important: Do not claim live web scraping, verified search volume, or live traffic data. "
                f"Clearly describe these as conceptual hypotheses with logical rationale. "
                f"Return ONLY valid JSON matching this exact structure:\n"
                f"[\n"
                f"  {{\n"
                f"    \"title\": \"Clear product title\",\n"
                f"    \"niche\": \"Specific domain/niche\",\n"
                f"    \"business_model\": \"digital_product\" or \"affiliate\" or \"storefront\",\n"
                f"    \"evidence\": \"Theoretical hypothesis rationale and consumer problem addressed (unverified)\",\n"
                f"    \"demand_score\": integer between 60 and 95,\n"
                f"    \"competition_level\": \"Low\" or \"Medium\" or \"High\"\n"
                f"  }}\n"
                f"]"
            )
            res = AIService.generate_chat([{"role": "user", "content": prompt}])
            if res.get("success") and res.get("reply"):
                try:
                    text = res["reply"].strip()
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.endswith("```"):
                        text = text[:-3]
                    parsed = json.loads(text.strip())
                    if isinstance(parsed, list) and len(parsed) >= 1:
                        for item in parsed:
                            item["source_type"] = f"unverified_hypothesis_{provider}"
                            item["source_ref"] = f"{provider}:{status.get('model', 'default')}"
                            item["confidence"] = "unverified_ai_hypothesis"
                            item["is_verified"] = 0
                            item["is_simulated"] = 1
                        return parsed[:3]
                except Exception:
                    pass # Fall back to curated baseline fixtures if AI formatting fails

        # Fallback to clearly labelled simulated seed items
        items = [dict(x) for x in self.CURATED_SEED_OPPORTUNITIES]
        random.shuffle(items)
        return items[:3]
