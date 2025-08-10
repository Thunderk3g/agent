from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union
from app.models.chat_response import (
    ChatResponse, FormAction, DocumentUploadAction, 
    QuoteDisplayAction, PaymentRedirectAction,
    OptionsSelectionAction, ConfirmationAction,
    FormField, FieldType, ValidationRule, DataCollection
)
from app.models.session import SessionData, SessionState
from app.utils.logging import logger


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class BaseState(ABC):
    """Abstract base class for all insurance process states."""
    
    def __init__(self, state_name: SessionState):
        self.state_name = state_name
        self.allowed_transitions: List[SessionState] = []
        self.required_fields: List[str] = []
    
    @abstractmethod
    async def enter(self, session: SessionData, context: Dict[str, Any] = None) -> ChatResponse:
        """Called when entering this state. Returns initial chat response."""
        pass
    
    @abstractmethod
    async def process_message(self, session: SessionData, user_message: str, 
                            form_data: Dict[str, Any] = None,
                            action_data: Dict[str, Any] = None) -> ChatResponse:
        """Process user message and return chat response."""
        pass
    
    @abstractmethod 
    def can_transition_to(self, target_state: SessionState) -> bool:
        """Check if transition to target state is allowed."""
        return target_state in self.allowed_transitions
    
    def get_required_fields(self) -> List[str]:
        """Get list of required fields for this state."""
        return self.required_fields
    
    def get_missing_fields(self, session: SessionData) -> List[str]:
        """Get list of missing required fields from session data."""
        missing_fields = []
        for field in self.required_fields:
            if field not in session.customer_data or session.customer_data[field] is None:
                missing_fields.append(field)
        return missing_fields
    
    def create_form_action(self, title: str, fields: List[FormField], 
                          description: str = None, submit_label: str = "Submit") -> FormAction:
        """Helper to create form actions."""
        return FormAction(
            title=title,
            description=description,
            fields=fields,
            submit_label=submit_label
        )
    
    def create_field(self, name: str, label: str, field_type: FieldType,
                    required: bool = False, placeholder: str = None,
                    options: List[Dict[str, Any]] = None,
                    validation: ValidationRule = None) -> FormField:
        """Helper to create form fields."""
        return FormField(
            name=name,
            label=label,
            type=field_type,
            required=required,
            placeholder=placeholder,
            options=options,
            validation=validation
        )
    
    def update_session_data(self, session: SessionData, form_data: Dict[str, Any]):
        """Update session with form data."""
        if form_data:
            session.update_customer_data(form_data)
            logger.info(f"Updated session {session.session_id} with data: {list(form_data.keys())}")
    
    def create_data_collection_status(self, session: SessionData) -> DataCollection:
        """Create data collection status for response."""
        collected_fields = list(session.customer_data.keys())
        missing_fields = self.get_missing_fields(session)
        
        total_required = len(self.required_fields)
        collected_required = len([f for f in self.required_fields if f in collected_fields])
        completion_percentage = int((collected_required / total_required) * 100) if total_required > 0 else 100
        
        next_required = missing_fields[0] if missing_fields else None
        
        return DataCollection(
            collected=collected_fields,
            missing=missing_fields,
            completion_percentage=completion_percentage,
            next_required_field=next_required
        )
    
    def create_basic_response(self, session: SessionData, message: str,
                            actions: List[Union[FormAction, DocumentUploadAction, 
                                              QuoteDisplayAction, PaymentRedirectAction,
                                              OptionsSelectionAction, ConfirmationAction]] = None,
                            metadata: Dict[str, Any] = None) -> ChatResponse:
        """Create a basic chat response."""
        return ChatResponse(
            message=message,
            session_id=session.session_id,
            current_state=self.state_name.value,
            actions=actions or [],
            data_collection=self.create_data_collection_status(session),
            metadata=metadata or {}
        )
    
    def validate_transition(self, target_state: SessionState) -> bool:
        """Validate if transition to target state is allowed."""
        if not self.can_transition_to(target_state):
            logger.warning(f"Invalid transition from {self.state_name} to {target_state}")
            return False
        return True
    
    async def on_exit(self, session: SessionData, target_state: SessionState):
        """Called when exiting this state. Override for cleanup."""
        logger.info(f"Exiting state {self.state_name} to {target_state} for session {session.session_id}")
    
    def is_state_complete(self, session: SessionData) -> bool:
        """Check if this state has collected all required information."""
        missing_fields = self.get_missing_fields(session)
        return len(missing_fields) == 0
    
    def get_completion_message(self, session: SessionData) -> str:
        """Get message when state is completed."""
        return f"Great! I've collected all the necessary information for the {self.state_name.value.replace('_', ' ')} stage."
    
    def get_welcome_message(self) -> str:
        """Get welcome message when entering this state."""
        return f"Welcome to the {self.state_name.value.replace('_', ' ')} stage."


class StateRegistry:
    """Registry for all available states."""
    
    def __init__(self):
        self._states: Dict[SessionState, BaseState] = {}
    
    def register_state(self, state: BaseState):
        """Register a state in the registry."""
        self._states[state.state_name] = state
        logger.info(f"Registered state: {state.state_name}")
    
    def get_state(self, state_name: SessionState) -> Optional[BaseState]:
        """Get a state by name."""
        return self._states.get(state_name)
    
    def get_all_states(self) -> Dict[SessionState, BaseState]:
        """Get all registered states."""
        return self._states.copy()


# Global state registry
state_registry = StateRegistry()