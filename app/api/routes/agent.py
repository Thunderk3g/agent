from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.services.agent_orchestrator import agent_orchestrator
from app.services.ollama_service import ollama_service


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


