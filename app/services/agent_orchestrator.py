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
   - When you have enough data (age, gender, coverage_amount, policy_term, smoker status), automatically generate a quote

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
- CRITICAL: If you have age, gender, coverage_amount, policy_term, and smoker status → You MUST call "premium_calculation" API
- When user provides insurance requirements, always check if you can generate a quote
- Quote generation is the primary goal once sufficient data is collected
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

        # Extract data and check transitions in onboarding mode, but also check for quote readiness always
        conversation_mode = llm_json.get("mode", "conversational")
        extracted_data = llm_json.get("extracted") or {}
        
        if conversation_mode == "onboarding" or extracted_data:
            # Merge extracted into session store for memory
            self._apply_extracted(session, extracted_data)
            # Check for state transitions based on form completion
            self._check_state_transitions(session, extracted_data)
            
        # Check if we have enough data to generate a quote automatically
        should_quote = self._should_generate_quote(session)
        has_existing_quote_call = any(call.get("name") == "premium_calculation" for call in llm_json.get("api_calls", []))
        
        logger.info(f"[Agent] Quote check - should_quote: {should_quote}, has_existing_call: {has_existing_quote_call}, customer_data: {session.customer_data}")
        
        if should_quote and not has_existing_quote_call:
            # Add premium calculation to API calls if not already requested
            if "api_calls" not in llm_json:
                llm_json["api_calls"] = []
                
            quote_params = self._get_quote_params(session)
            logger.info(f"[Agent] Adding automatic premium_calculation with params: {quote_params}")
            
            llm_json["api_calls"].append({
                "name": "premium_calculation",
                "params": quote_params
            })
        elif should_quote and has_existing_quote_call:
            logger.info(f"[Agent] Quote should be generated and LLM already requested it")
        elif not should_quote:
            logger.info(f"[Agent] Quote not eligible yet - missing data or validation failed")
        
        # 2) Execute decided API calls
        api_results: List[Dict[str, Any]] = []
        for call in llm_json.get("api_calls", []) or []:
            name = call.get("name")
            params = call.get("params") or {}
            logger.info(f"[Agent] Executing API call: {name} with params: {params}")
            try:
                result = await self._execute_api(name, params)
                logger.info(f"[Agent] API call {name} successful. Result: {result}")
                api_results.append({"name": name, "params": params, "result": result, "success": True})
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception(f"API call failed: {name} - Error: {str(exc)}")
                api_results.append({"name": name, "params": params, "error": str(exc), "success": False})

        # Store quote results in session for future reference
        quote_results = [r for r in api_results if r.get("name") == "premium_calculation" and r.get("success")]
        if quote_results:
            quote_data = quote_results[0].get("result", {})
            session.quote_data.update({
                "quotes_generated": quote_data.get("quotes", []),
                "best_quote": quote_data.get("best", {}),
                "last_generated": datetime.utcnow().isoformat()
            })
            logger.info(f"[Agent] Stored quote data in session: {len(quote_data.get('quotes', []))} quotes")

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

        # Include quote information in metadata if available
        metadata = {
            "mode": conversation_mode,
            "extracted": llm_json.get("extracted") if conversation_mode == "onboarding" else {},
            "store_update": llm_json.get("store_update") if conversation_mode == "onboarding" else {}
        }
        
        # Add quote data to metadata if quotes were generated
        if quote_results:
            quote_data = quote_results[0].get("result", {})
            metadata["quotes"] = {
                "generated": True,
                "best_quote": quote_data.get("best", {}),
                "all_quotes": quote_data.get("quotes", []),
                "quote_count": len(quote_data.get("quotes", []))
            }
            logger.info(f"[Agent] Added quote metadata to response")

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
            "metadata": metadata
        }

    async def _ask_llm_decide(self, session: SessionData, user_message: str) -> Dict[str, Any]:
        # Build comprehensive context with conversation history and extracted data
        conversation_context = []
        recent_turns = getattr(session, 'conversation_history', [])[-7:]  # Last 7 turns for better context
        for turn in recent_turns:
            if hasattr(turn, 'user_message') and hasattr(turn, 'bot_response'):
                conversation_context.append({
                    "user": turn.user_message,
                    "bot": turn.bot_response
                })
        
        # Build comprehensive context for Ollama
        context = {
            "conversation_history": conversation_context,
            "customer_data": session.customer_data,
            "session_state": session.current_state.value,
            "state_context": {
                "form_completion": session.form_completion,
                "selected_variant": session.selected_variant,
                "quote_data": session.quote_data,
                "policy_data": session.policy_data,
                "session_id": session.session_id,
                "conversation_turns": len(session.conversation_history)
            }
        }
        
        prompt = (
            f"Current user message: \"{user_message}\"\n\n"
            f"INSTRUCTIONS:\n"
            f"1. **CONTEXT AWARENESS**: Use the conversation history and customer data provided in the context\n"
            f"2. **DETECT INTENT**: Is this informational, conversational, or purchase-focused?\n"
            f"3. **BE NATURAL**: Don't force data collection for casual questions\n"
            f"4. **USE MEMORY**: Reference previously collected information when appropriate\n"
            f"5. **CHOOSE MODE**: informational/conversational/onboarding based on user intent\n"
            f"6. **AUTO-QUOTE**: If you have age, gender, coverage_amount, policy_term, and smoker status, call premium_calculation API\n\n"
            f"Current customer data: {session.customer_data}\n"
            f"Session state: {session.current_state.value}\n\n"
            f"Return JSON response following the schema in your system prompt."
        )
        
        logger.info(f"[Agent] Asking LLM for decisions | session={session.session_id} | history_turns={len(conversation_context)}")
        raw = await ollama_service.generate_response(prompt, MASTER_SYSTEM_PROMPT, context)
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

    def _is_json_string(self, text: str) -> bool:
        """Check if text appears to be JSON."""
        if not text:
            return False
        text = text.strip()
        return (text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']'))

    def _extract_reply_from_json(self, text: str) -> str:
        """Extract reply text from JSON response."""
        if not text:
            return text
            
        try:
            # If it's clearly JSON, try to parse and extract reply
            if self._is_json_string(text):
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    # Check for reply field first (most common)
                    if 'reply' in parsed and isinstance(parsed['reply'], str):
                        reply = parsed['reply']
                        # Also check for next_question and combine if present
                        if 'next_question' in parsed and isinstance(parsed['next_question'], str) and parsed['next_question'].strip():
                            return f"{reply}\n\n{parsed['next_question']}"
                        return reply
                    
                    # Try other common field names
                    for field in ['message', 'response', 'text', 'content']:
                        if field in parsed and isinstance(parsed[field], str):
                            return parsed[field]
                    
                    # If it's a complete agent response with mode/api_calls, provide fallback
                    if any(key in parsed for key in ['mode', 'extracted', 'api_calls', 'reasoning']):
                        return "I'm working on your request. Please let me know if you need any additional information."
                        
        except json.JSONDecodeError:
            pass
        
        # If parsing fails, try to clean common JSON artifacts
        cleaned = text
        
        # Remove complete JSON wrapper patterns
        json_patterns = [
            (r'^\{\s*"reply"\s*:\s*"(.+?)"\s*,.*\}$', r'\1'),
            (r'^\{\s*"reply"\s*:\s*"(.+?)"\s*\}$', r'\1'),
            (r'^\{\s*"message"\s*:\s*"(.+?)"\s*,.*\}$', r'\1'),
            (r'^\{\s*"message"\s*:\s*"(.+?)"\s*\}$', r'\1'),
        ]
        
        import re
        for pattern, replacement in json_patterns:
            match = re.match(pattern, cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1)
                break
        
        # Basic cleanup
        cleaned = cleaned.replace('\\"', '"')  # Unescape quotes
        cleaned = cleaned.replace('\\n', '\n')  # Unescape newlines
        cleaned = cleaned.strip()
        
        # Remove outer quotes if the entire string is wrapped
        if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) > 2:
            cleaned = cleaned[1:-1]
            
        return cleaned if cleaned != text and len(cleaned) > 0 else text

    def _should_generate_quote(self, session: SessionData) -> bool:
        """Check if we have enough data to generate a quote."""
        required_fields = ["age", "gender", "coverage_amount", "policy_term", "smoker"]
        customer_data = session.customer_data
        
        logger.info(f"[Agent] Checking quote eligibility for session {session.session_id}")
        logger.info(f"[Agent] Required fields: {required_fields}")
        logger.info(f"[Agent] Available customer data: {customer_data}")
        
        # Check if all required fields are present and not None
        for field in required_fields:
            if field not in customer_data or customer_data[field] is None:
                logger.info(f"[Agent] Missing or null field: {field}")
                return False
                
        # Additional validation
        age = customer_data.get("age")
        coverage_amount = customer_data.get("coverage_amount")
        policy_term = customer_data.get("policy_term")
        
        logger.info(f"[Agent] Validating ranges - age: {age}, coverage: {coverage_amount}, term: {policy_term}")
        
        if not (18 <= age <= 65):
            logger.info(f"[Agent] Age {age} out of range (18-65)")
            return False
        if not (100000 <= coverage_amount <= 50000000):  # Min 1L, Max 5Cr
            logger.info(f"[Agent] Coverage {coverage_amount} out of range (100k-5Cr)")
            return False
        if not (5 <= policy_term <= 40):  # Min 5 years, Max 40 years
            logger.info(f"[Agent] Policy term {policy_term} out of range (5-40 years)")
            return False
            
        logger.info(f"[Agent] Quote generation eligible: TRUE")
        return True

    def _get_quote_params(self, session: SessionData) -> Dict[str, Any]:
        """Extract quote parameters from session data."""
        customer_data = session.customer_data
        return {
            "age": customer_data.get("age"),
            "gender": customer_data.get("gender"),
            "coverage_amount": customer_data.get("coverage_amount"),
            "policy_term": customer_data.get("policy_term"),
            "smoker": customer_data.get("smoker", False),
            "premium_frequency": customer_data.get("premium_frequency", "yearly")
        }

    async def _compose_final_reply(
        self,
        session: SessionData,
        user_message: str,
        llm_json: Dict[str, Any],
        api_results: List[Dict[str, Any]],
    ) -> str:
        # Check if we have quote results that need to be incorporated
        quote_results = [r for r in api_results if r.get("name") == "premium_calculation" and r.get("success")]
        
        # If we have quote results, we must regenerate the response to include them
        # Otherwise, use the initial LLM reply if it's clean
        if not quote_results:
            initial_reply = llm_json.get("reply", "")
            if initial_reply and not self._is_json_string(initial_reply):
                return initial_reply
            
            # If the initial reply looks like JSON, extract the reply field
            if initial_reply and self._is_json_string(initial_reply):
                cleaned = self._extract_reply_from_json(initial_reply)
                if cleaned:
                    return cleaned
        
        # Build conversation context for final reply composition
        conversation_context = []
        recent_turns = getattr(session, 'conversation_history', [])[-3:]  # Last 3 turns for context
        for turn in recent_turns:
            if hasattr(turn, 'user_message') and hasattr(turn, 'bot_response'):
                conversation_context.append({
                    "user": turn.user_message,
                    "bot": turn.bot_response
                })

        followup_context = {
            "conversation_history": conversation_context,
            "customer_data": session.customer_data,
            "session_state": session.current_state.value,
            "extracted": llm_json.get("extracted"),
            "api_results": api_results,
            "user_message": user_message,
            "state_context": {
                "mode": llm_json.get("mode", "conversational"),
                "reasoning": llm_json.get("reasoning", ""),
                "next_question": llm_json.get("next_question"),
                "session_id": session.session_id
            },
            "guidance": {
                "use_context": True,
                "be_natural": True,
                "tone": "friendly, professional, conversational",
                "remember_previous": True
            },
        }

        # Use a more explicit system prompt to get clean text only
        clean_text_prompt = (
            "You are a helpful insurance assistant. Respond with ONLY plain text - no JSON, no formatting, no quotes. "
            "Be friendly, professional, and conversational. Do not include any structured data in your response."
        )

        logger.info(f"[Agent] Final reply composition - found {len(quote_results)} quote results")
        if quote_results:
            logger.info(f"[Agent] Quote result data: {quote_results[0].get('result', {})}")
        
        prompt = (
            f"User just said: \"{user_message}\"\n\n"
            f"Based on the conversation context, provide a natural conversational response. "
            f"Use the conversation history to maintain continuity and reference previous information when relevant. "
        )
        
        if quote_results:
            quote_data = quote_results[0].get("result", {})
            best_quote = quote_data.get("best", {})
            all_quotes = quote_data.get("quotes", [])
            
            logger.info(f"[Agent] Including quote in response - best_quote: {best_quote}")
            
            prompt += (
                f"\n\nIMPORTANT: You have successfully generated quotes! Include these details naturally in your response:\n"
                f"**Best Recommended Quote:**\n"
                f"- Plan: {best_quote.get('name', 'N/A')}\n"
                f"- Premium: ₹{best_quote.get('annual_premium', 'N/A'):,} per year\n"
                f"- Coverage: ₹{best_quote.get('sum_assured', 'N/A'):,}\n"
                f"- Policy Term: {best_quote.get('policy_term', 'N/A')} years\n"
                f"- Features: {', '.join(best_quote.get('features', []))}\n\n"
                f"You can also mention that {len(all_quotes)} variants are available.\n"
                f"Present this as a personalized quote result and ask if they'd like to see other options or proceed.\n"
            )
        
        prompt += "\n\nRespond with ONLY the message text that should be shown to the user - no JSON structure."
        
        logger.info(f"[Agent] Composing final reply via LLM | mode={llm_json.get('mode')} | history_turns={len(conversation_context)}")
        reply = await ollama_service.generate_response(prompt, clean_text_prompt, followup_context)
        
        # Clean any remaining JSON artifacts
        cleaned_reply = self._extract_reply_from_json(reply) if self._is_json_string(reply) else reply
        return cleaned_reply

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


