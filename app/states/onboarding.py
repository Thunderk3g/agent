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
            "User is starting insurance application process",
            {"entering_onboarding": True}
        )
        
        missing_fields = self.get_missing_fields(session)
        actions = []
        
        if missing_fields:
            # Create form for missing personal details
            form_action = response_formatter.format_onboarding_form(session, missing_fields)
            actions.append(form_action)
        
        # Always show KYC documents option
        kyc_action = response_formatter.format_kyc_documents_form()
        actions.append(kyc_action)
        
        return self.create_basic_response(
            session=session,
            message=welcome_message,
            actions=actions,
            metadata={"onboarding_stage": "personal_details"}
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
        ai_response = await ollama_service.process_state_message(
            session,
            user_message,
            {"conversation_context": "onboarding"}
        )
        
        missing_fields = self.get_missing_fields(session)
        actions = []
        
        # Determine what actions to show based on conversation
        if any(keyword in user_message.lower() for keyword in ["start", "begin", "form", "details"]):
            if missing_fields:
                form_action = response_formatter.format_onboarding_form(session, missing_fields)
                actions.append(form_action)
        
        if any(keyword in user_message.lower() for keyword in ["document", "kyc", "upload", "pan", "aadhar"]):
            kyc_action = response_formatter.format_kyc_documents_form()
            actions.append(kyc_action)
        
        # If no specific actions triggered and we have missing info, show form
        if not actions and missing_fields:
            form_action = response_formatter.format_onboarding_form(session, missing_fields)
            actions.append(form_action)
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=actions,
            metadata={"conversation_response": True}
        )
    
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