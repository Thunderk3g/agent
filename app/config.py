from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    session_secret_key: str = "your-secret-key-change-in-production"
    api_cors_origins: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    environment: str = "development"
    log_level: str = "INFO"
    
    # Insurance product configuration
    product_config_path: str = "data/etouch.json"
    customer_template_path: str = "data/data.json"
    
    # Session management
    session_expire_hours: int = 24
    max_session_memory: int = 1000  # Maximum number of active sessions
    
    # Document upload settings
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    allowed_extensions: List[str] = ["pdf", "jpg", "jpeg", "png"]
    upload_directory: str = "uploads"
    
    # Ollama service settings
    ollama_timeout: int = 30
    ollama_max_retries: int = 3
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()

# Ensure upload directory exists
os.makedirs(settings.upload_directory, exist_ok=True)