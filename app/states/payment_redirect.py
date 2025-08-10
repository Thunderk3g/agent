from typing import Dict, Any, List
from app.states.base_state import BaseState
from app.models.session import SessionData, SessionState
from app.models.chat_response import ChatResponse, PaymentRedirectAction, PaymentDetails
from app.services.ollama_service import ollama_service
from app.utils.logging import logger
import uuid


class PaymentRedirectState(BaseState):
    """Final state that redirects to external payment gateway."""
    
    def __init__(self):
        super().__init__(SessionState.PAYMENT_REDIRECT)
        self.allowed_transitions = []  # Terminal state
        self.required_fields = []
    
    async def enter(self, session: SessionData, context: Dict[str, Any] = None) -> ChatResponse:
        """Enter payment redirect state with external payment setup."""
        
        selected_quote = session.quote_data.get("selected_quote", {})
        if not selected_quote:
            logger.error(f"No selected quote found for payment redirect in session {session.session_id}")
            return self.create_basic_response(
                session=session,
                message="I'm sorry, but I couldn't find your selected quote. Please go back and select a plan.",
                actions=[],
                metadata={"error": "no_selected_quote"}
            )
        
        # Generate message about proceeding to payment
        payment_message = await ollama_service.process_state_message(
            session,
            f"User has selected {selected_quote['name']} and is ready to make payment of ₹{selected_quote['annual_premium']}",
            {"entering_payment": True, "selected_quote": selected_quote}
        )
        
        # Create payment redirect action
        payment_action = self._create_payment_redirect(session, selected_quote)
        
        # Store payment preparation details
        session.payment_data = {
            "quote_id": selected_quote.get("quote_id", str(uuid.uuid4())),
            "variant": selected_quote["name"],
            "sum_assured": selected_quote["sum_assured"],
            "annual_premium": selected_quote["annual_premium"],
            "payment_frequency": session.customer_data.get("payment_frequency", "yearly"),
            "customer_details": self._prepare_customer_details(session),
            "redirect_prepared": True
        }
        
        return self.create_basic_response(
            session=session,
            message=payment_message,
            actions=[payment_action],
            metadata={
                "payment_stage": "redirect",
                "quote_selected": selected_quote["name"],
                "premium_amount": selected_quote["annual_premium"]
            }
        )
    
    async def process_message(self, session: SessionData, user_message: str,
                            form_data: Dict[str, Any] = None,
                            action_data: Dict[str, Any] = None) -> ChatResponse:
        """Process messages in payment redirect state."""
        
        if action_data and action_data.get("action") == "proceed_payment":
            return await self._handle_payment_initiation(session, user_message, action_data)
        
        return await self._handle_conversation(session, user_message)
    
    async def _handle_payment_initiation(self, session: SessionData, user_message: str,
                                       action_data: Dict[str, Any]) -> ChatResponse:
        """Handle payment initiation."""
        
        ai_response = await ollama_service.process_state_message(
            session,
            "User is proceeding to external payment gateway",
            {"payment_initiated": True}
        )
        
        # Create final payment redirect
        selected_quote = session.quote_data["selected_quote"]
        payment_action = self._create_payment_redirect(session, selected_quote)
        
        return self.create_basic_response(
            session=session,
            message=ai_response + "\n\n🔐 You'll be redirected to our secure payment gateway to complete your purchase.",
            actions=[payment_action],
            metadata={
                "payment_initiated": True,
                "redirect_url": payment_action.redirect_url
            }
        )
    
    async def _handle_conversation(self, session: SessionData, user_message: str) -> ChatResponse:
        """Handle general conversation in payment state."""
        
        ai_response = await ollama_service.process_state_message(
            session,
            user_message,
            {"conversation_context": "payment_redirect"}
        )
        
        # Always show payment option
        selected_quote = session.quote_data.get("selected_quote", {})
        actions = []
        
        if selected_quote:
            payment_action = self._create_payment_redirect(session, selected_quote)
            actions.append(payment_action)
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=actions,
            metadata={"conversation_response": True}
        )
    
    def _create_payment_redirect(self, session: SessionData, selected_quote: Dict[str, Any]) -> PaymentRedirectAction:
        """Create payment redirect action for external gateway."""
        
        # Calculate modal premium based on selected frequency
        frequency = session.customer_data.get("payment_frequency", "yearly")
        annual_premium = selected_quote["annual_premium"]
        
        # Get modal premium (first payment amount)
        modal_premiums = selected_quote.get("modal_premiums", {})
        payment_amount = modal_premiums.get(frequency, annual_premium)
        
        payment_details = PaymentDetails(
            amount=payment_amount,
            currency="INR",
            premium_frequency=frequency,
            variant_name=selected_quote["name"],
            sum_assured=selected_quote["sum_assured"],
            policy_term=selected_quote["policy_term"],
            premium_paying_term=selected_quote["premium_paying_term"]
        )
        
        # Generate unique order ID for payment gateway
        order_id = f"ETH{session.session_id[:8]}{str(uuid.uuid4())[:8].upper()}"
        
        # Create redirect URL with parameters
        redirect_url = f"/api/payment/initiate?order_id={order_id}&session_id={session.session_id}"
        
        return PaymentRedirectAction(
            title="Complete Your Purchase",
            description=f"Proceed with {frequency} premium payment of ₹{payment_amount:,.2f} for your {selected_quote['name']} policy.",
            payment_details=payment_details,
            redirect_url=redirect_url,
            payment_gateway="external"
        )
    
    def _prepare_customer_details(self, session: SessionData) -> Dict[str, Any]:
        """Prepare customer details for payment gateway."""
        
        customer_data = session.customer_data
        
        return {
            "name": customer_data.get("full_name", ""),
            "email": customer_data.get("email", ""),
            "phone": customer_data.get("mobile_number", ""),
            "age": customer_data.get("age", 0),
            "gender": customer_data.get("gender", ""),
            "address": {
                "pin_code": customer_data.get("pin_code", ""),
                "state": customer_data.get("state", "")
            }
        }
    
    def can_transition_to(self, target_state: SessionState) -> bool:
        """Payment redirect is terminal state."""
        return False
    
    def is_state_complete(self, session: SessionData) -> bool:
        """Payment redirect state is always complete once entered."""
        return True
    
    def get_completion_message(self, session: SessionData) -> str:
        """Get completion message for payment redirect."""
        return "Perfect! Your insurance application is complete. You'll now be redirected to make your payment and activate your policy."