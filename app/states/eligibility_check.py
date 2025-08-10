from typing import Dict, Any, List
from app.states.base_state import BaseState
from app.models.session import SessionData, SessionState
from app.models.chat_response import ChatResponse
from app.services.ollama_service import ollama_service
from app.services.response_formatter import response_formatter
from app.utils.logging import logger
from datetime import date


class EligibilityCheckState(BaseState):
    """State for checking customer eligibility for insurance."""
    
    def __init__(self):
        super().__init__(SessionState.ELIGIBILITY_CHECK)
        self.allowed_transitions = [
            SessionState.QUOTE_GENERATION,
            SessionState.ONBOARDING  # Back if not eligible
        ]
        self.required_fields = [
            "occupation", "health_condition", "family_medical_history"
        ]
    
    async def enter(self, session: SessionData, context: Dict[str, Any] = None) -> ChatResponse:
        """Enter eligibility check state."""
        # First do basic eligibility checks
        eligibility_result = self._check_basic_eligibility(session)
        
        if not eligibility_result["eligible"]:
            # Not eligible, explain why
            message = await ollama_service.process_state_message(
                session,
                f"User not eligible: {eligibility_result['reason']}",
                {"eligibility_result": eligibility_result}
            )
            
            return self.create_basic_response(
                session=session,
                message=message,
                actions=[],
                metadata={
                    "eligible": False,
                    "reason": eligibility_result["reason"]
                }
            )
        
        # Basic eligibility passed, get additional details
        welcome_message = await ollama_service.process_state_message(
            session,
            "Starting eligibility assessment - user passed basic checks",
            {"basic_eligibility": eligibility_result}
        )
        
        missing_fields = self.get_missing_fields(session)
        actions = []
        
        if missing_fields:
            eligibility_form = response_formatter.format_eligibility_form(session)
            actions.append(eligibility_form)
        
        return self.create_basic_response(
            session=session,
            message=welcome_message,
            actions=actions,
            metadata={
                "basic_eligibility": eligibility_result,
                "assessment_stage": "detailed_check"
            }
        )
    
    async def process_message(self, session: SessionData, user_message: str,
                            form_data: Dict[str, Any] = None,
                            action_data: Dict[str, Any] = None) -> ChatResponse:
        """Process eligibility assessment messages."""
        
        if form_data:
            return await self._handle_eligibility_form(session, user_message, form_data)
        
        return await self._handle_conversation(session, user_message)
    
    async def _handle_eligibility_form(self, session: SessionData, user_message: str,
                                     form_data: Dict[str, Any]) -> ChatResponse:
        """Handle eligibility form submission."""
        # Update session with eligibility data
        self.update_session_data(session, form_data)
        
        # Perform detailed eligibility assessment
        detailed_eligibility = self._check_detailed_eligibility(session, form_data)
        
        # Generate AI response based on eligibility
        ai_response = await ollama_service.process_state_message(
            session,
            f"Eligibility assessment completed: {detailed_eligibility}",
            {
                "form_data": form_data,
                "eligibility_result": detailed_eligibility
            }
        )
        
        # Store eligibility result in session
        session.customer_data["eligibility_status"] = detailed_eligibility["status"]
        session.customer_data["risk_profile"] = detailed_eligibility["risk_profile"]
        
        actions = []
        metadata = {
            "eligibility_completed": True,
            "eligible": detailed_eligibility["eligible"],
            "risk_profile": detailed_eligibility["risk_profile"]
        }
        
        if detailed_eligibility["eligible"]:
            # Eligible - suggest moving to quote generation
            ai_response += f"\n\n🎉 Great news! You're eligible for our insurance plans with a {detailed_eligibility['risk_profile']} risk profile. Let's generate your personalized quotes!"
            metadata["ready_for_quotes"] = True
        else:
            # Not eligible
            ai_response += f"\n\nI'm sorry, but based on your profile, you may not be eligible for our standard plans. {detailed_eligibility.get('reason', '')}"
            metadata["ineligible_reason"] = detailed_eligibility.get("reason")
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=actions,
            metadata=metadata
        )
    
    async def _handle_conversation(self, session: SessionData, user_message: str) -> ChatResponse:
        """Handle general conversation during eligibility check."""
        ai_response = await ollama_service.process_state_message(
            session,
            user_message,
            {"conversation_context": "eligibility_check"}
        )
        
        missing_fields = self.get_missing_fields(session)
        actions = []
        
        # Show eligibility form if user asks about eligibility or we need info
        if (any(keyword in user_message.lower() for keyword in ["eligible", "qualify", "check", "assess"]) 
            or missing_fields):
            eligibility_form = response_formatter.format_eligibility_form(session)
            actions.append(eligibility_form)
        
        return self.create_basic_response(
            session=session,
            message=ai_response,
            actions=actions,
            metadata={"conversation_response": True}
        )
    
    def _check_basic_eligibility(self, session: SessionData) -> Dict[str, Any]:
        """Check basic eligibility criteria."""
        customer_data = session.customer_data
        
        # Age check
        if "date_of_birth" in customer_data:
            dob = customer_data["date_of_birth"]
            if isinstance(dob, str):
                from datetime import datetime
                dob = datetime.fromisoformat(dob).date()
            
            age = self._calculate_age(dob)
            
            if age < 18:
                return {
                    "eligible": False,
                    "reason": "You must be at least 18 years old to purchase this insurance.",
                    "age": age
                }
            
            if age > 65:
                return {
                    "eligible": False,
                    "reason": "The maximum entry age for this insurance is 65 years.",
                    "age": age
                }
        
        # Income check (minimum requirement)
        if "annual_income" in customer_data:
            annual_income = customer_data["annual_income"]
            if annual_income < 100000:  # 1 lakh minimum
                return {
                    "eligible": False,
                    "reason": "Minimum annual income requirement is ₹1,00,000 for this insurance plan."
                }
        
        # All basic checks passed
        return {
            "eligible": True,
            "reason": "Passed basic eligibility checks",
            "checks_passed": ["age", "income", "nationality"]
        }
    
    def _check_detailed_eligibility(self, session: SessionData, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check detailed eligibility based on health and occupation."""
        health_condition = form_data.get("health_condition")
        occupation = form_data.get("occupation")
        family_history = form_data.get("family_medical_history")
        
        risk_factors = []
        risk_score = 0
        
        # Health assessment
        if health_condition == "major":
            risk_factors.append("major_health_conditions")
            risk_score += 3
        elif health_condition == "minor":
            risk_factors.append("minor_health_conditions")
            risk_score += 1
        
        # Family history
        if family_history == "true":
            risk_factors.append("family_medical_history")
            risk_score += 1
        
        # Occupation assessment
        high_risk_occupations = ["mining", "aviation", "defense", "stunt"]
        if any(risk_job in occupation.lower() for risk_job in high_risk_occupations):
            risk_factors.append("high_risk_occupation")
            risk_score += 2
        
        # Tobacco usage
        if session.customer_data.get("tobacco_user"):
            risk_factors.append("tobacco_usage")
            risk_score += 2
        
        # Determine eligibility and risk profile
        if risk_score >= 5:
            return {
                "eligible": False,
                "status": "high_risk_ineligible",
                "risk_profile": "high",
                "risk_factors": risk_factors,
                "reason": "Based on your health profile and risk factors, you may require special underwriting. Please contact our underwriting team."
            }
        elif risk_score >= 3:
            return {
                "eligible": True,
                "status": "eligible_with_conditions",
                "risk_profile": "medium",
                "risk_factors": risk_factors,
                "conditions": ["medical_checkup_required", "higher_premium"]
            }
        elif risk_score >= 1:
            return {
                "eligible": True,
                "status": "eligible_standard",
                "risk_profile": "low_medium",
                "risk_factors": risk_factors
            }
        else:
            return {
                "eligible": True,
                "status": "eligible_preferred",
                "risk_profile": "low",
                "risk_factors": risk_factors,
                "benefits": ["preferential_rates", "fast_track_processing"]
            }
    
    def _calculate_age(self, birth_date: date) -> int:
        """Calculate age from birth date."""
        today = date.today()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    
    def can_transition_to(self, target_state: SessionState) -> bool:
        """Check if transition to target state is allowed."""
        return target_state in self.allowed_transitions
    
    def is_state_complete(self, session: SessionData) -> bool:
        """Check if eligibility assessment is complete."""
        missing_fields = self.get_missing_fields(session)
        has_eligibility_status = "eligibility_status" in session.customer_data
        return len(missing_fields) == 0 and has_eligibility_status