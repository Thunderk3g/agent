from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from enum import Enum
import uuid


class Variant(str, Enum):
    LIFE_SHIELD = "Life Shield"
    LIFE_SHIELD_PLUS = "Life Shield Plus" 
    LIFE_SHIELD_ROP = "Life Shield ROP"


class PaymentFrequency(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"  
    HALF_YEARLY = "half_yearly"
    YEARLY = "yearly"


class PremiumAmounts(BaseModel):
    annual_premium_reported: Optional[str] = None
    modal_prem_raw: Optional[float] = None
    modal_premium_tax_inclusive_raw: Optional[float] = None
    base_premium: Optional[float] = None
    gst_amount: Optional[float] = None
    total_premium: Optional[float] = None


class QuoteDetails(BaseModel):
    variant_type: Optional[Variant] = None
    product_uin: str = "116N198V04"
    sum_assured: Optional[float] = None
    frequency: Optional[PaymentFrequency] = None
    frequency_label: Optional[str] = None
    premium_paying_term_years: Optional[int] = None
    policy_term_years: Optional[int] = None
    pay_for: Optional[str] = None
    cover_till_age: Optional[str] = None
    payout_nominee_option: Optional[str] = None
    premium_holiday_selected_years: Optional[int] = None
    quotation_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    transaction_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    premium_amounts: PremiumAmounts = PremiumAmounts()
    
    # Additional quote details
    life_stage_upgrade_opted: bool = False
    auto_cover_continuance_opted: bool = False
    
    @validator('cover_till_age', always=True)
    def calculate_cover_till_age(cls, v, values):
        if v:
            return v
        
        # This would need customer age and policy term
        # For now, return None - will be calculated in service layer
        return None


class Rider(BaseModel):
    name: str
    uin: str
    sum_assured: Optional[float] = None
    premium: Optional[float] = None
    selected: bool = False


class AddOns(BaseModel):
    riders_selected: List[Rider] = []
    rider_premium_total: Optional[float] = None
    coverage_value: Optional[float] = None
    accidental_value: Optional[float] = None
    protection_for: Optional[str] = None
    selected_rider_array: List[Dict[str, Any]] = []


class PolicyDocument(BaseModel):
    document_type: str
    file_path: str
    generated_at: datetime
    version: str = "1.0"


class Benefit(BaseModel):
    benefit_type: str
    amount: float
    description: str
    conditions: Optional[List[str]] = None


class PolicyData(BaseModel):
    policy_number: Optional[str] = None
    application_number: Optional[str] = None
    issue_date: Optional[date] = None
    commencement_date: Optional[date] = None
    maturity_date: Optional[date] = None
    
    # Policy status
    status: str = "ACTIVE"  # ACTIVE, LAPSED, SURRENDERED, MATURED, etc.
    
    # Premium information
    next_premium_due: Optional[date] = None
    total_premiums_paid: float = 0.0
    
    # Benefits
    death_benefit: Optional[Benefit] = None
    maturity_benefit: Optional[Benefit] = None
    surrender_benefit: Optional[Benefit] = None
    
    # Policy documents
    documents: List[PolicyDocument] = []
    
    # Nominee information
    nominee_details: Optional[Dict[str, Any]] = None


class Quote(BaseModel):
    """Complete quote model combining customer selection and calculations."""
    quote_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_age: int
    quote_details: QuoteDetails = QuoteDetails()
    add_ons: AddOns = AddOns()
    
    # Calculated values
    annual_premium: Optional[float] = None
    modal_premium: Optional[float] = None
    total_premium_payable: Optional[float] = None
    
    # Discounts applied
    applicable_discounts: List[str] = []
    discount_amount: float = 0.0
    
    # Quote metadata
    created_at: datetime = Field(default_factory=datetime.now)
    valid_until: Optional[datetime] = None
    
    def calculate_modal_premium(self, modal_factors: Dict[str, float]) -> float:
        """Calculate modal premium based on frequency."""
        if not self.annual_premium or not self.quote_details.frequency:
            return 0.0
            
        frequency = self.quote_details.frequency.value
        modal_factor = modal_factors.get(frequency, 1.0)
        return self.annual_premium * modal_factor
    
    def is_valid(self) -> bool:
        """Check if quote is still valid."""
        if not self.valid_until:
            return True
        return datetime.now() < self.valid_until


class Policy(BaseModel):
    """Complete policy model after issuance."""
    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    quote: Quote
    policy_data: PolicyData = PolicyData()
    
    # Policy lifecycle
    issued_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
    
    def update_policy_data(self, updates: Dict[str, Any]):
        """Update policy data and timestamp."""
        for key, value in updates.items():
            if hasattr(self.policy_data, key):
                setattr(self.policy_data, key, value)
        self.last_updated = datetime.now()


# Product configuration models
class VariantConfig(BaseModel):
    name: str
    death_benefit: bool
    terminal_illness: bool
    adb: bool
    wop_atpd_ti: bool
    return_of_premium: bool
    features: List[str] = []
    exclusions: List[str] = []


class EligibilityLimits(BaseModel):
    min_entry_age: int = 18
    max_entry_age: int = 65
    max_maturity_age: int = 99
    min_policy_term: int = 10
    max_policy_term: int = 50
    min_sum_assured: float = 5000000
    max_sum_assured: Optional[float] = None


class ProductConfig(BaseModel):
    """Product configuration loaded from etouch.json."""
    product_name: str = "Bajaj Allianz Life eTouch II"
    uin: str = "116N198V04"
    variants: Dict[str, VariantConfig] = {}
    eligibility_limits: EligibilityLimits = EligibilityLimits()
    modal_factors: Dict[str, float] = {
        "monthly": 0.0875,
        "quarterly": 0.26, 
        "half_yearly": 0.51,
        "yearly": 1.0
    }
    discounts: Dict[str, str] = {}
    available_riders: List[Rider] = []