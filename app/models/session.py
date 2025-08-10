from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
import uuid


class SessionState(str, Enum):
    ONBOARDING = "onboarding"
    ELIGIBILITY_CHECK = "eligibility_check"
    QUOTE_GENERATION = "quote_generation" 
    PAYMENT_REDIRECT = "payment_redirect"
    DOCUMENT_COLLECTION = "document_collection"


class ConversationTurn(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    user_message: str
    bot_response: str
    state: SessionState
    actions_taken: List[str] = []
    data_collected: Dict[str, Any] = {}


class SessionData(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    current_state: SessionState = SessionState.ONBOARDING
    
    # Customer data collected during conversation
    customer_data: Dict[str, Any] = {}
    
    # Insurance-specific data
    selected_variant: Optional[str] = None
    quote_data: Dict[str, Any] = {}
    policy_data: Dict[str, Any] = {}
    
    # Conversation history
    conversation_history: List[ConversationTurn] = []
    
    # State machine context
    state_context: Dict[str, Any] = {}
    
    # Document tracking
    uploaded_documents: List[Dict[str, Any]] = []
    
    # Payment and transaction data
    payment_data: Dict[str, Any] = {}
    
    # System metadata
    metadata: Dict[str, Any] = {}
    
    def add_conversation_turn(self, user_message: str, bot_response: str, 
                            actions_taken: List[str] = None, 
                            data_collected: Dict[str, Any] = None):
        """Add a new conversation turn to the history."""
        turn = ConversationTurn(
            user_message=user_message,
            bot_response=bot_response,
            state=self.current_state,
            actions_taken=actions_taken or [],
            data_collected=data_collected or {}
        )
        self.conversation_history.append(turn)
        self.updated_at = datetime.now()
    
    def update_customer_data(self, new_data: Dict[str, Any]):
        """Update customer data with new information."""
        self.customer_data.update(new_data)
        self.updated_at = datetime.now()
    
    def get_collected_fields(self) -> List[str]:
        """Get list of all collected customer data fields."""
        return list(self.customer_data.keys())
    
    def get_completion_percentage(self, required_fields: List[str]) -> int:
        """Calculate completion percentage based on required fields."""
        if not required_fields:
            return 100
        
        collected = len([field for field in required_fields 
                        if field in self.customer_data and self.customer_data[field] is not None])
        return int((collected / len(required_fields)) * 100)


class SessionManager:
    """In-memory session manager. In production, use Redis or database."""
    
    def __init__(self):
        self.sessions: Dict[str, SessionData] = {}
        self.max_sessions = 1000
    
    def create_session(self) -> SessionData:
        """Create a new session."""
        session = SessionData()
        
        # Clean up old sessions if we're at the limit
        if len(self.sessions) >= self.max_sessions:
            self._cleanup_old_sessions()
        
        self.sessions[session.session_id] = session
        return session
    
    def get_session(self, session_id: str) -> Optional[SessionData]:
        """Get an existing session."""
        return self.sessions.get(session_id)
    
    def update_session(self, session: SessionData):
        """Update an existing session."""
        session.updated_at = datetime.now()
        self.sessions[session.session_id] = session
    
    def delete_session(self, session_id: str):
        """Delete a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def _cleanup_old_sessions(self):
        """Remove oldest sessions when limit is reached."""
        if not self.sessions:
            return
            
        # Sort sessions by last update time
        sorted_sessions = sorted(
            self.sessions.items(), 
            key=lambda x: x[1].updated_at
        )
        
        # Remove oldest 10% of sessions
        num_to_remove = max(1, len(sorted_sessions) // 10)
        for i in range(num_to_remove):
            session_id, _ = sorted_sessions[i]
            del self.sessions[session_id]


# Global session manager instance
session_manager = SessionManager()