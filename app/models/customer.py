from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional, List, Dict, Any
from datetime import date
from enum import Enum


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class ResidentialStatus(str, Enum):
    RESIDENT = "resident"
    NRI = "nri"
    NRI_EMERGENCY = "nri_emergency"


class PersonalDetails(BaseModel):
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    age: Optional[int] = None
    gender: Optional[Gender] = None
    mobile_number: Optional[str] = None
    mobile_number_country_code: str = "+91"
    email: Optional[EmailStr] = None
    pin_code: Optional[str] = None
    state: Optional[str] = None
    nationality: str = "Indian"
    residential_status: Optional[ResidentialStatus] = None
    is_nri: Optional[bool] = None
    is_nri_emergency: Optional[bool] = None
    is_bajaj_group_employee: Optional[bool] = None
    tobacco_user: Optional[bool] = None
    occupation_code: Optional[str] = None
    education_code: Optional[str] = None
    annual_income: Optional[float] = None
    accept_terms: bool = False
    kyc_accepted: bool = False
    enquiry_id: Optional[str] = None
    tool_free_number: Optional[str] = None

    @validator('age', always=True)
    def calculate_age_from_dob(cls, v, values):
        if v is not None:
            return v
        if 'date_of_birth' in values and values['date_of_birth']:
            today = date.today()
            dob = values['date_of_birth']
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return age
        return v

    @validator('full_name', always=True)
    def generate_full_name(cls, v, values):
        if v:
            return v
        name_parts = []
        if values.get('first_name'):
            name_parts.append(values['first_name'])
        if values.get('middle_name'):
            name_parts.append(values['middle_name'])
        if values.get('last_name'):
            name_parts.append(values['last_name'])
        return ' '.join(name_parts) if name_parts else None


class KYCDocument(BaseModel):
    document_type: str
    document_number: Optional[str] = None
    file_path: Optional[str] = None
    verified: bool = False
    verification_details: Optional[Dict[str, Any]] = None


class CustomerProfile(BaseModel):
    personal_details: PersonalDetails = PersonalDetails()
    kyc_documents: List[KYCDocument] = []
    eligibility_status: Optional[str] = None
    risk_profile: Optional[str] = None
    
    def get_required_fields(self) -> List[str]:
        """Get list of required fields for policy issuance."""
        return [
            'full_name', 'date_of_birth', 'gender', 'mobile_number', 
            'email', 'annual_income', 'tobacco_user', 'pin_code'
        ]
    
    def get_missing_fields(self) -> List[str]:
        """Get list of missing required fields."""
        required_fields = self.get_required_fields()
        missing_fields = []
        
        personal_dict = self.personal_details.dict()
        for field in required_fields:
            if field not in personal_dict or personal_dict[field] is None:
                missing_fields.append(field)
        
        return missing_fields
    
    def is_eligible_basic(self) -> bool:
        """Basic eligibility check based on age and nationality."""
        if not self.personal_details.age:
            return False
        
        # Age check (18-65 for eTouch II)
        if self.personal_details.age < 18 or self.personal_details.age > 65:
            return False
        
        # Nationality check
        if self.personal_details.nationality != "Indian":
            return False
            
        return True
    
    def get_applicable_discounts(self) -> List[str]:
        """Get applicable discounts based on customer profile."""
        discounts = []
        
        # Non-tobacco discount
        if self.personal_details.tobacco_user is False:
            discounts.append("preferential")
        
        # Female discount (3-year setback)
        if self.personal_details.gender == Gender.FEMALE:
            discounts.append("preferential")
        
        # Bajaj employee discount
        if self.personal_details.is_bajaj_group_employee:
            discounts.append("staff_discount")
            
        return discounts