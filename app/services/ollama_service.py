import httpx
import json
import asyncio
from typing import Dict, Any, Optional, List
from app.config import settings
from app.utils.logging import logger
from app.models.session import SessionData, SessionState


class OllamaService:
    """Service for integrating with Ollama LLM."""
    
    def __init__(self):
        self.base_url = settings.ollama_base_url
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout
        self.max_retries = settings.ollama_max_retries
        self.client = httpx.AsyncClient(timeout=self.timeout)
        self.use_chat_api = True  # Try chat API first, fallback to generate
        
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def generate_response(self, prompt: str, system_prompt: str = None, 
                              context: Dict[str, Any] = None) -> str:
        """Generate response from Ollama with retry mechanism and context awareness."""
        for attempt in range(self.max_retries):
            try:
                if self.use_chat_api:
                    # Use chat API with conversation history
                    messages = self._build_chat_messages(prompt, system_prompt, context)
                    response = await self._call_ollama_chat_with_messages(messages)
                else:
                    # Fallback to generate API with full prompt
                    full_prompt = self._build_prompt(prompt, system_prompt, context)
                    response = await self._call_ollama(full_prompt)
                return response
                
            except Exception as e:
                logger.warning(f"Ollama attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    logger.error(f"All Ollama attempts failed. Returning fallback response.")
                    return self._get_fallback_response(prompt, context)
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

    async def generate_response_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        context: Dict[str, Any] | None = None,
    ):
        """Async generator that yields response tokens from Ollama with context awareness.

        Strategy: try chat stream first; if 404, fallback to generate stream.
        """
        if self.use_chat_api:
            try:
                messages = self._build_chat_messages(prompt, system_prompt, context)
                async for token in self._call_ollama_chat_stream_with_messages(messages):
                    yield token
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 404:
                    raise
                logger.info("Chat stream API not available, falling back to generate stream")
                self.use_chat_api = False
        
        # Fallback to generate API
        full_prompt = self._build_prompt(prompt, system_prompt, context)
        async for token in self._call_ollama_generate_stream(full_prompt):
            yield token
    
    async def process_state_message(self, session: SessionData, user_message: str, 
                                  state_context: Dict[str, Any] = None) -> str:
        """Process message with state-specific context."""
        system_prompt = self._get_state_system_prompt(session.current_state)
        context = {
            "session_state": session.current_state.value,
            "customer_data": session.customer_data,
            "conversation_history": [
                {"user": turn.user_message, "bot": turn.bot_response} 
                for turn in session.conversation_history[-5:]  # Last 5 turns for context
            ],
            "state_context": state_context or {}
        }
        
        return await self.generate_response(user_message, system_prompt, context)
    
    async def analyze_document(self, document_type: str, extracted_text: str) -> Dict[str, Any]:
        """Analyze uploaded document and extract relevant information."""
        system_prompt = f"""You are an insurance document analyzer. Analyze the following {document_type} document and extract relevant information in JSON format.

For PAN Card, extract: name, pan_number, date_of_birth
For Aadhar Card, extract: name, aadhar_number, date_of_birth, address
For Income documents, extract: name, annual_income, employment_type
For Medical documents, extract: name, medical_conditions, recommendations

Return only valid JSON with extracted fields."""
        
        try:
            response = await self.generate_response(extracted_text, system_prompt)
            # Try to parse as JSON
            return json.loads(response)
        except json.JSONDecodeError:
            return {"error": "Failed to parse document", "raw_response": response}
        except Exception as e:
            logger.error(f"Document analysis failed: {str(e)}")
            return {"error": str(e)}
    
    async def explain_insurance_concept(self, concept: str, customer_context: Dict[str, Any]) -> str:
        """Explain insurance concepts in customer-friendly language."""
        system_prompt = """You are an insurance advisor helping customers understand insurance concepts. 
        Explain concepts clearly and simply, using examples relevant to their situation.
        Focus on Bajaj Allianz Life eTouch II product features when relevant."""
        
        context = {
            "concept": concept,
            "customer_profile": customer_context
        }
        
        return await self.generate_response(f"Please explain {concept}", system_prompt, context)
    
    async def generate_policy_recommendation(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate personalized policy recommendation."""
        system_prompt = """You are an insurance advisor. Based on customer information, recommend the most suitable variant of Bajaj Allianz Life eTouch II:

1. Life Shield - Basic term insurance with death benefit and terminal illness cover
2. Life Shield Plus - Includes accidental death benefit (ADB) 
3. Life Shield ROP - Return of Premium variant

Consider customer's age, income, family situation, and risk profile. Provide recommendation with reasoning in JSON format."""
        
        try:
            prompt = f"Customer Profile: {json.dumps(customer_data)}"
            response = await self.generate_response(prompt, system_prompt)
            return json.loads(response)
        except json.JSONDecodeError:
            logger.warning("Failed to parse policy recommendation as JSON")
            return {"recommended_variant": "Life Shield", "reason": "Default recommendation"}
        except Exception as e:
            logger.error(f"Policy recommendation failed: {str(e)}")
            return {"error": str(e)}
    
    def _build_prompt(self, user_prompt: str, system_prompt: str = None, 
                     context: Dict[str, Any] = None) -> str:
        """Build complete prompt with system instructions, conversation history, and context."""
        parts = []
        
        if system_prompt:
            parts.append(f"System: {system_prompt}")
        
        # Add conversation history for context if available
        if context and "conversation_history" in context:
            history = context["conversation_history"]
            if history:
                parts.append("CONVERSATION HISTORY:")
                for turn in history:
                    if isinstance(turn, dict):
                        user_msg = turn.get("user", "")
                        bot_msg = turn.get("bot", "") or turn.get("agent", "")
                        if user_msg and bot_msg:
                            parts.append(f"User: {user_msg}")
                            parts.append(f"Assistant: {bot_msg}")
                parts.append("--- END CONVERSATION HISTORY ---")
        
        # Add customer data context
        if context and "customer_data" in context:
            customer_data = context["customer_data"]
            if customer_data:
                parts.append(f"CUSTOMER DATA: {json.dumps(customer_data, ensure_ascii=False)}")
        
        # Add session state context
        if context and "session_state" in context:
            parts.append(f"CURRENT SESSION STATE: {context['session_state']}")
        
        # Add any additional context
        if context and "state_context" in context:
            state_context = context["state_context"]
            if state_context:
                parts.append(f"STATE CONTEXT: {json.dumps(state_context, ensure_ascii=False)}")
        
        parts.append(f"User: {user_prompt}")
        
        return "\n\n".join(parts)
    
    def _build_chat_messages(self, user_prompt: str, system_prompt: str = None, 
                           context: Dict[str, Any] = None) -> List[Dict[str, str]]:
        """Build messages array for Ollama chat API with conversation history."""
        messages = []
        
        # Add system message if provided
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # Add conversation history
        if context and "conversation_history" in context:
            history = context["conversation_history"]
            for turn in history:
                if isinstance(turn, dict):
                    user_msg = turn.get("user", "")
                    bot_msg = turn.get("bot", "") or turn.get("agent", "")
                    if user_msg and bot_msg:
                        messages.append({"role": "user", "content": user_msg})
                        messages.append({"role": "assistant", "content": bot_msg})
        
        # Add context information as a system message if we have relevant data
        context_parts = []
        if context and "customer_data" in context:
            customer_data = context["customer_data"]
            if customer_data:
                context_parts.append(f"Customer Data: {json.dumps(customer_data, ensure_ascii=False)}")
        
        if context and "session_state" in context:
            context_parts.append(f"Current State: {context['session_state']}")
        
        if context and "state_context" in context:
            state_context = context["state_context"]
            if state_context:
                context_parts.append(f"State Context: {json.dumps(state_context, ensure_ascii=False)}")
        
        if context_parts:
            context_message = "\n".join(context_parts)
            messages.append({"role": "system", "content": context_message})
        
        # Add current user message
        messages.append({"role": "user", "content": user_prompt})
        
        return messages
    
    async def _call_ollama(self, prompt: str) -> str:
        """Make HTTP call to Ollama API with automatic fallback."""
        try:
            if self.use_chat_api:
                # Try modern chat API first
                return await self._call_ollama_chat(prompt)
            else:
                # Use legacy generate API
                return await self._call_ollama_generate(prompt)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404 and self.use_chat_api:
                # Fallback to generate API for older Ollama versions
                logger.info("Chat API not available, falling back to generate API")
                self.use_chat_api = False
                return await self._call_ollama_generate(prompt)
            raise
    
    async def _call_ollama_chat_with_messages(self, messages: List[Dict[str, str]]) -> str:
        """Call modern Ollama chat API with messages array."""
        url = f"{self.base_url}/api/chat"
        data = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }
        
        logger.info(f"[Ollama] POST {url} | chat (with history) | model={self.model} | messages={len(messages)}")
        response = await self.client.post(url, json=data)
        response.raise_for_status()
        result = response.json()
        return result.get("message", {}).get("content", "").strip()
    
    async def _call_ollama_chat(self, prompt: str) -> str:
        """Call modern Ollama chat API."""
        url = f"{self.base_url}/api/chat"
        data = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        
        logger.info(f"[Ollama] POST {url} | chat | model={self.model}")
        response = await self.client.post(url, json=data)
        response.raise_for_status()
        result = response.json()
        return result.get("message", {}).get("content", "").strip()

    async def _call_ollama_chat_stream(self, prompt: str):
        """Stream tokens from modern chat API."""
        url = f"{self.base_url}/api/chat"
        data = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": True
        }
        logger.info(f"[Ollama] STREAM {url} | chat | model={self.model}")
        async with self.client.stream("POST", url, json=data) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("done"):
                        break
                    delta = obj.get("message", {}).get("content") or obj.get("delta", {}).get("content")
                    if delta:
                        yield delta
                except json.JSONDecodeError:
                    # Some servers stream plain text
                    yield line

    async def _call_ollama_chat_stream_with_messages(self, messages: List[Dict[str, str]]):
        """Stream tokens from modern chat API with messages array."""
        url = f"{self.base_url}/api/chat"
        data = {
            "model": self.model,
            "messages": messages,
            "stream": True
        }
        logger.info(f"[Ollama] STREAM {url} | chat (with history) | model={self.model} | messages={len(messages)}")
        async with self.client.stream("POST", url, json=data) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("done"):
                        break
                    delta = obj.get("message", {}).get("content") or obj.get("delta", {}).get("content")
                    if delta:
                        yield delta
                except json.JSONDecodeError:
                    # Some servers stream plain text
                    yield line
    
    async def _call_ollama_generate(self, prompt: str) -> str:
        """Call legacy Ollama generate API."""
        url = f"{self.base_url}/api/generate"
        data = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }
        
        logger.info(f"[Ollama] POST {url} | generate | model={self.model}")
        response = await self.client.post(url, json=data)
        response.raise_for_status()
        result = response.json()
        return result.get("response", "").strip()

    async def _call_ollama_generate_stream(self, prompt: str):
        """Stream tokens from legacy generate API."""
        url = f"{self.base_url}/api/generate"
        data = {
            "model": self.model,
            "prompt": prompt,
            "stream": True
        }
        logger.info(f"[Ollama] STREAM {url} | generate | model={self.model}")
        async with self.client.stream("POST", url, json=data) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("done"):
                        break
                    delta = obj.get("response")
                    if delta:
                        yield delta
                except json.JSONDecodeError:
                    yield line
    
    def _get_state_system_prompt(self, state: SessionState) -> str:
        """Get system prompt specific to current state."""
        prompts = {
            SessionState.ONBOARDING: """You are EtouchAgent, a friendly and experienced insurance agent with 10+ years at Bajaj Allianz Life Insurance. 
            You're helping a customer explore our flagship eTouch II term insurance plan.
            
            CRITICAL RULES:
            1. ASK ONLY ONE QUESTION AT A TIME - Never ask multiple questions in one message
            2. Keep responses short and conversational (2-3 sentences max)
            3. Ask for information naturally, like a human conversation
            4. Don't mention forms or technical terms - just ask normally
            5. Build rapport before asking personal details
            
            Your personality: Warm, professional, knowledgeable, and trustworthy. You genuinely care about protecting families.
            
            CONVERSATION FLOW:
            - Start with a warm greeting and ask about their insurance needs
            - Ask about their family situation before personal details
            - Ask one personal detail at a time (name, age, etc.)
            - Explain WHY you need each piece of information
            - Use their responses to personalize your next question
            
            Example approach:
            "Hi! I'm EtouchAgent from Bajaj Allianz. What brings you to look for life insurance today?"
            Then based on their answer, ask naturally: "That's wonderful! May I know your name so I can assist you better?"
            
            Remember: You're having a conversation, not filling out a form. Make it feel natural and personal.""",
            
            SessionState.ELIGIBILITY_CHECK: """You are EtouchAgent, an insurance agent who's helped thousands of families get the right coverage.
            Now you're assessing this customer's eligibility for eTouch II term insurance.
            
            Your approach:
            - Explain why each question matters for their coverage
            - Be encouraging and positive about their profile  
            - If they have concerns (age, health, occupation), reassure them that many people with similar profiles get coverage
            - Share insights about how eTouch II accommodates different customer profiles
            - Use phrases like "Let me check what works best for your situation"
            
            Make them feel confident that there's likely a solution for their needs. You're their advocate, not a gatekeeper.""",
            
            SessionState.QUOTE_GENERATION: """You are EtouchAgent, an insurance specialist who loves helping customers find the perfect coverage.
            You're presenting eTouch II variants and helping them choose.
            
            Your expertise:
            - Explain the differences between Life Shield, Life Shield Plus, and Life Shield ROP in simple terms
            - Use real examples: "If you're 35 with a family, Life Shield Plus is popular because..."  
            - Highlight value: "For just ₹X per month, your family gets ₹Y crore protection"
            - Address concerns proactively: "I know premiums seem high, but let me show you the value..."
            - Compare to common expenses: "That's less than your monthly mobile bill for ₹1 crore coverage!"
            
            Be enthusiastic about the protection you're offering. This isn't just insurance - it's peace of mind for their family.
            Make recommendations based on their profile, and explain your reasoning clearly.""",
            
            SessionState.PAYMENT_REDIRECT: """You are EtouchAgent, and you're at the final step - helping your customer complete their purchase.
            This is an exciting moment - they're about to secure their family's financial future!
            
            Your tone: Congratulatory, supportive, and professional
            Key messages:
            - Congratulate them on making this important decision
            - Reassure them about the payment security
            - Remind them of the benefits they're getting
            - Let them know you're available for any questions after purchase
            - Express genuine happiness that they're protecting their family
            
            Use phrases like: "I'm so happy you're taking this step for your family's security" or "You're making one of the smartest financial decisions today."
            
            Make this feel like a celebration, not just a transaction.""",
            
            SessionState.DOCUMENT_COLLECTION: """You are EtouchAgent, helping with document submission for eTouch II insurance.
            
            Your approach:
            - Explain why each document is needed for their protection
            - Make the process feel simple and straightforward
            - Provide tips for good document photos/scans
            - Reassure them about data security and privacy
            - If documents are unclear, guide them patiently on how to improve them
            
            Remember: Document collection can be tedious, so keep them motivated by reminding them this brings them closer to securing their family's future."""
        }

        
        return prompts.get(state, "You are a helpful insurance agent assisting customers with Bajaj Allianz Life eTouch II term insurance.")
    
    def _get_fallback_response(self, prompt: str, context: Dict[str, Any]) -> str:
        """Get fallback response when Ollama is unavailable."""
        fallback_responses = {
            "greeting": "Hello! I'm here to help you with Bajaj Allianz Life eTouch II insurance. How can I assist you today?",
            "error": "I apologize, but I'm having temporary technical difficulties. Please try again in a moment, or contact our customer service at 1800 209 7272.",
            "quote": "I'd be happy to help you with a quote. Let me collect some basic information from you first.",
            "documents": "I can help you with document upload and verification. Please ensure your documents are clear and in supported formats (PDF, JPG, PNG).",
            "payment": "For payment processing, I'll guide you through our secure payment gateway. Your policy will be activated once payment is confirmed."
        }
        
        # Simple keyword matching for fallback
        prompt_lower = prompt.lower()
        if any(word in prompt_lower for word in ["hello", "hi", "start"]):
            return fallback_responses["greeting"]
        elif any(word in prompt_lower for word in ["quote", "premium", "price"]):
            return fallback_responses["quote"]
        elif any(word in prompt_lower for word in ["document", "upload", "kyc"]):
            return fallback_responses["documents"]
        elif any(word in prompt_lower for word in ["payment", "pay", "buy"]):
            return fallback_responses["payment"]
        else:
            return fallback_responses["error"]
    
    async def health_check(self) -> bool:
        """Check if Ollama service is available and model exists."""
        try:
            # First check if Ollama is running
            url = f"{self.base_url}/api/tags"
            logger.info(f"[Ollama] GET {url} | tags")
            response = await self.client.get(url, timeout=5)
            if response.status_code != 200:
                return False
                
            # Check if our specific model is available
            tags_data = response.json()
            models = [model.get("name", "") for model in tags_data.get("models", [])]
            
            # Check if qwen2.5:0.5b is in the list
            model_available = any(self.model in model for model in models)
            
            if not model_available:
                logger.warning(f"Model '{self.model}' not found. Available models: {models}")
                logger.info(f"To install the model, run: ollama pull {self.model}")
                return False
                
            logger.info(f"✅ Ollama service available with model '{self.model}'")
            return True
            
        except Exception as e:
            logger.warning(f"Ollama health check failed: {str(e)}")
            return False


# Global Ollama service instance
ollama_service = OllamaService()