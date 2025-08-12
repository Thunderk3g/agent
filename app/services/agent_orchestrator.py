from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.ollama_service import ollama_service
from app.services.quote_calculator import QuoteCalculator
from app.services.payment_service import payment_service, PaymentRequest, PaymentMethod
from app.models.session import SessionData, SessionState, session_manager
from app.utils.logging import logger


MASTER_SYSTEM_PROMPT = (
    """
ROLE: You are an intelligent insurance assistant for Bajaj Allianz Life eTouch II. You're a skilled insurance agent who is conversational, helpful, and naturally adapts to the user's needs.

CORE BEHAVIOR:
1. **CONVERSATION FLOW AWARENESS**: 
   - Detect user intent: Information seeking vs. Purchase intent vs. Casual conversation
   - For generic questions (like "what is term insurance?", "who am I?", "how are you?"), respond naturally WITHOUT forcing data collection
   - Only begin onboarding when user shows clear purchase intent (e.g., "I want to buy", "I need insurance", "get me a quote")
   
2. **NATURAL CONVERSATION**:
   - Handle greetings, questions, and casual chat naturally
   - Provide helpful information about term insurance when asked
   - Don't force data collection unless user wants to proceed with a purchase
   - Use conversation context to determine appropriate response style

3. **SMART DATA COLLECTION** (only when purchase intent is clear):
   - Extract data from user messages when relevant
   - Never re-ask for information already provided
   - Ask follow-up questions naturally, not like a form

RESPONSE TYPES:
- **INFORMATIONAL**: For general questions about insurance, explain concepts naturally. Set "mode": "informational"
- **CONVERSATIONAL**: For greetings, casual chat. Set "mode": "conversational"  
- **ONBOARDING**: For purchase-focused interactions. Set "mode": "onboarding"

EXTRACTABLE FIELDS (only when relevant):
- full_name, date_of_birth (YYYY-MM-DD), age, gender, occupation, smoker (true/false), mobile_number, email, pin_code,
  coverage_amount (integer rupees), policy_term (years int), premium_frequency, riders_interest (list of strings)

RESPONSE SCHEMA (JSON only):
{
  "mode": "informational" | "conversational" | "onboarding",
  "reply": "<natural, context-appropriate response>",
  "next_question": "<optional: only if in onboarding mode and need specific info>",
  "extracted": {
    "full_name": string | null,
    "date_of_birth": string | null,
    "age": int | null,
    "gender": "male" | "female" | "other" | null,
    "occupation": string | null,
    "smoker": bool | null,
    "mobile_number": string | null,
    "email": string | null,
    "pin_code": string | null,
    "coverage_amount": int | null,
    "policy_term": int | null,
    "premium_frequency": "yearly" | "half_yearly" | "quarterly" | "monthly" | null,
    "riders_interest": [string] | null
  },
  "store_update": {
    "personalDetails": {
      "fullName": string?,
      "dateOfBirth": string?,
      "age": int?,
      "gender": string?,
      "mobileNumber": string?,
      "email": string?,
      "pinCode": string?,
      "tobaccoUser": bool?
    },
    "quoteDetails": {
      "sumAssured": int?,
      "policyTerm_years": int?,
      "premiumPayingTerm_years": int?,
      "frequency": string?
    }
  },
  "api_calls": [
    {
      "name": "premium_calculation" | "eligibility_check" | "plan_comparison" | "policy_documents",
      "params": { "key": "value" }
    }
  ],
  "reasoning": "<brief rationale for chosen mode and response>",
  "done": false
}

EXAMPLES:
- User: "What is term insurance?" → Mode: "informational", explain term insurance naturally
- User: "Hi, how are you?" → Mode: "conversational", respond warmly
- User: "I want to buy term insurance" → Mode: "onboarding", start data collection
- User: "Who am I?" → Mode: "conversational", check if you know them from context, else chat naturally
"""
)


class AgentOrchestrator:
    def __init__(self) -> None:
        self.quote_calculator = QuoteCalculator()

    async def handle_turn(
        self,
        session_id: Optional[str],
        user_message: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Process a single conversational turn fully via LLM-first orchestration.

        - Ensures a session
        - Prompts LLM for extraction + api decisions
        - Executes requested backend APIs
        - Returns final user-facing reply and updated session id
        - Persists full turn to data.json
        """

        session: SessionData
        if session_id:
            session = session_manager.get_session(session_id)  # type: ignore
            if not session:
                # Create session with the provided session_id to maintain consistency
                session = session_manager.create_session(session_id)  # type: ignore
        else:
            session = session_manager.create_session()  # type: ignore

        # 1) Ask LLM for extraction + decisions
        llm_json = await self._ask_llm_decide(session, user_message)

        # Only extract data and check transitions in onboarding mode
        conversation_mode = llm_json.get("mode", "conversational")
        if conversation_mode == "onboarding":
            # Merge extracted into session store for memory
            self._apply_extracted(session, llm_json.get("extracted") or {})
            # Check for state transitions based on form completion
            self._check_state_transitions(session, llm_json.get("extracted", {}))
        
        # 2) Execute decided API calls
        api_results: List[Dict[str, Any]] = []
        for call in llm_json.get("api_calls", []) or []:
            name = call.get("name")
            params = call.get("params") or {}
            try:
                result = await self._execute_api(name, params)
                api_results.append({"name": name, "params": params, "result": result, "success": True})
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception(f"API call failed: {name}")
                api_results.append({"name": name, "params": params, "error": str(exc), "success": False})

        # 3) Compose final answer via LLM with results
        final_reply = await self._compose_final_reply(session, user_message, llm_json, api_results)

        # 4) Update session with store mapping for frontend and persist conversation
        store_update = llm_json.get("store_update", {})
        if conversation_mode == "onboarding" and store_update:
            # Update session with frontend data structure only in onboarding mode
            session.update_frontend_data(store_update)
        
        # Add conversation turn to session history
        session.add_conversation_turn(
            user_message=user_message,
            bot_response=final_reply,
            actions_taken=[call.get("name") for call in llm_json.get("api_calls", [])],
            data_collected=llm_json.get("extracted", {})
        )
        
        # Update session in manager
        session_manager.update_session(session)
        
        # 5) Persist turn
        # Persist both conversation and store update mapping
        await self._persist_turn(
            session.session_id,
            user_message,
            llm_json,
            api_results,
            final_reply,
            store_update,
        )

        return {
            "session_id": session.session_id,
            "message": final_reply,
            "actions": [],
            "current_state": conversation_mode,  # Use the detected conversation mode
            "data_collection": {
                "collected": list(session.customer_data.keys()) if conversation_mode == "onboarding" else [],
                "missing": [],
                "completion_percentage": 0
            },
            "metadata": {
                "mode": conversation_mode,
                "extracted": llm_json.get("extracted") if conversation_mode == "onboarding" else {},
                "store_update": llm_json.get("store_update") if conversation_mode == "onboarding" else {}
            }
        }

    async def _ask_llm_decide(self, session: SessionData, user_message: str) -> Dict[str, Any]:
        # Build comprehensive context with conversation history and extracted data
        conversation_context = []
        recent_turns = getattr(session, 'conversation_history', [])[-5:]  # Last 5 turns
        for turn in recent_turns:
            if hasattr(turn, 'user_message') and hasattr(turn, 'bot_response'):
                conversation_context.append({
                    "user": turn.user_message,
                    "agent": turn.bot_response
                })
        
        prompt = (
            f"Current user message: \"{user_message}\"\n\n"
            f"CONTEXT - ALREADY KNOWN DATA: {json.dumps(session.customer_data, ensure_ascii=False)}\n\n"
            f"CONVERSATION HISTORY: {json.dumps(conversation_context, ensure_ascii=False)}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. **DETECT INTENT**: Is this informational, conversational, or purchase-focused?\n"
            f"2. **BE NATURAL**: Don't force data collection for casual questions\n"
            f"3. **USE CONTEXT**: Reference known data appropriately\n"
            f"4. **CHOOSE MODE**: informational/conversational/onboarding based on user intent\n\n"
            f"Return JSON response following the schema in your system prompt."
        )
        logger.info(f"[Agent] Asking LLM for decisions | session={session.session_id}")
        raw = await ollama_service.generate_response(prompt, MASTER_SYSTEM_PROMPT)
        logger.info(f"[Agent] LLM raw: {raw[:200]}...")
        parsed = self._safe_parse_json(raw)
        if parsed is None:
            logger.warning("LLM returned non-JSON. Falling back to minimal structure.")
            return {
                "mode": "conversational",
                "reply": raw, 
                "next_question": None, 
                "extracted": {}, 
                "api_calls": [], 
                "reasoning": "parse_fail", 
                "done": False
            }
        return parsed

    def _apply_extracted(self, session: SessionData, extracted: Dict[str, Any]) -> None:
        if not extracted:
            return
        normalized: Dict[str, Any] = {}
        # Normalize date and age
        dob = extracted.get("date_of_birth")
        if dob:
            try:
                # Accept dd/mm/yyyy or dd Mon yyyy or yyyy-mm-dd
                from datetime import datetime
                dt = None
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y"):
                    try:
                        dt = datetime.strptime(dob, fmt)
                        break
                    except Exception:
                        continue
                if dt:
                    normalized["date_of_birth"] = dt.strftime("%Y-%m-%d")
                    # derive age
                    today = datetime.utcnow().date()
                    age = today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
                    normalized["age"] = age
            except Exception:
                pass
        # Simple direct mappings
        for key in [
            "full_name","age","gender","occupation","smoker","mobile_number","email","pin_code",
            "coverage_amount","policy_term","premium_frequency","riders_interest"
        ]:
            if extracted.get(key) is not None:
                normalized[key] = extracted.get(key)
        if normalized:
            session.update_customer_data(normalized)

    def _safe_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(text)
        except Exception:
            pass
        # Strip code fences
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]  # drop 'json'
        # Extract first {...} block
        try:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                snippet = cleaned[start:end+1]
                return json.loads(snippet)
        except Exception:
            return None
        return None

    async def _compose_final_reply(
        self,
        session: SessionData,
        user_message: str,
        llm_json: Dict[str, Any],
        api_results: List[Dict[str, Any]],
    ) -> str:
        followup_context = {
            "extracted": llm_json.get("extracted"),
            "api_results": api_results,
            "guidance": {
                "one_question": True,
                "tone": "friendly, professional, concise",
            },
        }

        prompt = (
            "Summarize results for the user in plain language, then ask exactly ONE relevant next question."
        )
        logger.info("[Agent] Composing final reply via LLM")
        reply = await ollama_service.generate_response(prompt, MASTER_SYSTEM_PROMPT, followup_context)
        return reply

    def _check_state_transitions(self, session: SessionData, extracted_data: Dict[str, Any]):
        """Check if session should transition to next state based on data completeness."""
        current_state = session.current_state
        
        # Define required fields for each state transition
        state_requirements = {
            SessionState.ONBOARDING: ["full_name", "age", "gender", "mobile_number", "email"],
            SessionState.ELIGIBILITY_CHECK: ["pin_code", "smoker"],
            SessionState.PRODUCT_SELECTION: ["coverage_amount", "policy_term"],
            SessionState.QUOTE_GENERATION: ["premium_frequency"],
            SessionState.ADDON_RIDERS: [],  # Optional state
            SessionState.PAYMENT_INITIATED: ["payment_method"],
        }
        
        required_fields = state_requirements.get(current_state, [])
        if not required_fields:
            return
        
        # Check if all required fields are present
        completion_percentage = session.get_completion_percentage(required_fields)
        
        # Update form completion tracking
        form_type_map = {
            SessionState.ONBOARDING: "personal_details",
            SessionState.ELIGIBILITY_CHECK: "personal_details", 
            SessionState.PRODUCT_SELECTION: "insurance_requirements",
            SessionState.QUOTE_GENERATION: "insurance_requirements",
            SessionState.ADDON_RIDERS: "rider_selection",
            SessionState.PAYMENT_INITIATED: "payment_details"
        }
        
        form_type = form_type_map.get(current_state)
        if form_type:
            session.update_form_completion(form_type, {
                "completion_percentage": completion_percentage,
                "completed": completion_percentage >= 80
            })
        
        # Auto-transition if requirements are met
        if completion_percentage >= 80:
            next_state_map = {
                SessionState.ONBOARDING: SessionState.ELIGIBILITY_CHECK,
                SessionState.ELIGIBILITY_CHECK: SessionState.PRODUCT_SELECTION,
                SessionState.PRODUCT_SELECTION: SessionState.QUOTE_GENERATION,
                SessionState.QUOTE_GENERATION: SessionState.ADDON_RIDERS,
                SessionState.ADDON_RIDERS: SessionState.PAYMENT_INITIATED
            }
            
            next_state = next_state_map.get(current_state)
            if next_state and session.can_transition_to(next_state):
                session.transition_state(next_state, {
                    "trigger": "auto_transition",
                    "completion_percentage": completion_percentage,
                    "extracted_fields": list(extracted_data.keys())
                })
                logger.info(f"Session {session.session_id} transitioned from {current_state} to {next_state}")

    async def _execute_api(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if name == "payment_initiation":
            # Handle payment initiation
            session_id = params.get("session_id")
            amount = float(params.get("amount", 0))
            payment_method = PaymentMethod(params.get("payment_method", "credit_card"))
            
            payment_request = PaymentRequest(
                session_id=session_id,
                amount=amount,
                payment_method=payment_method,
                customer_details=params.get("customer_details", {}),
                policy_details=params.get("policy_details", {}),
                return_url=params.get("return_url", "http://localhost:3000/payment/callback")
            )
            
            payment_response = await payment_service.initiate_payment(payment_request)
            return {
                "payment_id": payment_response.payment_id,
                "payment_url": payment_response.payment_url,
                "transaction_id": payment_response.transaction_id,
                "status": payment_response.status.value
            }
        elif name == "premium_calculation":
            # Minimal bridge to existing calculator
            age = int(params.get("age", 30))
            coverage = int(params.get("coverage_amount", 5000000))
            gender = params.get("gender", "male")
            smoker = bool(params.get("smoker", False))
            term = int(params.get("policy_term", 20))
            # Reuse configured calculator by synthesizing a small profile
            profile = {
                "gender": gender,
                "tobacco_user": smoker,
                "sum_assured": coverage,
                "payment_frequency": "yearly",
            }
            quotes = self.quote_calculator.generate_quotes(
                customer_age=age,
                sum_assured=coverage,
                policy_term=term,
                premium_paying_term=term,
                customer_profile=profile,
            )
            # Return best (lowest premium) quote
            best = quotes[0] if quotes else {}
            return {"quotes": quotes, "best": best}
        elif name == "eligibility_check":
            # Placeholder eligibility logic
            age = int(params.get("age", 30))
            smoker = bool(params.get("smoker", False))
            eligible = 18 <= age <= 65
            reason = None if eligible else "Age out of range"
            return {"eligible": eligible, "reason": reason, "smoker": smoker}
        elif name == "plan_comparison":
            # Placeholder comparison result
            return {
                "plans": [
                    {"name": "Life Shield", "pros": ["Lower premium"], "cons": ["No ADB by default"]},
                    {"name": "Life Shield Plus", "pros": ["Includes ADB"], "cons": ["Slightly higher premium"]},
                ]
            }
        elif name == "policy_documents":
            return {"docs": ["Key Features Document", "Policy Wording", "Brochure"]}
        elif name == "state_transition":
            # Manual state transition
            session_id = params.get("session_id")
            target_state = params.get("target_state")
            context = params.get("context", {})
            
            session = session_manager.get_session(session_id)
            if session and hasattr(SessionState, target_state.upper()):
                new_state = SessionState(target_state)
                if session.can_transition_to(new_state):
                    session.transition_state(new_state, context)
                    session_manager.update_session(session)
                    return {"success": True, "new_state": new_state.value}
                else:
                    return {"success": False, "error": f"Cannot transition from {session.current_state} to {new_state}"}
            return {"success": False, "error": "Invalid session or state"}
        else:
            raise ValueError(f"Unknown API: {name}")

    async def _persist_turn(
        self,
        session_id: str,
        user_message: str,
        llm_json: Dict[str, Any],
        api_results: List[Dict[str, Any]],
        final_reply: str,
        store_update: Dict[str, Any],
    ) -> None:
        """Append conversation turn to data.json persistently."""
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": session_id,
            "user_message": user_message,
            "llm_decision": llm_json,
            "api_results": api_results,
            "final_reply": final_reply,
            "store_update": store_update,  # Include frontend data mapping
        }

        path = "data.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"conversations": []}

        data.setdefault("conversations", []).append(record)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


agent_orchestrator = AgentOrchestrator()


