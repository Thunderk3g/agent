from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.services.agent_orchestrator import agent_orchestrator
from app.services.ollama_service import ollama_service
from app.models.session import session_manager


router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentTurnRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    attachments: Optional[list] = None


@router.post("/turn")
async def agent_turn(req: AgentTurnRequest) -> Dict[str, Any]:
    return await agent_orchestrator.handle_turn(
        session_id=req.session_id,
        user_message=req.message,
        attachments=req.attachments,
    )


@router.post("/turn/stream")
async def agent_turn_stream(req: AgentTurnRequest):
    async def token_stream():
        # Simple streaming of the final composed reply for now
        result = await agent_orchestrator.handle_turn(
            session_id=req.session_id,
            user_message=req.message,
            attachments=req.attachments,
        )
        # Break message into pseudo tokens for streaming UX
        for chunk in result.get("message", "").split(" "):
            yield chunk + " "
        yield "\n"
    return StreamingResponse(token_stream(), media_type="text/plain")


class FormDataSyncRequest(BaseModel):
    session_id: str
    form_data: Dict[str, Any]


@router.post("/sync-form-data")
async def sync_form_data(req: FormDataSyncRequest) -> Dict[str, Any]:
    """
    Sync form data with backend session to ensure unified memory state.
    """
    try:
        session = session_manager.get_session(req.session_id)
        if not session:
            return {"error": "Session not found", "success": False}
        
        # Update session with frontend form data structure
        if req.form_data:
            session.update_frontend_data(req.form_data)
            session_manager.update_session(session)
        
        return {
            "success": True,
            "session_id": session.session_id,
            "updated_data": {
                "customer_data": session.customer_data,
                "quote_data": session.quote_data,
                "form_completion": session.form_completion
            }
        }
        
    except Exception as e:
        return {"error": str(e), "success": False}


@router.get("/session-data/{session_id}")
async def get_session_data(session_id: str) -> Dict[str, Any]:
    """
    Get session data formatted for frontend forms pre-population.
    """
    try:
        session = session_manager.get_session(session_id)
        if not session:
            return {"error": "Session not found", "success": False}
        
        # Map backend data to frontend form structure
        personal_details = {}
        quote_details = {}
        
        # Map customer_data to frontend personalDetails
        customer_data = session.customer_data
        if customer_data:
            field_mapping = {
                "full_name": "fullName",
                "date_of_birth": "dateOfBirth", 
                "age": "age",
                "gender": "gender",
                "mobile_number": "mobileNumber",
                "email": "email",
                "pin_code": "pinCode",
                "smoker": "tobaccoUser",
                "annual_income": "annualIncome"
            }
            for backend_key, frontend_key in field_mapping.items():
                if backend_key in customer_data and customer_data[backend_key] is not None:
                    personal_details[frontend_key] = customer_data[backend_key]
        
        # Map quote_data to frontend quoteDetails
        quote_data = session.quote_data
        if quote_data:
            quote_mapping = {
                "coverage_amount": "sumAssured",
                "policy_term": "policyTerm_years",
                "premium_paying_term": "premiumPayingTerm_years",
                "premium_frequency": "frequency"
            }
            for backend_key, frontend_key in quote_mapping.items():
                if backend_key in quote_data and quote_data[backend_key] is not None:
                    quote_details[frontend_key] = quote_data[backend_key]
        
        return {
            "success": True,
            "session_id": session.session_id,
            "current_state": session.current_state.value,
            "form_data": {
                "personalDetails": personal_details,
                "quoteDetails": quote_details,
                "paymentDetails": session.payment_data,
                "formCompletion": session.form_completion
            }
        }
        
    except Exception as e:
        return {"error": str(e), "success": False}


