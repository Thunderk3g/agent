from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from app.config import settings
from app.utils.logging import setup_logging, logger
from app.api.routes import chat
from app.states.base_state import state_registry
from app.states.onboarding import OnboardingState
from app.states.eligibility_check import EligibilityCheckState
from app.states.quote_generation import QuoteGenerationState
from app.states.payment_redirect import PaymentRedirectState


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting eTouch Insurance Backend")
    
    # Setup logging
    setup_logging()
    
    # Register all states
    logger.info("Registering application states...")
    state_registry.register_state(OnboardingState())
    state_registry.register_state(EligibilityCheckState())
    state_registry.register_state(QuoteGenerationState())
    state_registry.register_state(PaymentRedirectState())
    
    logger.info(f"Registered {len(state_registry.get_all_states())} states")
    
    # Check Ollama connection
    from app.services.ollama_service import ollama_service
    ollama_healthy = await ollama_service.health_check()
    if ollama_healthy:
        logger.info("✅ Ollama service is available")
    else:
        logger.warning("⚠️ Ollama service is not available - using fallback responses")
    
    yield
    
    # Shutdown
    logger.info("Shutting down eTouch Insurance Backend")


# Create FastAPI application
app = FastAPI(
    title="Bajaj Allianz eTouch II Insurance Backend",
    description="AI-powered insurance agent backend with conversational interface",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    redirect_slashes=False  # Prevent automatic redirects that cause CORS issues
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False if settings.environment == "development" else True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include routers
app.include_router(chat.router)
try:
    from app.api.routes import documents
    app.include_router(documents.router)
except Exception:
    # Documents router is optional; ignore if unavailable
    pass

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Bajaj Allianz eTouch II Insurance Backend",
        "version": "1.0.0",
        "docs": "/docs",
        "chat_endpoint": "/api/chat/message",
        "health": "/api/chat/health"
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    """Application health check."""
    try:
        return {
            "status": "healthy",
            "service": "etouch-insurance-backend",
            "version": "1.0.0",
            "environment": settings.environment
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {str(exc)}")
    return HTTPException(
        status_code=500,
        detail="An unexpected error occurred. Please try again later."
    )

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower()
    )