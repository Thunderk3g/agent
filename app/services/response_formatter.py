from typing import Dict, Any, List, Optional
from app.models.chat_response import (
    ChatResponse, FormAction, FormField, FieldType, ValidationRule,
    DocumentUploadAction, DocumentUpload, QuoteDisplayAction, QuoteVariant,
    PaymentRedirectAction, PaymentDetails, DataCollection
)
from app.models.session import SessionData, SessionState
from app.models.customer import Gender, ResidentialStatus
from app.models.policy import Variant, PaymentFrequency
from app.utils.logging import logger


class ResponseFormatter:
    """Service to format responses for frontend consumption."""
    
    def format_onboarding_form(self, session: SessionData, missing_fields: List[str]) -> FormAction:
        """Create onboarding form based on missing fields."""
        fields = []
        
        if 'full_name' in missing_fields:
            fields.append(FormField(
                name="full_name",
                label="Full Name",
                type=FieldType.TEXT,
                required=True,
                placeholder="Enter your full name as per ID documents",
                validation=ValidationRule(min_length=2, max_length=100)
            ))
        
        if 'date_of_birth' in missing_fields:
            fields.append(FormField(
                name="date_of_birth",
                label="Date of Birth",
                type=FieldType.DATE,
                required=True,
                validation=ValidationRule(min_age=18, max_age=65)
            ))
        
        if 'gender' in missing_fields:
            fields.append(FormField(
                name="gender",
                label="Gender",
                type=FieldType.SELECT,
                required=True,
                options=[
                    {"value": "male", "label": "Male"},
                    {"value": "female", "label": "Female"},
                    {"value": "other", "label": "Other"}
                ]
            ))
        
        if 'mobile_number' in missing_fields:
            fields.append(FormField(
                name="mobile_number",
                label="Mobile Number",
                type=FieldType.PHONE,
                required=True,
                placeholder="10-digit mobile number",
                validation=ValidationRule(pattern="^[6-9][0-9]{9}$")
            ))
        
        if 'email' in missing_fields:
            fields.append(FormField(
                name="email",
                label="Email Address",
                type=FieldType.EMAIL,
                required=True,
                placeholder="your.email@example.com"
            ))
        
        if 'pin_code' in missing_fields:
            fields.append(FormField(
                name="pin_code",
                label="PIN Code",
                type=FieldType.TEXT,
                required=True,
                placeholder="6-digit PIN code",
                validation=ValidationRule(pattern="^[0-9]{6}$")
            ))
        
        if 'annual_income' in missing_fields:
            fields.append(FormField(
                name="annual_income",
                label="Annual Income (₹)",
                type=FieldType.NUMBER,
                required=True,
                placeholder="Enter your annual income in rupees",
                validation=ValidationRule(min_value=100000)  # Minimum 1 lakh
            ))
        
        if 'tobacco_user' in missing_fields:
            fields.append(FormField(
                name="tobacco_user",
                label="Do you use tobacco products?",
                type=FieldType.RADIO,
                required=True,
                options=[
                    {"value": "false", "label": "No"},
                    {"value": "true", "label": "Yes"}
                ]
            ))
        
        return FormAction(
            title="Personal Information",
            description="Please provide your basic personal details to get started.",
            fields=fields,
            submit_label="Continue"
        )
    
    def format_kyc_documents_form(self) -> DocumentUploadAction:
        """Create KYC document upload form."""
        documents = [
            DocumentUpload(
                name="pan_card",
                label="PAN Card",
                required=True,
                description="Upload clear image of your PAN card"
            ),
            DocumentUpload(
                name="aadhar_card",
                label="Aadhar Card",
                required=True,
                description="Upload clear image of your Aadhar card"
            ),
            DocumentUpload(
                name="income_proof",
                label="Income Proof",
                required=False,
                description="Salary slip, ITR, or bank statement"
            )
        ]
        
        return DocumentUploadAction(
            title="KYC Documents",
            description="Please upload the required documents for identity verification.",
            documents=documents,
            submit_label="Upload Documents"
        )
    
    def format_eligibility_form(self, session: SessionData) -> FormAction:
        """Create eligibility assessment form."""
        fields = [
            FormField(
                name="occupation",
                label="Occupation",
                type=FieldType.SELECT,
                required=True,
                options=[
                    {"value": "salaried", "label": "Salaried Employee"},
                    {"value": "self_employed", "label": "Self Employed"},
                    {"value": "business", "label": "Business Owner"},
                    {"value": "professional", "label": "Professional"},
                    {"value": "retired", "label": "Retired"},
                    {"value": "homemaker", "label": "Homemaker"}
                ]
            ),
            FormField(
                name="health_condition",
                label="Any pre-existing health conditions?",
                type=FieldType.RADIO,
                required=True,
                options=[
                    {"value": "none", "label": "No health conditions"},
                    {"value": "minor", "label": "Minor conditions (controlled)"},
                    {"value": "major", "label": "Major health conditions"}
                ]
            ),
            FormField(
                name="family_medical_history",
                label="Family history of serious illness?",
                type=FieldType.RADIO,
                required=True,
                options=[
                    {"value": "false", "label": "No"},
                    {"value": "true", "label": "Yes"}
                ]
            )
        ]
        
        return FormAction(
            title="Eligibility Assessment",
            description="Help us understand your profile better for accurate quotation.",
            fields=fields,
            submit_label="Check Eligibility"
        )
    
    def format_quote_selection(self, variants: List[Dict[str, Any]]) -> QuoteDisplayAction:
        """Create quote display with variant selection."""
        quote_variants = []
        
        for variant in variants:
            features = []
            if variant.get("death_benefit"):
                features.append("Death Benefit")
            if variant.get("terminal_illness"):
                features.append("Terminal Illness Cover")
            if variant.get("adb"):
                features.append("Accidental Death Benefit")
            if variant.get("return_of_premium"):
                features.append("Return of Premium")
            
            quote_variants.append(QuoteVariant(
                name=variant["name"],
                premium=variant["premium"],
                features=features,
                sum_assured=variant["sum_assured"],
                policy_term=variant["policy_term"],
                premium_paying_term=variant["premium_paying_term"],
                recommended=variant.get("recommended", False)
            ))
        
        return QuoteDisplayAction(
            title="Choose Your Insurance Plan",
            description="Compare our variants and select the one that best fits your needs.",
            variants=quote_variants,
            comparison_features=["Death Benefit", "Terminal Illness", "Accidental Death", "Return of Premium"]
        )
    
    def format_payment_redirect(self, quote_data: Dict[str, Any]) -> PaymentRedirectAction:
        """Create payment redirect action."""
        payment_details = PaymentDetails(
            amount=quote_data["total_premium"],
            premium_frequency=quote_data["frequency"],
            variant_name=quote_data["variant"],
            sum_assured=quote_data["sum_assured"],
            policy_term=quote_data["policy_term"],
            premium_paying_term=quote_data["premium_paying_term"]
        )
        
        return PaymentRedirectAction(
            title="Complete Your Purchase",
            description="Proceed to secure payment to activate your insurance policy.",
            payment_details=payment_details,
            redirect_url="/api/payments/initiate"
        )
    
    def format_data_collection_status(self, session: SessionData, required_fields: List[str]) -> DataCollection:
        """Create data collection status."""
        collected = []
        missing = []
        
        for field in required_fields:
            if field in session.customer_data and session.customer_data[field] is not None:
                collected.append(field)
            else:
                missing.append(field)
        
        completion_percentage = int((len(collected) / len(required_fields)) * 100) if required_fields else 100
        next_required = missing[0] if missing else None
        
        return DataCollection(
            collected=collected,
            missing=missing,
            completion_percentage=completion_percentage,
            next_required_field=next_required
        )
    
    def format_policy_management_options(self, session: SessionData) -> List[Dict[str, Any]]:
        """Create policy management options."""
        return [
            {
                "title": "Make Premium Payment",
                "description": "Pay your next premium installment",
                "action": "make_payment",
                "icon": "payment"
            },
            {
                "title": "Premium Holiday",
                "description": "Skip premium payments temporarily",
                "action": "premium_holiday",
                "icon": "pause"
            },
            {
                "title": "Life Stage Upgrade", 
                "description": "Increase coverage for life events",
                "action": "life_stage_upgrade",
                "icon": "upgrade"
            },
            {
                "title": "Submit Claim",
                "description": "File an insurance claim",
                "action": "submit_claim",
                "icon": "claim"
            },
            {
                "title": "Policy Documents",
                "description": "Download policy certificates and statements",
                "action": "download_documents",
                "icon": "document"
            },
            {
                "title": "Update Details",
                "description": "Update contact information or nominee details",
                "action": "update_details",
                "icon": "edit"
            }
        ]
    
    def format_claim_form(self) -> FormAction:
        """Create claim submission form."""
        fields = [
            FormField(
                name="claim_type",
                label="Type of Claim",
                type=FieldType.SELECT,
                required=True,
                options=[
                    {"value": "death", "label": "Death Claim"},
                    {"value": "terminal_illness", "label": "Terminal Illness"},
                    {"value": "accidental_death", "label": "Accidental Death"}
                ]
            ),
            FormField(
                name="incident_date",
                label="Date of Incident",
                type=FieldType.DATE,
                required=True
            ),
            FormField(
                name="claim_description",
                label="Description of Claim",
                type=FieldType.TEXTAREA,
                required=True,
                placeholder="Please provide details about the claim"
            ),
            FormField(
                name="claimant_relationship",
                label="Relationship to Policy Holder",
                type=FieldType.SELECT,
                required=True,
                options=[
                    {"value": "self", "label": "Self"},
                    {"value": "spouse", "label": "Spouse"},
                    {"value": "child", "label": "Child"},
                    {"value": "parent", "label": "Parent"},
                    {"value": "nominee", "label": "Nominee"}
                ]
            )
        ]
        
        return FormAction(
            title="Submit Insurance Claim",
            description="Please provide details about your claim. Our team will review and process it promptly.",
            fields=fields,
            submit_label="Submit Claim"
        )


# Global response formatter instance
response_formatter = ResponseFormatter()