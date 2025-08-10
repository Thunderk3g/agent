from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional
from app.models.chat_response import ChatRequest, ChatResponse
from app.models.session import SessionData, session_manager
from app.services.state_machine import state_machine
from app.utils.logging import logger

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/message", response_model=ChatResponse)
async def process_chat_message(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint - processes user messages and returns structured responses.
    
    This endpoint handles the conversational AI interface and manages state transitions
    through the insurance application process.
    """
    try:
        logger.info(f"Processing chat message for session: {request.session_id}")
        
        # Process through state machine
        response = await state_machine.process_chat_request(request)
        
        # Check if we should auto-advance to next state
        if request.session_id:
            session = await state_machine.get_session(request.session_id)
            if session:
                auto_advance_response = await state_machine.auto_advance_if_ready(session)
                if auto_advance_response:
                    # Return the auto-advanced response instead
                    response = auto_advance_response
        
        logger.info(f"Chat response generated for session: {response.session_id}")
        return response
        
    except Exception as e:
        logger.error(f"Error processing chat message: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process message: {str(e)}"
        )


@router.post("/session/start", response_model=Dict[str, Any])
async def start_new_session() -> Dict[str, Any]:
    """
    Start a new insurance application session.
    
    Returns session information including session_id for subsequent requests.
    """
    try:
        session = await state_machine.start_new_session()
        
        # Initialize the session with onboarding state
        from app.states.base_state import state_registry
        from app.models.session import SessionState
        
        onboarding_state = state_registry.get_state(SessionState.ONBOARDING)
        if onboarding_state:
            initial_response = await onboarding_state.enter(session)
            
            return {
                "session_id": session.session_id,
                "current_state": session.current_state.value,
                "created_at": session.created_at.isoformat(),
                "initial_message": initial_response.message,
                "initial_actions": [action.dict() for action in initial_response.actions]
            }
        else:
            return {
                "session_id": session.session_id,
                "current_state": session.current_state.value,
                "created_at": session.created_at.isoformat(),
                "message": "Session created successfully. You can now start chatting!"
            }
        
    except Exception as e:
        logger.error(f"Error starting new session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start session: {str(e)}"
        )


@router.get("/session/{session_id}", response_model=Dict[str, Any])
async def get_session_info(session_id: str) -> Dict[str, Any]:
    """
    Get current session information including state and collected data.
    """
    try:
        session = await state_machine.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {
            "session_id": session.session_id,
            "current_state": session.current_state.value,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "customer_data_collected": list(session.customer_data.keys()),
            "conversation_turns": len(session.conversation_history),
            "selected_variant": getattr(session, 'selected_variant', None),
            "policy_number": session.policy_data.get("policy_number") if hasattr(session, 'policy_data') and session.policy_data else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session info: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session info: {str(e)}"
        )


@router.get("/session/{session_id}/history", response_model=Dict[str, Any])
async def get_conversation_history(session_id: str) -> Dict[str, Any]:
    """
    Get full conversation history for a session.
    """
    try:
        history = await state_machine.get_session_history(session_id)
        if not history:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return history
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation history: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get conversation history: {str(e)}"
        )


@router.post("/session/{session_id}/reset", response_model=Dict[str, str])
async def reset_session(session_id: str) -> Dict[str, str]:
    """
    Reset a session to initial state (useful for starting over).
    """
    try:
        success = await state_machine.reset_session(session_id)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {"message": "Session reset successfully", "session_id": session_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset session: {str(e)}"
        )


@router.post("/session/{session_id}/transition", response_model=ChatResponse)
async def manual_state_transition(
    session_id: str, 
    target_state: str,
    context: Optional[Dict[str, Any]] = None
) -> ChatResponse:
    """
    Manually transition session to a specific state (admin/testing use).
    """
    try:
        session = await state_machine.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        from app.models.session import SessionState
        
        try:
            target_state_enum = SessionState(target_state)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid state: {target_state}")
        
        response = await state_machine.transition_to_state(session, target_state_enum, context)
        
        logger.info(f"Manual transition: session {session_id} to {target_state}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error transitioning state: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to transition state: {str(e)}"
        )


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """
    Health check endpoint for the chat service.
    """
    try:
        # Check Ollama service
        from app.services.ollama_service import ollama_service
        ollama_healthy = await ollama_service.health_check()
        
        return {
            "status": "healthy",
            "chat_service": "operational",
            "ollama_service": "operational" if ollama_healthy else "degraded",
            "active_sessions": str(len(state_machine.current_sessions))
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "degraded",
            "error": str(e)
        }