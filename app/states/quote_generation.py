from typing import Dict, Any, List
from app.states.base_state import BaseState
from app.models.session import SessionData, SessionState
from app.models.chat_response import ChatResponse, FormField, FieldType, ValidationRule
from app.services.ollama_service import ollama_service
from app.services.response_formatter import response_formatter
from app.services.quote_calculator import quote_calculator
from app.utils.logging import logger
from datetime import date


class QuoteGenerationState(BaseState):
    """State for generating and presenting insurance quotes."""
    
    def __init__(self):
        super().__init__(SessionState.QUOTE_GENERATION)
        self.allowed_transitions = [
            SessionState.PAYMENT_REDIRECT,
            SessionState.ELIGIBILITY_CHECK  # Back if parameters need adjustment
        ]
        self.required_fields = [
            "sum_assured", "policy_term", "premium_paying_term", "payment_frequency"
        ]
    
    async def enter(self, session: SessionData, context: Dict[str, Any] = None) -> ChatResponse:
        """Enter quote generation state."""
        welcome_message = await ollama_service.process_state_message(
            session,
            "User is ready for quote generation. Explain different variants and help them choose coverage amount.",
            {"entering_quote_generation": True}
        )
        
        missing_fields = self.get_missing_fields(session)
        actions = []
        
        if missing_fields:
            # Show quote parameters form
            quote_form = self._create_quote_parameters_form(session)
            actions.append(quote_form)
        else:
            # Generate quotes with existing parameters
            await self._generate_quotes(session)
            quotes_display = response_formatter.format_quote_selection(session.quote_data.get("quotes", []))
            actions.append(quotes_display)
        
        return self.create_basic_response(
            session=session,
            message=welcome_message,
            actions=actions,
            metadata={"quote_generation_stage": "parameters" if missing_fields else "selection"}
        )
    
    async def process_message(self, session: SessionData, user_message: str,
                            form_data: Dict[str, Any] = None,
                            action_data: Dict[str, Any] = None) -> ChatResponse:
        """Process quote generation messages."""
        
        if form_data:
            return await self._handle_quote_parameters(session, user_message, form_data)
        
        if action_data and action_data.get("action") == "select_variant":
            return await self._handle_variant_selection(session, user_message, action_data)
        
        return await self._handle_conversation(session, user_message)
    
    async def _handle_quote_parameters(self, session: SessionData, user_message: str,
                                     form_data: Dict[str, Any]) -> ChatResponse:
        """Handle quote parameters form submission."""
        # Validate sum assured
        annual_income = session.customer_data.get("annual_income", 500000)
        sum_assured = form_data.get("sum_assured")
        
        if sum_assured:
            validation = quote_calculator.validate_sum_assured(sum_assured, annual_income)
            if not validation["valid"]:
                error_message = await ollama_service.process_state_message(
                    session,
                    f"Sum assured validation failed: {validation['messages']}",
                    {"validation_error": validation}
                )
                
                quote_form = self._create_quote_parameters_form(session, validation["messages"])
                return self.create_basic_response(
                    session=session,
                    message=error_message,
                    actions=[quote_form],
                    metadata={"validation_error": True}
                )
        
        # Update session with parameters
        self.update_session_data(session, form_data)
        
        # Generate quotes
        quotes = await self._generate_quotes(session)
        
        ai_response = await ollama_service.process_state_message(
            session,
            f"Generated {len(quotes)} quotes for user based on parameters: {form_data}",
            {"quotes": quotes, "parameters": form_data}
        )
        
        quotes_display = response_formatter.format_quote_selection(quotes)
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=[quotes_display],
            metadata={
                "quotes_generated": True,
                "quote_count": len(quotes)
            }
        )
    
    async def _handle_variant_selection(self, session: SessionData, user_message: str,
                                      action_data: Dict[str, Any]) -> ChatResponse:
        """Handle variant selection."""
        selected_variant = action_data.get("variant")
        selected_quote = None
        
        # Find selected quote
        for quote in session.quote_data.get("quotes", []):
            if quote["name"] == selected_variant:
                selected_quote = quote
                break
        
        if not selected_quote:
            error_message = "Sorry, I couldn't find the selected variant. Please try again."
            return self.create_basic_response(
                session=session,
                message=error_message,
                actions=[],
                metadata={"selection_error": True}
            )
        
        # Store selected variant
        session.selected_variant = selected_variant
        session.quote_data["selected_quote"] = selected_quote
        
        ai_response = await ollama_service.process_state_message(
            session,
            f"User selected {selected_variant} variant with premium ₹{selected_quote['annual_premium']}",
            {"selected_quote": selected_quote}
        )
        
        return self.create_basic_response(
            session=session,
            message=ai_response + "\n\n🎉 Excellent choice! You're all set to proceed with the payment.",
            actions=[],
            metadata={
                "variant_selected": True,
                "selected_variant": selected_variant,
                "ready_for_payment": True
            }
        )
    
    async def _handle_conversation(self, session: SessionData, user_message: str) -> ChatResponse:
        """Handle general conversation during quote generation."""
        ai_response = await ollama_service.process_state_message(
            session,
            user_message,
            {"conversation_context": "quote_generation"}
        )
        
        missing_fields = self.get_missing_fields(session)
        actions = []
        
        # Determine what to show based on conversation
        if missing_fields and any(keyword in user_message.lower() 
                                for keyword in ["quote", "premium", "price", "cost", "calculate"]):
            quote_form = self._create_quote_parameters_form(session)
            actions.append(quote_form)
        elif not missing_fields and "quote_data" not in session.__dict__:
            # Generate quotes if parameters are available but quotes not generated
            quotes = await self._generate_quotes(session)
            quotes_display = response_formatter.format_quote_selection(quotes)
            actions.append(quotes_display)
        elif any(keyword in user_message.lower() 
               for keyword in ["compare", "variants", "options", "plans"]):
            # Show existing quotes if available
            if session.quote_data.get("quotes"):
                quotes_display = response_formatter.format_quote_selection(session.quote_data["quotes"])
                actions.append(quotes_display)
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=actions,
            metadata={"conversation_response": True}
        )
    
    def _create_quote_parameters_form(self, session: SessionData, 
                                    validation_errors: List[str] = None) -> Any:
        """Create form for quote parameters."""
        customer_data = session.customer_data
        age = self._calculate_age_from_session(session)
        max_policy_term = min(85 - age, 50) if age else 30
        
        error_text = "\n".join(validation_errors) if validation_errors else None
        
        fields = [
            FormField(
                name="sum_assured",
                label="Life Cover Amount (₹)",
                type=FieldType.NUMBER,
                required=True,
                placeholder="Minimum ₹50,00,000",
                validation=ValidationRule(min_value=5000000),
                help_text="Choose coverage between 5-20 times your annual income" + (f"\n{error_text}" if error_text else "")
            ),
            FormField(
                name="policy_term",
                label="Policy Term (Years)",
                type=FieldType.SELECT,
                required=True,
                options=[
                    {"value": str(term), "label": f"{term} years"}
                    for term in range(10, min(max_policy_term + 1, 51), 5)
                ]
            ),
            FormField(
                name="premium_paying_term", 
                label="Premium Paying Term (Years)",
                type=FieldType.SELECT,
                required=True,
                options=[
                    {"value": str(term), "label": f"{term} years"}
                    for term in range(5, min(max_policy_term + 1, 51), 5)
                ]
            ),
            FormField(
                name="payment_frequency",
                label="Premium Payment Frequency",
                type=FieldType.SELECT,
                required=True,
                options=[
                    {"value": "yearly", "label": "Yearly (Best Value)"},
                    {"value": "half_yearly", "label": "Half-Yearly"},
                    {"value": "quarterly", "label": "Quarterly"},
                    {"value": "monthly", "label": "Monthly"}
                ]
            )
        ]
        
        return self.create_form_action(
            title="Quote Parameters",
            description="Please specify your coverage requirements to generate personalized quotes.",
            fields=fields,
            submit_label="Generate Quotes"
        )
    
    async def _generate_quotes(self, session: SessionData) -> List[Dict[str, Any]]:
        """Generate quotes based on session data."""
        customer_data = session.customer_data
        age = self._calculate_age_from_session(session)
        
        quotes = quote_calculator.generate_quotes(
            customer_age=age,
            sum_assured=customer_data["sum_assured"],
            policy_term=int(customer_data["policy_term"]),
            premium_paying_term=int(customer_data["premium_paying_term"]),
            customer_profile=customer_data
        )
        
        # Store quotes in session
        session.quote_data = {"quotes": quotes, "generated_at": str(date.today())}
        
        logger.info(f"Generated {len(quotes)} quotes for session {session.session_id}")
        return quotes
    
    def _calculate_age_from_session(self, session: SessionData) -> int:
        """Calculate customer age from session data."""
        if "date_of_birth" in session.customer_data:
            dob = session.customer_data["date_of_birth"]
            if isinstance(dob, str):
                from datetime import datetime
                dob = datetime.fromisoformat(dob).date()
            
            today = date.today()
            return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        
        return session.customer_data.get("age", 30)  # Fallback
    
    def can_transition_to(self, target_state: SessionState) -> bool:
        """Check if transition to target state is allowed."""
        return target_state in self.allowed_transitions
    
    def is_state_complete(self, session: SessionData) -> bool:
        """Check if quote generation is complete."""
        missing_fields = self.get_missing_fields(session)
        has_selected_variant = hasattr(session, 'selected_variant') and session.selected_variant
        return len(missing_fields) == 0 and has_selected_variant