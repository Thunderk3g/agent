from typing import Dict, Any, List
from app.states.base_state import BaseState
from app.models.session import SessionData, SessionState
from app.models.chat_response import ChatResponse
from app.services.ollama_service import ollama_service
from app.utils.logging import logger


class ProductSelectionState(BaseState):
    """State for selecting insurance product variants."""
    
    def __init__(self):
        super().__init__(SessionState.PRODUCT_SELECTION)
        self.allowed_transitions = [
            SessionState.QUOTE_GENERATION,
            SessionState.ELIGIBILITY_CHECK  # Back if needs adjustment
        ]
        self.required_fields = [
            "selected_variant"
        ]
    
    async def enter(self, session: SessionData, context: Dict[str, Any] = None) -> ChatResponse:
        """Enter product selection state."""
        welcome_message = await ollama_service.process_state_message(
            session,
            "Help user choose the best eTouch II variant for their needs.",
            {"entering_product_selection": True}
        )
        
        return self.create_basic_response(
            session=session,
            message=welcome_message,
            actions=[],
            metadata={"product_selection_stage": "variant_selection"}
        )
    
    async def process_message(self, session: SessionData, user_message: str,
                            form_data: Dict[str, Any] = None,
                            action_data: Dict[str, Any] = None) -> ChatResponse:
        """Process product selection messages."""
        
        if action_data and action_data.get("action") == "select_variant":
            return await self._handle_variant_selection(session, user_message, action_data)
        
        return await self._handle_conversation(session, user_message)
    
    async def _handle_variant_selection(self, session: SessionData, user_message: str,
                                      action_data: Dict[str, Any]) -> ChatResponse:
        """Handle variant selection."""
        selected_variant = action_data.get("variant")
        
        # Store selected variant
        session.selected_product = {"variant": selected_variant}
        self.update_session_data(session, {"selected_variant": selected_variant})
        
        ai_response = await ollama_service.process_state_message(
            session,
            f"User selected {selected_variant} variant. Explain the benefits and proceed to quote generation.",
            {"selected_variant": selected_variant}
        )
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=[],
            metadata={
                "variant_selected": True,
                "selected_variant": selected_variant,
                "ready_for_quotes": True
            }
        )
    
    async def _handle_conversation(self, session: SessionData, user_message: str) -> ChatResponse:
        """Handle general conversation during product selection."""
        ai_response = await ollama_service.process_state_message(
            session,
            user_message,
            {"conversation_context": "product_selection"}
        )
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=[],
            metadata={"conversation_response": True}
        )
    
    def can_transition_to(self, target_state: SessionState) -> bool:
        """Check if transition to target state is allowed."""
        return target_state in self.allowed_transitions
    
    def is_state_complete(self, session: SessionData) -> bool:
        """Check if product selection is complete."""
        return bool(session.selected_product.get("variant"))