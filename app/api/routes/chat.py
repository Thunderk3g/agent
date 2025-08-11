from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from app.models.chat_response import ChatRequest, ChatResponse
from app.models.session import SessionData, session_manager
from app.services.agent_orchestrator import agent_orchestrator
from app.utils.logging import logger

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/message", response_model=ChatResponse)
async def process_chat_message(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint - processes user messages through LLM agent orchestrator.
    
    This endpoint handles the conversational AI interface with unified memory state.
    """
    try:
        logger.info(f"Processing chat message for session: {request.session_id}")
        
        # Process through agent orchestrator - unified memory handling
        response = await agent_orchestrator.handle_turn(
            request.session_id,
            request.message,
            request.attachments
        )
        
        # Convert to ChatResponse format
        chat_response = ChatResponse(
            session_id=response["session_id"],
            message=response["message"],
            actions=response["actions"],
            current_state=response["current_state"],
            data_collection=response["data_collection"],
            metadata=response.get("metadata", {})
        )
        
        logger.info(f"Chat response generated for session: {chat_response.session_id}")
        return chat_response
        
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
        # Create new session through session manager
        session = session_manager.create_session()
        
        return {
            "session_id": session.session_id,
            "current_state": session.current_state.value,
            "created_at": session.created_at.isoformat(),
            "initial_message": "Hello! I'm here to help you with your life insurance needs. Let me start by collecting some basic information. What's your full name?"
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
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {
            "session_id": session.session_id,
            "current_state": session.current_state.value,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "customer_data": session.customer_data,
            "quote_data": session.quote_data,
            "form_completion": session.form_completion,
            "conversation_turns": len(session.conversation_history),
            "selected_variant": session.selected_variant,
            "policy_data": session.policy_data
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
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {
            "session_id": session.session_id,
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
            ]
        }
        
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
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Reset session data
        session.customer_data = {}
        session.quote_data = {}
        session.policy_data = {}
        session.conversation_history = []
        session.state_transitions = []
        from app.models.session import SessionState
        session.current_state = SessionState.ONBOARDING
        session.form_completion = {
            "personal_details": {"completed": False, "completion_percentage": 0},
            "insurance_requirements": {"completed": False, "completion_percentage": 0},
            "rider_selection": {"completed": False, "completion_percentage": 0},
            "payment_details": {"completed": False, "completion_percentage": 0}
        }
        
        session_manager.update_session(session)
        
        return {"message": "Session reset successfully", "session_id": session_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset session: {str(e)}"
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
            "agent_orchestrator": "operational"
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "degraded",
            "error": str(e)
        }