from typing import Dict, Any, List
from app.states.base_state import BaseState
from app.models.session import SessionData, SessionState
from app.models.chat_response import ChatResponse
from app.services.ollama_service import ollama_service
from app.services.response_formatter import response_formatter
from app.utils.logging import logger


class OnboardingState(BaseState):
    """Initial state for customer onboarding and KYC collection."""
    
    def __init__(self):
        super().__init__(SessionState.ONBOARDING)
        self.allowed_transitions = [
            SessionState.ELIGIBILITY_CHECK,
            SessionState.DOCUMENT_COLLECTION
        ]
        self.required_fields = [
            "full_name", "date_of_birth", "gender", "mobile_number", 
            "email", "pin_code", "annual_income", "tobacco_user"
        ]
    
    async def enter(self, session: SessionData, context: Dict[str, Any] = None) -> ChatResponse:
        """Enter onboarding state with welcome message."""
        welcome_message = await ollama_service.process_state_message(
            session, 
            "User is starting insurance application process. Greet them warmly and ask what brings them to look for life insurance today.",
            {"entering_onboarding": True, "first_interaction": True}
        )
        
        # Don't show forms initially - let EtouchAgent ask questions naturally
        # Only show forms when user specifically asks for them or after conversation
        return self.create_basic_response(
            session=session,
            message=welcome_message,
            actions=[],  # No forms initially
            metadata={"onboarding_stage": "conversation_start", "next_field_to_ask": "purpose"}
        )
    
    async def process_message(self, session: SessionData, user_message: str,
                            form_data: Dict[str, Any] = None,
                            action_data: Dict[str, Any] = None) -> ChatResponse:
        """Process user messages and form submissions during onboarding."""
        
        # Handle form data submission
        if form_data:
            return await self._handle_form_submission(session, user_message, form_data)
        
        # Handle document upload notifications
        if action_data and action_data.get("action") == "documents_uploaded":
            return await self._handle_document_upload(session, user_message, action_data)
        
        # Handle general conversation
        return await self._handle_conversation(session, user_message)
    
    async def _handle_form_submission(self, session: SessionData, user_message: str, 
                                    form_data: Dict[str, Any]) -> ChatResponse:
        """Handle form data submission."""
        # Update session with form data
        self.update_session_data(session, form_data)
        
        # Generate contextual response
        ai_response = await ollama_service.process_state_message(
            session,
            f"User submitted form data: {list(form_data.keys())}",
            {"form_data": form_data}
        )
        
        missing_fields = self.get_missing_fields(session)
        actions = []
        
        if missing_fields:
            # Still have missing fields, show form again
            form_action = response_formatter.format_onboarding_form(session, missing_fields)
            actions.append(form_action)
        else:
            # All personal details collected, show KYC documents
            kyc_action = response_formatter.format_kyc_documents_form()
            actions.append(kyc_action)
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=actions,
            metadata={
                "form_submitted": True,
                "fields_updated": list(form_data.keys())
            }
        )
    
    async def _handle_document_upload(self, session: SessionData, user_message: str,
                                    action_data: Dict[str, Any]) -> ChatResponse:
        """Handle document upload completion."""
        uploaded_docs = action_data.get("documents", [])
        
        # Store document information in session
        for doc in uploaded_docs:
            session.uploaded_documents.append({
                "type": doc.get("type"),
                "name": doc.get("name"),
                "path": doc.get("path"),
                "uploaded_at": doc.get("uploaded_at")
            })
        
        ai_response = await ollama_service.process_state_message(
            session,
            f"User uploaded documents: {[doc.get('type') for doc in uploaded_docs]}",
            {"documents_uploaded": uploaded_docs}
        )
        
        # Check if we can proceed to next state
        if self.is_state_complete(session) and len(session.uploaded_documents) >= 2:  # PAN and Aadhar
            # Suggest moving to eligibility check
            ai_response += "\n\nGreat! Now let's check your eligibility for our insurance plans."
            
            return self.create_basic_response(
                session=session,
                message=ai_response,
                actions=[],
                metadata={
                    "ready_for_next_state": True,
                    "next_state": "eligibility_check",
                    "documents_uploaded": len(uploaded_docs)
                }
            )
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=[],
            metadata={
                "documents_uploaded": len(uploaded_docs)
            }
        )
    
    async def _handle_conversation(self, session: SessionData, user_message: str) -> ChatResponse:
        """Handle general conversation during onboarding."""
        
        # Extract information from natural conversation
        extracted_info = self._extract_info_from_message(user_message)
        if extracted_info:
            self.update_session_data(session, extracted_info)
            logger.info(f"Extracted info from conversation: {extracted_info}")
        
        # Determine what to ask next based on missing fields
        missing_fields = self.get_missing_fields(session)
        next_field_to_ask = self._get_next_field_to_ask(session, missing_fields)
        
        # Generate contextual response with instruction for next question
        context = {
            "conversation_context": "onboarding",
            "extracted_info": extracted_info,
            "missing_fields": missing_fields,
            "next_field_to_ask": next_field_to_ask,
            "conversation_stage": len(session.conversation_history)
        }
        
        # Give EtouchAgent specific instructions about what to ask next
        prompt = user_message
        if next_field_to_ask:
            prompt += f"\n\nNext, naturally ask for their {next_field_to_ask.replace('_', ' ')} if you haven't already."
        
        ai_response = await ollama_service.process_state_message(session, prompt, context)
        
        # Only show forms if user explicitly asks or if we've covered basics
        actions = []
        if any(keyword in user_message.lower() for keyword in ["form", "fill out", "complete details"]):
            if missing_fields:
                form_action = response_formatter.format_onboarding_form(session, missing_fields)
                actions.append(form_action)
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=actions,
            metadata={
                "conversation_response": True,
                "extracted_info": extracted_info,
                "next_field_to_ask": next_field_to_ask
            }
        )
    
    def _extract_info_from_message(self, message: str) -> Dict[str, Any]:
        """Extract information from natural conversation."""
        extracted = {}
        message_lower = message.lower()
        
        # Extract name (look for "my name is", "I'm", etc.)
        import re
        name_patterns = [
            r"my name is ([a-zA-Z\s]+)",
            r"i'm ([a-zA-Z\s]+)",
            r"i am ([a-zA-Z\s]+)",
            r"call me ([a-zA-Z\s]+)"
        ]
        for pattern in name_patterns:
            match = re.search(pattern, message_lower)
            if match and len(match.group(1).strip()) > 1:
                extracted["full_name"] = match.group(1).strip().title()
                break
        
        # Extract age/birth year
        age_patterns = [
            r"i'm (\d{1,2}) years? old",
            r"i am (\d{1,2}) years? old",
            r"(\d{1,2}) years? old",
            r"born in (\d{4})",
            r"age (\d{1,2})"
        ]
        for pattern in age_patterns:
            match = re.search(pattern, message_lower)
            if match:
                age_or_year = int(match.group(1))
                if age_or_year > 1900:  # It's a birth year
                    from datetime import datetime
                    current_year = datetime.now().year
                    if age_or_year <= current_year:
                        birth_date = f"{age_or_year}-01-01"
                        extracted["date_of_birth"] = birth_date
                elif 18 <= age_or_year <= 80:  # It's an age
                    from datetime import datetime
                    birth_year = datetime.now().year - age_or_year
                    extracted["date_of_birth"] = f"{birth_year}-01-01"
                break
        
        # Extract phone number
        phone_patterns = [
            r"(\+91[\s-]?)?([789]\d{9})",
            r"my number is (\+91[\s-]?)?([789]\d{9})",
            r"(\d{10})"
        ]
        for pattern in phone_patterns:
            match = re.search(pattern, message)
            if match:
                phone = re.sub(r"[\s-]", "", match.group(0))
                if len(phone) == 10 and phone[0] in "789":
                    extracted["mobile_number"] = f"+91{phone}"
                elif len(phone) == 13 and phone.startswith("+91"):
                    extracted["mobile_number"] = phone
                break
        
        # Extract email
        email_pattern = r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
        match = re.search(email_pattern, message)
        if match:
            extracted["email"] = match.group(1)
        
        return extracted
    
    def _get_next_field_to_ask(self, session: SessionData, missing_fields: List[str]) -> str:
        """Determine the next field to ask for in conversation."""
        # Order of importance for asking
        field_priority = [
            "full_name",
            "date_of_birth", 
            "mobile_number",
            "email",
            "annual_income",
            "tobacco_user",
            "pin_code",
            "gender"
        ]
        
        for field in field_priority:
            if field in missing_fields:
                return field
        return None
    
    def can_transition_to(self, target_state: SessionState) -> bool:
        """Check if transition to target state is allowed."""
        return target_state in self.allowed_transitions
    
    def is_state_complete(self, session: SessionData) -> bool:
        """Check if onboarding is complete."""
        missing_fields = self.get_missing_fields(session)
        has_required_docs = len(session.uploaded_documents) >= 2  # PAN and Aadhar minimum
        return len(missing_fields) == 0 and has_required_docs
    
    def get_completion_message(self, session: SessionData) -> str:
        """Get completion message."""
        return "Perfect! Your personal information and documents have been collected. Let's proceed to check your eligibility for our insurance plans."