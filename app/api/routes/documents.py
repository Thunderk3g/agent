from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Dict
from uuid import uuid4
import os

from app.config import settings
from app.utils.logging import logger


router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload", response_model=Dict[str, str])
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    session_id: str = Form(...),
) -> Dict[str, str]:
    try:
        # Validate extension
        filename = file.filename or "uploaded_file"
        extension = filename.split(".")[-1].lower() if "." in filename else ""
        if extension not in settings.allowed_extensions:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: .{extension}")

        # Read content and validate size
        content = await file.read()
        if len(content) > settings.max_file_size:
            raise HTTPException(status_code=400, detail="File too large")

        # Build destination path
        session_dir = os.path.join(settings.upload_directory, session_id)
        os.makedirs(session_dir, exist_ok=True)

        safe_name = f"{uuid4().hex}_{os.path.basename(filename)}"
        dest_path = os.path.join(session_dir, safe_name)

        # Save file
        with open(dest_path, "wb") as out:
            out.write(content)

        logger.info(
            f"Uploaded document for session {session_id}: type={document_type}, path={dest_path}"
        )

        return {"file_path": dest_path.replace("\\", "/")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upload document")


