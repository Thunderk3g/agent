import json
from typing import Dict, Any, List, Optional
from app.config import settings
from app.models.policy import Variant, PaymentFrequency, Quote, QuoteDetails, PremiumAmounts
from app.models.customer import CustomerProfile
from app.utils.logging import logger
from datetime import date, datetime
import os


class QuoteCalculator:
    """Service for calculating insurance premium quotes using comprehensive actuarial tables."""
    
    def __init__(self):
        self.product_config = self._load_product_config()
        self.premium_config = self._load_premium_config()
    
    def _load_product_config(self) -> Dict[str, Any]:
        """Load product configuration from etouch.json."""
        try:
            with open(settings.product_config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load product config: {str(e)}")
            return {}
    
    def _load_premium_config(self) -> Dict[str, Any]:
        """Load premium calculation tables from premium.json."""
        try:
            premium_path = os.path.join("data", "premium.json")
            with open(premium_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load premium config: {str(e)}")
            return {}
    
    def generate_quotes(self, customer_age: int, sum_assured: float, 
                       policy_term: int, premium_paying_term: int,
                       customer_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate quotes for all variants."""
        quotes = []
        
        variants = ["Life Shield", "Life Shield Plus", "Life Shield ROP"]
        
        for variant in variants:
            try:
                quote = self.calculate_quote(
                    variant=variant,
                    customer_age=customer_age,
                    sum_assured=sum_assured,
                    policy_term=policy_term,
                    premium_paying_term=premium_paying_term,
                    customer_profile=customer_profile
                )
                quotes.append(quote)
            except Exception as e:
                logger.error(f"Failed to calculate quote for {variant}: {str(e)}")
                continue
        
        # Sort by premium (lowest first)
        quotes.sort(key=lambda x: x.get("annual_premium", float('inf')))
        
        return quotes
    
    def calculate_quote(self, variant: str, customer_age: int, sum_assured: float,
                       policy_term: int, premium_paying_term: int,
                       customer_profile: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate quote for specific variant using premium tables."""
        
        # Get base premium from actuarial tables
        base_premium = self._calculate_base_premium_from_tables(
            variant, customer_age, sum_assured, policy_term, customer_profile
        )
        
        # Apply all adjustment factors
        adjusted_premium = self._apply_adjustment_factors(base_premium, customer_profile, policy_term)
        
        # Apply discounts
        discounts_applied = self._calculate_applicable_discounts(customer_profile, sum_assured)
        total_discount = sum(discount["amount"] for discount in discounts_applied.values())
        
        # Final annual premium
        annual_premium = max(adjusted_premium - total_discount, adjusted_premium * 0.5)  # Min 50% of adjusted
        
        # Modal premiums using frequency factors
        modal_premiums = self._calculate_modal_premiums(annual_premium)
        
        # Get variant details
        variant_config = self.premium_config.get("base_rates", {}).get(variant, {})
        
        return {
            "name": variant,
            "variant": variant,
            "annual_premium": round(annual_premium, 2),
            "modal_premiums": {k: round(v, 2) for k, v in modal_premiums.items()},
            "sum_assured": sum_assured,
            "policy_term": policy_term,
            "premium_paying_term": premium_paying_term,
            "total_premium_payable": round(annual_premium * premium_paying_term, 2),
            "features": self._get_variant_features(variant),
            "benefits": self._get_variant_benefits(variant, sum_assured),
            "discounts_applied": discounts_applied,
            "discount_amount": round(total_discount, 2),
            "recommended": self._is_recommended_variant(variant, customer_profile),
            "base_premium": round(base_premium, 2),
            "adjusted_premium": round(adjusted_premium, 2),
            "calculation_breakdown": self._get_calculation_breakdown(
                variant, customer_age, customer_profile, policy_term, sum_assured
            )
        }
    
    def _calculate_base_premium_from_tables(self, variant: str, age: int, sum_assured: float, 
                                           policy_term: int, customer_profile: Dict[str, Any]) -> float:
        """Calculate base premium using comprehensive premium tables."""
        
        # Get base rates for variant
        variant_rates = self.premium_config.get("base_rates", {}).get(variant, {})
        if not variant_rates:
            logger.error(f"No premium rates found for variant: {variant}")
            return 0.0
        
        # Determine age band
        age_band = self._get_age_band(age)
        age_rates = variant_rates.get("age_bands", {}).get(age_band, {})
        
        if not age_rates:
            logger.error(f"No rates found for age band: {age_band}")
            return 0.0
        
        # Get gender-specific rate
        gender = customer_profile.get("gender", "male")
        base_rate_per_1000 = age_rates.get(gender, age_rates.get("male", 2.0))
        
        # Calculate base premium (rate per 1000 sum assured)
        base_premium = (sum_assured / 1000) * base_rate_per_1000
        
        # Apply policy term factor
        term_factors = variant_rates.get("policy_term_factors", {})
        term_factor = term_factors.get(str(policy_term), 1.0)
        base_premium *= term_factor
        
        return base_premium
    
    def _apply_adjustment_factors(self, base_premium: float, customer_profile: Dict[str, Any], 
                                policy_term: int) -> float:
        """Apply all adjustment factors to base premium."""
        
        adjusted_premium = base_premium
        adjustments = self.premium_config.get("adjustments", {})
        
        # Tobacco usage adjustment
        tobacco_factor = 1.75 if customer_profile.get("tobacco_user") else 1.0
        adjusted_premium *= tobacco_factor
        
        # Occupation adjustment
        occupation_factor = self._get_occupation_factor(customer_profile.get("occupation", ""))
        adjusted_premium *= occupation_factor
        
        # Health condition adjustment
        health_factor = self._get_health_factor(customer_profile.get("health_condition", "good"))
        adjusted_premium *= health_factor
        
        # Sum assured band factor
        sa_factor = self._get_sum_assured_factor(customer_profile.get("sum_assured", 0))
        adjusted_premium *= sa_factor
        
        # Payment frequency factor
        frequency_factor = self._get_frequency_factor(customer_profile.get("payment_frequency", "yearly"))
        adjusted_premium *= frequency_factor
        
        return adjusted_premium
    
    def _get_age_band(self, age: int) -> str:
        """Get age band for premium lookup."""
        if age <= 25:
            return "18-25"
        elif age <= 30:
            return "26-30"
        elif age <= 35:
            return "31-35"
        elif age <= 40:
            return "36-40"
        elif age <= 45:
            return "41-45"
        elif age <= 50:
            return "46-50"
        elif age <= 55:
            return "51-55"
        elif age <= 60:
            return "56-60"
        else:
            return "61-65"
    
    def _get_occupation_factor(self, occupation: str) -> float:
        """Get occupation loading factor."""
        occupation_categories = self.premium_config.get("adjustments", {}).get("occupation_categories", {})
        
        for category, details in occupation_categories.items():
            if occupation.lower() in [occ.lower() for occ in details.get("occupations", [])]:
                return details.get("factor", 1.0)
        
        # Default to class 1 if occupation not found
        return occupation_categories.get("class_1", {}).get("factor", 1.0)
    
    def _get_health_factor(self, health_condition: str) -> float:
        """Get health condition factor."""
        health_conditions = self.premium_config.get("adjustments", {}).get("health_conditions", {})
        return health_conditions.get(health_condition, {}).get("factor", 1.0)
    
    def _get_sum_assured_factor(self, sum_assured: float) -> float:
        """Get sum assured band factor."""
        sa_bands = self.premium_config.get("adjustments", {}).get("sum_assured_bands", {})
        
        if sum_assured <= 2500000:
            return sa_bands.get("up_to_25_lakh", 1.0)
        elif sum_assured <= 5000000:
            return sa_bands.get("25_to_50_lakh", 0.98)
        elif sum_assured <= 10000000:
            return sa_bands.get("50_lakh_to_1_crore", 0.95)
        elif sum_assured <= 20000000:
            return sa_bands.get("1_to_2_crore", 0.92)
        else:
            return sa_bands.get("above_2_crore", 0.90)
    
    def _get_frequency_factor(self, frequency: str) -> float:
        """Get payment frequency factor."""
        freq_factors = self.premium_config.get("adjustments", {}).get("payment_frequency", {})
        return freq_factors.get(frequency, 1.0)
    
    def _calculate_modal_premiums(self, annual_premium: float) -> Dict[str, float]:
        """Calculate modal premiums for different frequencies."""
        freq_factors = self.premium_config.get("adjustments", {}).get("payment_frequency", {
            "yearly": 1.0,
            "half_yearly": 1.02,
            "quarterly": 1.04,
            "monthly": 1.08
        })
        
        return {
            frequency: annual_premium * factor
            for frequency, factor in freq_factors.items()
        }
    
    def _calculate_applicable_discounts(self, customer_profile: Dict[str, Any], sum_assured: float) -> Dict[str, Dict[str, Any]]:
        """Calculate applicable discounts based on premium.json."""
        applicable_discounts = {}
        discounts_config = self.premium_config.get("adjustments", {}).get("discounts", {})
        
        # Online purchase discount
        if customer_profile.get("purchase_channel") == "online":
            discount = discounts_config.get("online_purchase", {})
            applicable_discounts["online_purchase"] = {
                "name": discount.get("description", "Online Purchase"),
                "percentage": discount.get("percentage", 6),
                "amount": 0  # Will be calculated based on premium
            }
        
        # High sum assured discount
        if sum_assured >= discounts_config.get("high_sum_assured", {}).get("minimum_sum_assured", 10000000):
            discount = discounts_config.get("high_sum_assured", {})
            applicable_discounts["high_sum_assured"] = {
                "name": discount.get("description", "High Sum Assured Rebate"),
                "percentage": discount.get("percentage", 8),
                "amount": 0
            }
        
        # Non-tobacco discount
        if not customer_profile.get("tobacco_user", True):
            discount = discounts_config.get("non_tobacco_preferred", {})
            applicable_discounts["non_tobacco"] = {
                "name": discount.get("description", "Non-tobacco Preferred"),
                "percentage": discount.get("percentage", 10),
                "amount": 0
            }
        
        # Loyalty discount for existing customers
        if customer_profile.get("existing_customer", False):
            discount = discounts_config.get("loyalty_discount", {})
            applicable_discounts["loyalty"] = {
                "name": discount.get("description", "Loyalty Discount"),
                "percentage": discount.get("percentage", 3),
                "amount": 0
            }
        
        return applicable_discounts
    
    def _get_calculation_breakdown(self, variant: str, age: int, customer_profile: Dict[str, Any], 
                                 policy_term: int, sum_assured: float) -> Dict[str, Any]:
        """Get detailed calculation breakdown."""
        return {
            "variant": variant,
            "age_band": self._get_age_band(age),
            "gender": customer_profile.get("gender", "male"),
            "tobacco_user": customer_profile.get("tobacco_user", False),
            "occupation_category": self._get_occupation_category(customer_profile.get("occupation", "")),
            "health_condition": customer_profile.get("health_condition", "good"),
            "policy_term": policy_term,
            "sum_assured_band": self._get_sum_assured_band_name(sum_assured),
            "payment_frequency": customer_profile.get("payment_frequency", "yearly")
        }
    
    def _get_occupation_category(self, occupation: str) -> str:
        """Get occupation category name."""
        occupation_categories = self.premium_config.get("adjustments", {}).get("occupation_categories", {})
        
        for category, details in occupation_categories.items():
            if occupation.lower() in [occ.lower() for occ in details.get("occupations", [])]:
                return category
        
        return "class_1"
    
    def _get_sum_assured_band_name(self, sum_assured: float) -> str:
        """Get sum assured band name."""
        if sum_assured <= 2500000:
            return "up_to_25_lakh"
        elif sum_assured <= 5000000:
            return "25_to_50_lakh"
        elif sum_assured <= 10000000:
            return "50_lakh_to_1_crore"
        elif sum_assured <= 20000000:
            return "1_to_2_crore"
        else:
            return "above_2_crore"
    
    def _calculate_discounts(self, customer_profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Calculate applicable discounts."""
        discounts = {}
        
        # Non-tobacco discount (preferential rates)
        if not customer_profile.get("tobacco_user", True):
            discounts["preferential"] = {
                "name": "Preferential Rates (Non-Tobacco)",
                "percentage": 15,
                "amount": 0  # Will be calculated based on premium
            }
        
        # Female discount (3-year age setback equivalent to ~10% discount)
        if customer_profile.get("gender") == "female":
            discounts["female"] = {
                "name": "Female Discount", 
                "percentage": 8,
                "amount": 0
            }
        
        # Online purchase discount
        discounts["online"] = {
            "name": "Online Direct Purchase",
            "percentage": 6,
            "amount": 0
        }
        
        # First time buyer discount
        if customer_profile.get("first_time_buyer", True):
            discounts["first_time"] = {
                "name": "First Time Buyer",
                "percentage": 5,
                "amount": 0
            }
        
        # High sum assured discount
        sum_assured = customer_profile.get("sum_assured", 0)
        if sum_assured >= 10000000:  # 1 crore
            discounts["hsar"] = {
                "name": "High Sum Assured Rebate",
                "percentage": 3,
                "amount": 0
            }
        
        return discounts
    
    def _get_variant_features(self, variant: str) -> List[str]:
        """Get features for a specific variant."""
        features = {
            "Life Shield": [
                "Death Benefit",
                "Terminal Illness Cover",
                "Waiver of Premium (ATPD/TI)",
                "Life Stage Upgrade Option"
            ],
            "Life Shield Plus": [
                "Death Benefit", 
                "Terminal Illness Cover",
                "Accidental Death Benefit",
                "Waiver of Premium (ATPD/TI)",
                "Life Stage Upgrade Option"
            ],
            "Life Shield ROP": [
                "Death Benefit",
                "Terminal Illness Cover", 
                "Return of Premium at Maturity",
                "Waiver of Premium (ATPD/TI)"
            ]
        }
        return features.get(variant, [])
    
    def _get_variant_benefits(self, variant: str, sum_assured: float) -> Dict[str, Any]:
        """Get benefit amounts for variant."""
        benefits = {
            "death_benefit": sum_assured,
            "terminal_illness": sum_assured if variant != "Life Shield ROP" else min(sum_assured, 20000000)
        }
        
        if variant == "Life Shield Plus":
            benefits["accidental_death"] = sum_assured  # Additional to death benefit
        
        if variant == "Life Shield ROP":
            benefits["maturity_benefit"] = "Total Premiums Paid"
        
        return benefits
    
    def _is_recommended_variant(self, variant: str, customer_profile: Dict[str, Any]) -> bool:
        """Determine if this variant should be recommended."""
        age = customer_profile.get("age", 30)
        income = customer_profile.get("annual_income", 500000)
        risk_profile = customer_profile.get("risk_profile", "low")
        
        # Simple recommendation logic
        if age < 35 and income > 1000000:
            return variant == "Life Shield Plus"  # Young, high income - recommend ADB
        elif age > 50 or income < 500000:
            return variant == "Life Shield"  # Older or lower income - recommend basic
        elif risk_profile == "low" and income > 800000:
            return variant == "Life Shield ROP"  # Low risk, good income - recommend ROP
        else:
            return variant == "Life Shield"  # Default recommendation
    
    def calculate_modal_premium(self, annual_premium: float, frequency: str) -> float:
        """Calculate modal premium for given frequency."""
        modal_factors = self.product_config.get("modal_factors", {
            "monthly": 0.0875,
            "quarterly": 0.26,
            "half_yearly": 0.51,
            "yearly": 1.0
        })
        
        factor = modal_factors.get(frequency.lower(), 1.0)
        return round(annual_premium * factor, 2)
    
    def validate_sum_assured(self, sum_assured: float, annual_income: float) -> Dict[str, Any]:
        """Validate sum assured against income and product limits."""
        min_sum_assured = self.product_config.get("eligibility_limits", {}).get("sum_assured", {}).get("min", 5000000)
        
        validation = {
            "valid": True,
            "messages": []
        }
        
        # Minimum check
        if sum_assured < min_sum_assured:
            validation["valid"] = False
            validation["messages"].append(f"Minimum sum assured is ₹{min_sum_assured:,}")
        
        # Income multiple check (typically 10-20x annual income)
        max_multiple = 20
        max_by_income = annual_income * max_multiple
        
        if sum_assured > max_by_income:
            validation["valid"] = False
            validation["messages"].append(f"Sum assured cannot exceed {max_multiple}x annual income (₹{max_by_income:,})")
        
        return validation


# Global quote calculator instance
quote_calculator = QuoteCalculator()