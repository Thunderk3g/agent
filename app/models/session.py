from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
import uuid


class SessionState(str, Enum):
    ONBOARDING = "onboarding"
    ELIGIBILITY_CHECK = "eligibility_check"
    PRODUCT_SELECTION = "product_selection"
    QUOTE_GENERATION = "quote_generation"
    ADDON_RIDERS = "addon_riders" 
    PAYMENT_INITIATED = "payment_initiated"
    DOCUMENT_COLLECTION = "document_collection"
    POLICY_ISSUED = "policy_issued"


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
    
    # Form completion tracking
    form_completion: Dict[str, Any] = {
        "personal_details": {"completed": False, "completion_percentage": 0},
        "insurance_requirements": {"completed": False, "completion_percentage": 0},
        "rider_selection": {"completed": False, "completion_percentage": 0},
        "payment_details": {"completed": False, "completion_percentage": 0}
    }
    
    # State transition history
    state_transitions: List[Dict[str, Any]] = []
    
    # Selected insurance product details
    selected_product: Dict[str, Any] = {}
    
    # Rider selections
    selected_riders: List[Dict[str, Any]] = []
    
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
    
    def update_frontend_data(self, store_update: Dict[str, Any]):
        """Update session data with frontend store mapping."""
        if not store_update:
            return
        
        # Map personalDetails to customer_data
        personal = store_update.get("personalDetails", {})
        if personal:
            mapped_personal = {}
            field_mapping = {
                "fullName": "full_name",
                "dateOfBirth": "date_of_birth", 
                "age": "age",
                "gender": "gender",
                "mobileNumber": "mobile_number",
                "email": "email",
                "pinCode": "pin_code",
                "tobaccoUser": "smoker"
            }
            for frontend_key, backend_key in field_mapping.items():
                if frontend_key in personal and personal[frontend_key] is not None:
                    mapped_personal[backend_key] = personal[frontend_key]
            
            if mapped_personal:
                self.customer_data.update(mapped_personal)
        
        # Map quoteDetails to quote_data  
        quote_details = store_update.get("quoteDetails", {})
        if quote_details:
            mapped_quote = {}
            quote_mapping = {
                "sumAssured": "coverage_amount",
                "policyTerm_years": "policy_term",
                "premiumPayingTerm_years": "premium_paying_term",
                "frequency": "premium_frequency"
            }
            for frontend_key, backend_key in quote_mapping.items():
                if frontend_key in quote_details and quote_details[frontend_key] is not None:
                    mapped_quote[backend_key] = quote_details[frontend_key]
            
            if mapped_quote:
                self.quote_data.update(mapped_quote)
                self.customer_data.update(mapped_quote)  # Also update customer_data for LLM context
        
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
    
    def transition_state(self, new_state: SessionState, context: Dict[str, Any] = None):
        """Transition to a new state with validation and logging."""
        old_state = self.current_state
        
        # Log state transition
        transition = {
            "timestamp": datetime.now().isoformat(),
            "from_state": old_state.value,
            "to_state": new_state.value,
            "context": context or {}
        }
        self.state_transitions.append(transition)
        
        # Update current state
        self.current_state = new_state
        self.updated_at = datetime.now()
    
    def update_form_completion(self, form_type: str, completion_data: Dict[str, Any]):
        """Update form completion tracking."""
        if form_type in self.form_completion:
            self.form_completion[form_type].update(completion_data)
            self.updated_at = datetime.now()
    
    def can_transition_to(self, target_state: SessionState) -> bool:
        """Check if transition to target state is allowed."""
        state_flow = {
            SessionState.ONBOARDING: [SessionState.ELIGIBILITY_CHECK],
            SessionState.ELIGIBILITY_CHECK: [SessionState.PRODUCT_SELECTION],
            SessionState.PRODUCT_SELECTION: [SessionState.QUOTE_GENERATION],
            SessionState.QUOTE_GENERATION: [SessionState.ADDON_RIDERS],
            SessionState.ADDON_RIDERS: [SessionState.PAYMENT_INITIATED],
            SessionState.PAYMENT_INITIATED: [SessionState.DOCUMENT_COLLECTION],
            SessionState.DOCUMENT_COLLECTION: [SessionState.POLICY_ISSUED]
        }
        
        allowed_transitions = state_flow.get(self.current_state, [])
        return target_state in allowed_transitions or target_state == self.current_state


class SessionManager:
    """JSON file-based session manager for persistent storage."""
    
    def __init__(self):
        self.sessions: Dict[str, SessionData] = {}
        self.max_sessions = 1000
        self.sessions_dir = "sessions"
        # Ensure sessions directory exists
        import os
        os.makedirs(self.sessions_dir, exist_ok=True)
    
    def create_session(self, session_id: Optional[str] = None) -> SessionData:
        """Create a new session with optional predefined session_id."""
        if session_id:
            # Check if session already exists
            existing_session = self.get_session(session_id)
            if existing_session:
                return existing_session
            # Try to restore session from data.json if it exists
            restored_session = self._restore_session_from_data_json(session_id)
            if restored_session:
                self.sessions[session_id] = restored_session
                self._persist_session(restored_session)
                return restored_session
            # Create session with provided ID
            session = SessionData(session_id=session_id)
        else:
            session = SessionData()
        
        # Clean up old sessions if we're at the limit
        if len(self.sessions) >= self.max_sessions:
            self._cleanup_old_sessions()
        
        # Store in memory and persist to file
        self.sessions[session.session_id] = session
        self._persist_session(session)
        return session
    
    def get_session(self, session_id: str) -> Optional[SessionData]:
        """Get an existing session from memory or load from file."""
        # Try memory first
        if session_id in self.sessions:
            return self.sessions[session_id]
        
        # Try loading from file
        session = self._load_session(session_id)
        if session:
            self.sessions[session_id] = session
        return session
    
    def update_session(self, session: SessionData):
        """Update an existing session."""
        session.updated_at = datetime.now()
        self.sessions[session.session_id] = session
        self._persist_session(session)
    
    def delete_session(self, session_id: str):
        """Delete a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
        
        # Also delete the file
        import os
        file_path = os.path.join(self.sessions_dir, f"{session_id}.json")
        if os.path.exists(file_path):
            os.remove(file_path)
    
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
            self.delete_session(session_id)
    
    def _persist_session(self, session: SessionData):
        """Persist session to JSON file."""
        import json
        import os
        
        file_path = os.path.join(self.sessions_dir, f"{session.session_id}.json")
        session_dict = session.model_dump()
        
        # Convert datetime objects to ISO strings for JSON serialization
        session_dict["created_at"] = session.created_at.isoformat()
        session_dict["updated_at"] = session.updated_at.isoformat()
        
        # Convert conversation history timestamps
        for turn in session_dict.get("conversation_history", []):
            if "timestamp" in turn:
                turn["timestamp"] = turn["timestamp"].isoformat() if hasattr(turn["timestamp"], 'isoformat') else turn["timestamp"]
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(session_dict, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error persisting session {session.session_id}: {e}")
    
    def _load_session(self, session_id: str) -> Optional[SessionData]:
        """Load session from JSON file."""
        import json
        import os
        from datetime import datetime
        
        file_path = os.path.join(self.sessions_dir, f"{session_id}.json")
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                session_dict = json.load(f)
            
            # Convert ISO strings back to datetime objects
            session_dict["created_at"] = datetime.fromisoformat(session_dict["created_at"])
            session_dict["updated_at"] = datetime.fromisoformat(session_dict["updated_at"])
            
            # Convert conversation history timestamps
            for turn in session_dict.get("conversation_history", []):
                if "timestamp" in turn and isinstance(turn["timestamp"], str):
                    turn["timestamp"] = datetime.fromisoformat(turn["timestamp"])
            
            return SessionData(**session_dict)
        except Exception as e:
            print(f"Error loading session {session_id}: {e}")
            return None

    def _restore_session_from_data_json(self, session_id: str) -> Optional[SessionData]:
        """Restore session data from data.json conversation history."""
        import json
        import os
        from datetime import datetime
        
        data_path = "data.json"
        if not os.path.exists(data_path):
            return None
        
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            conversations = data.get("conversations", [])
            session_conversations = [conv for conv in conversations if conv.get("session_id") == session_id]
            
            if not session_conversations:
                return None
            
            # Create new session with the provided session_id
            session = SessionData(session_id=session_id)
            
            # Restore customer data from the latest store updates
            latest_personal_details = {}
            latest_quote_details = {}
            
            for conv in session_conversations:
                store_update = conv.get("store_update", {})
                if store_update.get("personalDetails"):
                    latest_personal_details.update(store_update["personalDetails"])
                if store_update.get("quoteDetails"):
                    latest_quote_details.update(store_update["quoteDetails"])
            
            # Map frontend data to session data
            if latest_personal_details or latest_quote_details:
                combined_store_update = {
                    "personalDetails": latest_personal_details,
                    "quoteDetails": latest_quote_details
                }
                session.update_frontend_data(combined_store_update)
            
            # Restore conversation history as simple conversation turns
            for conv in session_conversations:
                if conv.get("user_message") and conv.get("final_reply"):
                    session.add_conversation_turn(
                        user_message=conv["user_message"],
                        bot_response=conv["final_reply"],
                        actions_taken=conv.get("llm_decision", {}).get("api_calls", []),
                        data_collected=conv.get("llm_decision", {}).get("extracted", {})
                    )
            
            # Set timestamps from first and last conversation
            if session_conversations:
                first_conv = session_conversations[0]
                last_conv = session_conversations[-1]
                
                try:
                    session.created_at = datetime.fromisoformat(first_conv["timestamp"].replace("Z", "+00:00"))
                    session.updated_at = datetime.fromisoformat(last_conv["timestamp"].replace("Z", "+00:00"))
                except Exception:
                    pass
            
            return session
            
        except Exception as e:
            print(f"Error restoring session {session_id} from data.json: {e}")
            return None


# Global session manager instance
session_manager = SessionManager()