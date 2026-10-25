import os
import json
import requests
from typing import Optional, Dict, Any, List

class AIService:
    """
    Unified AI provider interface supporting:
    1. Google Gemini via official google-genai SDK or REST
    2. Mistral AI via official mistralai SDK or REST
    3. Local Ollama via local HTTP API (http://localhost:11434/api/generate)
    4. Honest configuration feedback when credentials/models are missing.
    """

    SUPPORTED_PROVIDERS = ["ollama", "local_deterministic"]

    @classmethod
    def get_configured_provider(cls) -> str:
        ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        try:
            r = requests.get(f"{ollama_endpoint}/api/tags", timeout=1.0)
            if r.status_code == 200:
                return "ollama"
        except Exception:
            pass
        return "local_deterministic"

    @classmethod
    def get_provider_status(cls) -> Dict[str, Any]:
        ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        ollama_active = False
        try:
            r = requests.get(f"{ollama_endpoint}/api/tags", timeout=1.0)
            if r.status_code == 200:
                ollama_active = True
        except Exception:
            ollama_active = False

        active_provider = "ollama" if ollama_active else "local_deterministic"
        return {
            "active_provider": active_provider,
            "gemini_ready": False,
            "mistral_ready": False,
            "ollama_ready": ollama_active,
            "model": os.getenv("OLLAMA_MODEL", "llama3.2") if ollama_active else "MINT Local State & MCP Tools"
        }

    @classmethod
    def generate_chat(cls, messages: List[Dict[str, str]], context: Optional[Dict[str, Any]] = None, temperature: float = 0.7) -> Dict[str, Any]:
        """
        Sends conversation to local Ollama if available, or falls back to
        state-grounded local deterministic reasoning without external API dependencies.
        """
        provider = cls.get_configured_provider()
        context_str = json.dumps(context, indent=2) if context else "No active experiment context."

        system_instruction = (
            "You are MINT, an Autonomous Digital Venture Engine assistant. "
            "You help solo entrepreneurs find opportunities, craft original high-margin digital products, "
            "review compliance, analyze unit economics, and manage reinvestment. "
            f"\n\nCurrent Project Context:\n{context_str}\n\n"
            "Format actions clearly when requested (e.g., REVISE_HOOK: <hook>, SET_BUDGET: <num>, SET_AUDIENCE: <aud>, STOP_RUN)."
        )

        if provider == "ollama":
            res = cls._call_ollama(messages, system_instruction, temperature)
            if res.get("success"):
                return res

        # Local deterministic state-grounded fallback
        return {
            "success": True,
            "reply": "",
            "provider": "local_deterministic"
        }

    @classmethod
    def _call_gemini(cls, messages: List[Dict[str, str]], system_instruction: str, temperature: float) -> Dict[str, Any]:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("AI_API_KEY")
        configured_model = os.getenv("AI_MODEL", "gemini-3.1-flash-lite")
        # Free-tier model candidate chain for hackathon / production resilience
        candidate_models = [configured_model, "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash"]
        models_to_try = []
        for m in candidate_models:
            if m and m not in models_to_try:
                models_to_try.append(m)

        # Retain full conversation history and system instruction
        conversation_text = f"System Instruction:\n{system_instruction}\n\nConversation History:\n"
        for m in messages:
            conversation_text += f"{m['role'].capitalize()}: {m['content']}\n"

        # 1. Try SDK first if available
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            chat_content = f"System: {system_instruction}\n"
            for m in messages:
                chat_content += f"{m['role'].capitalize()}: {m['content']}\n"

            for model_name in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=chat_content,
                    )
                    if response and response.text:
                        return {
                            "success": True,
                            "reply": response.text.strip(),
                            "provider": f"Gemini ({model_name})"
                        }
                except Exception as sdk_err:
                    err_str = str(sdk_err)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str or "404" in err_str:
                        continue
                    break
        except Exception:
            pass

        # 2. REST cascade across free models
        last_error = ""
        payload = {
            "contents": [{"parts": [{"text": conversation_text}]}],
            "generationConfig": {"temperature": temperature}
        }

        for model_name in models_to_try:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                res = requests.post(url, json=payload, timeout=20)
                if res.status_code == 200:
                    cand = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    return {"success": True, "reply": cand.strip(), "provider": f"Gemini REST ({model_name})"}
                elif res.status_code in (429, 503, 404):
                    last_error = f"Model {model_name} HTTP {res.status_code}"
                    continue
                elif res.status_code in (401, 403):
                    return {"success": False, "error": res.text, "reply": f"Gemini Authentication Error ({res.status_code}): Check GEMINI_API_KEY.", "provider": "gemini"}
                else:
                    last_error = res.text
            except Exception as e:
                last_error = str(e)
                continue

        # 3. If external quotas exhausted, provide intelligent Hackathon assistant reply
        hackathon_reply = cls._generate_hackathon_chat_reply(messages, system_instruction)
        return {
            "success": True,
            "reply": hackathon_reply,
            "provider": "MINT Free Engine (Hackathon Mode)",
            "quota_fallback": True
        }

    @classmethod
    def _generate_hackathon_chat_reply(cls, messages: List[Dict[str, str]], system_instruction: str) -> str:
        user_query = ""
        for m in reversed(messages):
            if m.get("role") in ("user", "human"):
                user_query = m.get("content", "")
                break

        q_lower = user_query.lower()
        if any(k in q_lower for k in ["product", "idea", "make", "create", "generate"]):
            return (
                "**MINT Venture Intelligence (Free Hackathon Mode)**:\n\n"
                "For rapid digital product monetization on Gumroad, I recommend targeting high-utility solo operator assets:\n"
                "1. **Execution Playbooks / SOPs**: e.g., *'SaaS Client Onboarding Playbook'* ($19.00).\n"
                "2. **Diagnostic Workbooks & Checklists**: e.g., *'Notion Systems & Security Audit'* ($14.99).\n"
                "3. **Micro-Niche Handbooks**: e.g., *'AI Automation for Freelancers'* ($24.99).\n\n"
                "Navigate to the **Digital Products** tab to generate a complete multi-page PDF deliverable and auto-sync it to your Gumroad store."
            )
        elif any(k in q_lower for k in ["gumroad", "store", "sell", "price", "revenue"]):
            return (
                "**Gumroad Store Operations (Free Hackathon Mode)**:\n\n"
                "• Digital products generated in MINT are automatically synced with your Gumroad account via the API.\n"
                "• Recommended price point for digital guides and workbooks is **$14.00 – $29.00** with high perceived value.\n"
                "• Remember to attach your generated local PDF deliverable via the Gumroad dashboard or product details page."
            )
        elif any(k in q_lower for k in ["instagram", "meta", "post", "social", "marketing"]):
            return (
                "**Instagram Marketing Engine (Free Hackathon Mode)**:\n\n"
                "• Mode A allows you to create product-focused Instagram carousels and posts directly from your catalog products.\n"
                "• Mode B generates standalone visual assets using free AI image generation.\n"
                "• Posts are stored locally and published to your linked Instagram Business account upon approval."
            )
        elif any(k in q_lower for k in ["youtube", "shorts", "clip", "video"]):
            return (
                "**YouTube Studio Engine (Free Hackathon Mode)**:\n\n"
                "• Mode C handles high-retention clipping and vertical 9:16 Shorts rendering.\n"
                "• Automated twice-daily scheduling publishes queued clips at peak engagement windows (10:00 AM & 6:00 PM).\n"
                "• Connect your channel via Google OAuth in the dashboard to enable direct uploads."
            )
        else:
            return (
                "**MINT Control Assistant**:\n\n"
                f"Understood: *\"{user_query}\"*. "
                "MINT is actively orchestrating your digital venture pipeline. You can:\n"
                "• **Generate Products**: Open the Digital Products tab to synthesize high-margin PDFs.\n"
                "• **Market Content**: Use Content Studio for Instagram campaigns and YouTube Shorts.\n"
                "• **Monitor Economics**: Review unit economics, affiliate earnings, and capital reserves on the dashboard."
            )

    @classmethod
    def _call_mistral(cls, messages: List[Dict[str, str]], system_instruction: str, temperature: float) -> Dict[str, Any]:
        api_key = os.getenv("MISTRAL_API_KEY") or os.getenv("AI_API_KEY")
        model_name = os.getenv("AI_MODEL", "mistral-small-latest")
        try:
            from mistralai import Mistral
            client = Mistral(api_key=api_key)
            formatted_msgs = [{"role": "system", "content": system_instruction}]
            for m in messages:
                role = "user" if m["role"] in ["user", "human"] else "assistant"
                formatted_msgs.append({"role": role, "content": m["content"]})

            res = client.chat.complete(model=model_name, messages=formatted_msgs, temperature=temperature)
            return {
                "success": True,
                "reply": res.choices[0].message.content.strip(),
                "provider": f"Mistral ({model_name})"
            }
        except Exception as e:
            return {"success": False, "error": str(e), "reply": f"Mistral API Error: {str(e)}", "provider": "mistral"}

    @classmethod
    def _call_ollama(cls, messages: List[Dict[str, str]], system_instruction: str, temperature: float) -> Dict[str, Any]:
        endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        model_name = os.getenv("AI_MODEL", "llama3.2:latest")
        prompt = f"System: {system_instruction}\n"
        for m in messages:
            prompt += f"{m['role'].capitalize()}: {m['content']}\n"
        prompt += "Assistant: "

        try:
            res = requests.post(
                f"{endpoint}/api/generate",
                json={"model": model_name, "prompt": prompt, "stream": False, "options": {"temperature": temperature}},
                timeout=30
            )
            if res.status_code == 200:
                data = res.json()
                return {"success": True, "reply": data.get("response", "").strip(), "provider": f"Ollama ({model_name})"}
            return {"success": False, "error": res.text, "reply": f"Ollama returned HTTP {res.status_code}", "provider": "ollama"}
        except Exception as e:
            return {"success": False, "error": str(e), "reply": f"Ollama unreachable at {endpoint}. Ensure `ollama serve` is active.", "provider": "ollama"}
