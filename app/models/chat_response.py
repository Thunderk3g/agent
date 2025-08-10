from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from enum import Enum
import uuid


class ActionType(str, Enum):
    FORM = "form"
    DOCUMENT_UPLOAD = "document_upload"
    PAYMENT_REDIRECT = "payment_redirect"
    QUOTE_DISPLAY = "quote_display"
    CONFIRMATION = "confirmation"
    OPTIONS_SELECTION = "options_selection"


class FieldType(str, Enum):
    TEXT = "text"
    EMAIL = "email"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    TEXTAREA = "textarea"
    PHONE = "phone"


class ValidationRule(BaseModel):
    pattern: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    custom_message: Optional[str] = None


class FormField(BaseModel):
    name: str
    label: str
    type: FieldType
    required: bool = False
    placeholder: Optional[str] = None
    options: Optional[List[Dict[str, Any]]] = None  # For select, radio, checkbox
    validation: Optional[ValidationRule] = None
    default_value: Optional[str] = None
    help_text: Optional[str] = None


class FormAction(BaseModel):
    type: ActionType = ActionType.FORM
    title: str
    description: Optional[str] = None
    fields: List[FormField]
    submit_label: str = "Submit"


class DocumentUpload(BaseModel):
    name: str
    label: str
    required: bool = False
    accepted_types: List[str] = ["pdf", "jpg", "jpeg", "png"]
    max_size_mb: int = 10
    description: Optional[str] = None


class DocumentUploadAction(BaseModel):
    type: ActionType = ActionType.DOCUMENT_UPLOAD
    title: str
    description: Optional[str] = None
    documents: List[DocumentUpload]
    submit_label: str = "Upload Documents"


class PaymentDetails(BaseModel):
    amount: float
    currency: str = "INR"
    premium_frequency: str
    variant_name: str
    sum_assured: float
    policy_term: int
    premium_paying_term: int


class PaymentRedirectAction(BaseModel):
    type: ActionType = ActionType.PAYMENT_REDIRECT
    title: str
    description: Optional[str] = None
    payment_details: PaymentDetails
    redirect_url: str
    payment_gateway: str = "razorpay"


class QuoteVariant(BaseModel):
    name: str
    premium: float
    features: List[str]
    sum_assured: float
    policy_term: int
    premium_paying_term: int
    recommended: bool = False
    action: str = "select_variant"


class QuoteDisplayAction(BaseModel):
    type: ActionType = ActionType.QUOTE_DISPLAY
    title: str
    description: Optional[str] = None
    variants: List[QuoteVariant]
    comparison_features: List[str]


class OptionsSelectionAction(BaseModel):
    type: ActionType = ActionType.OPTIONS_SELECTION
    title: str
    description: Optional[str] = None
    options: List[Dict[str, Any]]
    selection_type: str = "single"  # single or multiple


class ConfirmationAction(BaseModel):
    type: ActionType = ActionType.CONFIRMATION
    title: str
    description: Optional[str] = None
    confirm_label: str = "Confirm"
    cancel_label: str = "Cancel"
    data_summary: Dict[str, Any]


class DataCollection(BaseModel):
    collected: List[str] = []
    missing: List[str] = []
    completion_percentage: int = 0
    next_required_field: Optional[str] = None


class ChatResponse(BaseModel):
    message: str
    session_id: str
    current_state: str
    actions: List[Union[
        FormAction, 
        DocumentUploadAction, 
        PaymentRedirectAction, 
        QuoteDisplayAction, 
        OptionsSelectionAction,
        ConfirmationAction
    ]] = []
    data_collection: DataCollection = DataCollection()
    metadata: Dict[str, Any] = {}
    timestamp: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    form_data: Optional[Dict[str, Any]] = None
    uploaded_documents: Optional[List[str]] = None
    selected_action: Optional[str] = None
    action_data: Optional[Dict[str, Any]] = None