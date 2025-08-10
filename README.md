# Bajaj Allianz eTouch II Insurance Backend

AI-powered insurance agent backend with conversational interface for the eTouch II insurance product lifecycle management.

## Features

- **Chat-GPT like Interface**: Conversational AI interface for customer interactions
- **State Machine**: Manages insurance process flow through different stages
- **Dynamic Forms**: Frontend-triggered forms based on current state and missing data
- **Quote Generation**: Real-time premium calculation with multiple variants
- **Payment Integration**: Ready for payment gateway integration
- **Document Processing**: Upload and AI analysis of KYC documents
- **Ollama Integration**: Local LLM integration with fallback mechanisms

## Architecture

### State Machine Flow
```
Onboarding → Eligibility Check → Quote Generation → Underwriting → Policy Issuance → Active Policy
     ↓              ↓                    ↓              ↓              ↓             ↓
Document Collection Premium Holiday  Claims Processing
```

### Key Components
- **FastAPI Application**: RESTful API with automatic documentation
- **State Management**: Each state handles specific business logic and form generation
- **Ollama Service**: AI conversation handling with retry mechanisms
- **Quote Calculator**: Premium calculation using product configuration
- **Response Formatter**: Structures responses for frontend consumption

## Installation

### Prerequisites
- Python 3.8+
- Ollama running locally at `http://localhost:11434`
- Llama 3 or Mistral model loaded in Ollama

### Setup

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment Configuration**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start Ollama** (if not running)
   ```bash
   ollama serve
   ollama pull llama3
   ```

4. **Run the Application**
   ```bash
   python -m app.main
   ```

   Or using uvicorn:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

## API Endpoints

### Chat Interface
- `POST /api/chat/message` - Main chat endpoint
- `POST /api/chat/session/start` - Start new session
- `GET /api/chat/session/{id}` - Get session info
- `GET /api/chat/session/{id}/history` - Get conversation history

### Health & Admin
- `GET /health` - Application health check
- `GET /api/chat/health` - Detailed service health
- `POST /api/chat/session/{id}/reset` - Reset session

## Request/Response Format

### Chat Request
```json
{
  "session_id": "uuid-string",
  "message": "I want to buy life insurance",
  "form_data": {
    "full_name": "John Doe",
    "email": "john@example.com"
  },
  "action_data": {
    "action": "select_variant",
    "variant": "Life Shield Plus"
  }
}
```

### Chat Response
```json
{
  "message": "AI response text for chat bubble",
  "session_id": "uuid-string",
  "current_state": "onboarding",
  "actions": [
    {
      "type": "form",
      "title": "Personal Information",
      "fields": [
        {
          "name": "full_name",
          "label": "Full Name",
          "type": "text",
          "required": true
        }
      ]
    }
  ],
  "data_collection": {
    "collected": ["email"],
    "missing": ["full_name", "date_of_birth"],
    "completion_percentage": 25
  }
}
```

## Configuration

### Environment Variables
- `OLLAMA_BASE_URL`: Ollama server URL (default: http://localhost:11434)
- `OLLAMA_MODEL`: Model to use (default: llama3)
- `API_CORS_ORIGINS`: Allowed CORS origins
- `ENVIRONMENT`: development/production
- `LOG_LEVEL`: Logging level

### Product Configuration
- `data/etouch.json`: Product rules and configuration
- `data/data.json`: Customer data template

## Development

### Project Structure
```
etouch-backend/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── config.py              # Configuration management
│   ├── models/                # Pydantic models
│   ├── services/              # Business logic services
│   ├── states/                # State machine states
│   ├── api/routes/            # API endpoints
│   └── utils/                 # Utility functions
├── data/                      # Product configuration
├── tests/                     # Test files
└── requirements.txt
```

### Adding New States
1. Create state class inheriting from `BaseState`
2. Implement required methods: `enter`, `process_message`, `can_transition_to`
3. Register state in `main.py`
4. Update state machine transitions

### Testing

The application includes health checks and detailed logging for debugging:

```bash
# Check application health
curl http://localhost:8000/health

# Check Ollama connectivity
curl http://localhost:8000/api/chat/health

# Start a new session
curl -X POST http://localhost:8000/api/chat/session/start

# Send a chat message
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, I want to buy insurance"}'
```

## Insurance Product Features

### Variants Supported
- **Life Shield**: Basic term insurance with death and terminal illness cover
- **Life Shield Plus**: Includes accidental death benefit (ADB)
- **Life Shield ROP**: Return of Premium at maturity

### Key Features
- Age eligibility: 18-65 years
- Sum assured: ₹50 lakh minimum
- Premium holiday options (1-3 years)
- Life stage upgrades for major life events
- Comprehensive claims processing

## Deployment

### Production Checklist
- [ ] Set environment to "production"
- [ ] Configure proper CORS origins
- [ ] Set up SSL/TLS certificates
- [ ] Configure logging to files
- [ ] Set up monitoring and alerting
- [ ] Configure database for session persistence (Redis recommended)
- [ ] Set up payment gateway integration

### Docker Deployment
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "-m", "app.main"]
```

## License

This project is proprietary to Bajaj Allianz General Insurance Company Limited.

## Support

For technical support or questions about the insurance products, contact:
- Technical Support: [Your contact information]
- Insurance Queries: 1800 209 7272
- Email: customercare@bajajallianz.co.in