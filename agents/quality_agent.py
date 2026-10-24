import re

class QualityCheckerAgent:
    """
    Deterministic safety, compliance, and disclosure auditor.
    Prevents publication if affiliate disclosures are missing or exaggerated factual claims exist.
    """
    def check_artifact(self, content_text: str, call_to_action: str, business_model: str, disclaimer: str) -> dict:
        issues = []
        score = 100.0

        # 1. Disclosure requirement for affiliate model
        if business_model.lower() == "affiliate":
            has_disclosure = any(k in (content_text + disclaimer).lower() for k in ["affiliate", "commission", "sponsored", "partner"])
            if not has_disclosure:
                issues.append("Missing mandatory affiliate commission disclosure.")
                score -= 30.0

        # 2. Unrealistic profit / earnings claims check
        exaggerated_patterns = [
            r"guarantee.*profit",
            r"get rich",
            r"100% risk free returns",
            r"make \$[0-9]+ (in minutes|instantly)"
        ]
        for pat in exaggerated_patterns:
            if re.search(pat, content_text, re.IGNORECASE):
                issues.append(f"Potentially deceptive claim detected: matches '{pat}'")
                score -= 25.0

        # 3. Minimum Content substance
        if len(content_text.strip()) < 30:
            issues.append("Content draft is too short to provide genuine consumer value.")
            score -= 20.0

        # 4. Actionable CTA
        if not call_to_action or len(call_to_action.strip()) < 4:
            issues.append("Call to action is empty or insufficiently clear.")
            score -= 15.0

        passed = score >= 70.0 and len(issues) == 0

        return {
            "passed": passed,
            "score": max(0.0, score),
            "issues": issues,
            "recommendation": "Ready for test storefront deployment" if passed else "Revisions required before public test",
            "provenance": "QualityCheckerAgent (deterministic rule engine)",
            "checks_evaluated": [
                "mandatory_affiliate_disclosure",
                "prohibited_deceptive_claims",
                "minimum_substance_threshold",
                "actionable_call_to_action"
            ]
        }
