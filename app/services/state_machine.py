from typing import Dict, Any, Optional
from app.models.session import SessionData, SessionState, session_manager
from app.models.chat_response import ChatResponse, ChatRequest
from app.states.base_state import BaseState, StateTransitionError, state_registry
from app.utils.logging import logger
import asyncio


class StateMachine:
    """Core state machine orchestrator for insurance process."""
    
    def __init__(self):
        self.current_sessions: Dict[str, SessionData] = {}
    
    async def start_new_session(self) -> SessionData:
        """Start a new insurance process session."""
        session = session_manager.create_session()
        self.current_sessions[session.session_id] = session
        
        logger.info(f"Started new session: {session.session_id}")
        return session
    
    async def get_session(self, session_id: str) -> Optional[SessionData]:
        """Get an existing session."""
        if session_id in self.current_sessions:
            return self.current_sessions[session_id]
        
        # Try to load from session manager
        session = session_manager.get_session(session_id)
        if session:
            self.current_sessions[session_id] = session
        
        return session
    
    async def process_chat_request(self, request: ChatRequest) -> ChatResponse:
        """Process a chat request and return appropriate response."""
        try:
            # Get or create session
            if request.session_id:
                session = await self.get_session(request.session_id)
                if not session:
                    logger.warning(f"Session not found: {request.session_id}")
                    session = await self.start_new_session()
            else:
                session = await self.start_new_session()
            
            # Get current state
            current_state = state_registry.get_state(session.current_state)
            if not current_state:
                logger.error(f"State not found: {session.current_state}")
                raise StateTransitionError(f"Invalid state: {session.current_state}")
            
            # Process message in current state
            response = await current_state.process_message(
                session=session,
                user_message=request.message,
                form_data=request.form_data,
                action_data=request.action_data
            )
            
            # Update session
            session.add_conversation_turn(
                user_message=request.message,
                bot_response=response.message,
                actions_taken=[action.type.value for action in response.actions],
                data_collected=request.form_data or {}
            )
            
            # Save session
            await self._save_session(session)
            
            logger.info(f"Processed message in state {session.current_state} for session {session.session_id}")
            return response
            
        except Exception as e:
            logger.error(f"Error processing chat request: {str(e)}")
            return self._create_error_response(str(e), request.session_id)
    
    async def transition_to_state(self, session: SessionData, target_state: SessionState, 
                                context: Dict[str, Any] = None) -> ChatResponse:
        """Transition session to a new state."""
        try:
            current_state = state_registry.get_state(session.current_state)
            target_state_instance = state_registry.get_state(target_state)
            
            if not target_state_instance:
                raise StateTransitionError(f"Target state not found: {target_state}")
            
            # Validate transition
            if current_state and not current_state.can_transition_to(target_state):
                raise StateTransitionError(f"Invalid transition from {session.current_state} to {target_state}")
            
            # Exit current state
            if current_state:
                await current_state.on_exit(session, target_state)
            
            # Update session state
            session.current_state = target_state
            session.state_context = context or {}
            
            # Enter new state
            response = await target_state_instance.enter(session, context)
            
            # Save session
            await self._save_session(session)
            
            logger.info(f"Transitioned session {session.session_id} from {current_state.state_name if current_state else 'None'} to {target_state}")
            return response
            
        except Exception as e:
            logger.error(f"Error transitioning to state {target_state}: {str(e)}")
            raise StateTransitionError(f"Failed to transition to {target_state}: {str(e)}")
    
    async def auto_advance_if_ready(self, session: SessionData) -> Optional[ChatResponse]:
        """Automatically advance to next state if current state is complete."""
        current_state = state_registry.get_state(session.current_state)
        if not current_state:
            return None
        
        # Check if current state is complete
        if current_state.is_state_complete(session):
            next_state = self._determine_next_state(session)
            if next_state:
                logger.info(f"Auto-advancing session {session.session_id} to {next_state}")
                return await self.transition_to_state(session, next_state)
        
        return None
    
    def _determine_next_state(self, session: SessionData) -> Optional[SessionState]:
        """Determine the next logical state based on current state and data."""
        current = session.current_state
        
        # Define the simplified flow
        state_flow = {
            SessionState.ONBOARDING: SessionState.ELIGIBILITY_CHECK,
            SessionState.ELIGIBILITY_CHECK: SessionState.QUOTE_GENERATION,
            SessionState.QUOTE_GENERATION: SessionState.PAYMENT_REDIRECT,
            SessionState.PAYMENT_REDIRECT: None,  # Terminal state - external payment
            SessionState.DOCUMENT_COLLECTION: SessionState.ONBOARDING,  # Back to onboarding after docs
        }
        
        return state_flow.get(current)
    
    async def _save_session(self, session: SessionData):
        """Save session to session manager."""
        session_manager.update_session(session)
        self.current_sessions[session.session_id] = session
    
    def _create_error_response(self, error_message: str, session_id: str = None) -> ChatResponse:
        """Create an error response."""
        return ChatResponse(
            message=f"I apologize, but I encountered an error: {error_message}. Please try again or contact support if the issue persists.",
            session_id=session_id or "error",
            current_state="error",
            actions=[],
            metadata={"error": True, "error_message": error_message}
        )
    
    async def get_session_history(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get conversation history for a session."""
        session = await self.get_session(session_id)
        if not session:
            return None
        
        return {
            "session_id": session.session_id,
            "current_state": session.current_state.value,
            "conversation_history": [
                {
                    "timestamp": turn.timestamp.isoformat(),
                    "user_message": turn.user_message,
                    "bot_response": turn.bot_response,
                    "state": turn.state.value,
                    "actions_taken": turn.actions_taken,
                    "data_collected": turn.data_collected
                }
                for turn in session.conversation_history
            ],
            "customer_data": session.customer_data,
            "completion_status": {
                field: field in session.customer_data and session.customer_data[field] is not None
                for field in ["full_name", "date_of_birth", "email", "mobile_number", "annual_income"]
            }
        }
    
    async def reset_session(self, session_id: str) -> bool:
        """Reset a session to initial state."""
        session = await self.get_session(session_id)
        if not session:
            return False
        
        # Clear data but keep session ID
        session.current_state = SessionState.ONBOARDING
        session.customer_data = {}
        session.quote_data = {}
        session.policy_data = {}
        session.conversation_history = []
        session.state_context = {}
        session.uploaded_documents = []
        session.payment_data = {}
        
        await self._save_session(session)
        logger.info(f"Reset session {session_id}")
        return True


# Global state machine instance
state_machine = StateMachine()