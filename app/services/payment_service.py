"""Mock payment gateway service for insurance purchase simulation."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel

from app.utils.logging import logger


class PaymentStatus(str, Enum):
    INITIATED = "initiated"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentMethod(str, Enum):
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    NET_BANKING = "net_banking"
    UPI = "upi"
    WALLET = "wallet"


class PaymentRequest(BaseModel):
    session_id: str
    amount: float
    currency: str = "INR"
    payment_method: PaymentMethod
    customer_details: Dict[str, Any]
    policy_details: Dict[str, Any]
    return_url: str
    webhook_url: Optional[str] = None


class PaymentResponse(BaseModel):
    payment_id: str
    status: PaymentStatus
    payment_url: Optional[str] = None
    transaction_id: Optional[str] = None
    gateway_response: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MockPaymentService:
    """Mock payment service that simulates real payment gateway behavior."""
    
    def __init__(self):
        self.payments: Dict[str, PaymentResponse] = {}
        self.success_rate = 0.85  # 85% success rate for simulation
        
    async def initiate_payment(self, payment_request: PaymentRequest) -> PaymentResponse:
        """Initiate a mock payment and return payment details."""
        payment_id = str(uuid.uuid4())
        transaction_id = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{payment_id[:8]}"
        
        # Create mock payment URL
        payment_url = f"https://mock-gateway.bajajallianz.com/pay/{payment_id}"
        
        payment_response = PaymentResponse(
            payment_id=payment_id,
            status=PaymentStatus.INITIATED,
            payment_url=payment_url,
            transaction_id=transaction_id,
            gateway_response={
                "gateway": "MockPaymentGateway",
                "merchant_id": "BAJAJ_ALLIANZ_LIFE",
                "amount": payment_request.amount,
                "currency": payment_request.currency,
                "payment_method": payment_request.payment_method.value,
                "session_id": payment_request.session_id
            },
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Store payment for tracking
        self.payments[payment_id] = payment_response
        
        # Simulate async payment processing
        asyncio.create_task(self._simulate_payment_processing(payment_id))
        
        logger.info(f"Payment initiated: {payment_id} for session {payment_request.session_id}")
        return payment_response
    
    async def get_payment_status(self, payment_id: str) -> Optional[PaymentResponse]:
        """Get current payment status."""
        return self.payments.get(payment_id)
    
    async def cancel_payment(self, payment_id: str) -> bool:
        """Cancel a pending payment."""
        payment = self.payments.get(payment_id)
        if payment and payment.status in [PaymentStatus.INITIATED, PaymentStatus.PROCESSING]:
            payment.status = PaymentStatus.CANCELLED
            payment.updated_at = datetime.now()
            payment.gateway_response.update({
                "cancelled_at": datetime.now().isoformat(),
                "cancellation_reason": "User initiated cancellation"
            })
            logger.info(f"Payment cancelled: {payment_id}")
            return True
        return False
    
    async def process_webhook(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process webhook callback from payment gateway."""
        payment_id = webhook_data.get("payment_id")
        status = webhook_data.get("status")
        
        if payment_id and payment_id in self.payments:
            payment = self.payments[payment_id]
            if status in [status.value for status in PaymentStatus]:
                payment.status = PaymentStatus(status)
                payment.updated_at = datetime.now()
                payment.gateway_response.update(webhook_data)
                
                logger.info(f"Payment webhook processed: {payment_id} - {status}")
                return {"status": "success", "message": "Webhook processed"}
        
        return {"status": "error", "message": "Invalid webhook data"}
    
    async def _simulate_payment_processing(self, payment_id: str):
        """Simulate payment processing with random delays and outcomes."""
        await asyncio.sleep(2)  # Initial processing delay
        
        payment = self.payments.get(payment_id)
        if not payment:
            return
        
        # Update to processing
        payment.status = PaymentStatus.PROCESSING
        payment.updated_at = datetime.now()
        payment.gateway_response.update({
            "processing_started_at": datetime.now().isoformat()
        })
        
        # Simulate processing time (5-15 seconds)
        processing_time = 5 + (hash(payment_id) % 10)
        await asyncio.sleep(processing_time)
        
        # Determine outcome based on success rate
        import random
        if random.random() < self.success_rate:
            # Success
            payment.status = PaymentStatus.SUCCESS
            payment.gateway_response.update({
                "success_at": datetime.now().isoformat(),
                "authorization_code": f"AUTH{random.randint(100000, 999999)}",
                "gateway_transaction_id": f"GTW{random.randint(1000000000, 9999999999)}",
                "bank_reference_number": f"BRN{random.randint(1000000000, 9999999999)}"
            })
            logger.info(f"Payment successful: {payment_id}")
        else:
            # Failure
            payment.status = PaymentStatus.FAILED
            failure_reasons = [
                "Insufficient funds",
                "Card declined by bank",
                "Transaction timeout",
                "Invalid card details",
                "Bank server unavailable"
            ]
            payment.gateway_response.update({
                "failed_at": datetime.now().isoformat(),
                "failure_reason": random.choice(failure_reasons),
                "error_code": f"ERR{random.randint(1000, 9999)}"
            })
            logger.info(f"Payment failed: {payment_id}")
        
        payment.updated_at = datetime.now()
        
        # Simulate webhook callback (in real implementation, this would be sent by gateway)
        if hasattr(self, '_webhook_callback'):
            await self._webhook_callback(payment)
    
    def generate_policy_number(self, session_id: str, payment_id: str) -> str:
        """Generate mock policy number after successful payment."""
        timestamp = datetime.now().strftime("%Y%m%d")
        policy_num = f"ETOUCH{timestamp}{session_id[:8].upper()}{payment_id[:4].upper()}"
        return policy_num
    
    async def generate_payment_receipt(self, payment_id: str) -> Dict[str, Any]:
        """Generate payment receipt data."""
        payment = self.payments.get(payment_id)
        if not payment or payment.status != PaymentStatus.SUCCESS:
            return {"error": "Payment not found or not successful"}
        
        receipt = {
            "receipt_id": f"RCP{datetime.now().strftime('%Y%m%d%H%M%S')}{payment_id[:6]}",
            "payment_id": payment_id,
            "transaction_id": payment.transaction_id,
            "amount": payment.gateway_response.get("amount"),
            "currency": payment.gateway_response.get("currency"),
            "payment_method": payment.gateway_response.get("payment_method"),
            "paid_at": payment.gateway_response.get("success_at"),
            "authorization_code": payment.gateway_response.get("authorization_code"),
            "bank_reference": payment.gateway_response.get("bank_reference_number"),
            "merchant_details": {
                "name": "Bajaj Allianz Life Insurance Co. Ltd.",
                "merchant_id": "BAJAJ_ALLIANZ_LIFE",
                "gstin": "27AABCB1234C1Z8"
            },
            "receipt_url": f"https://mock-gateway.bajajallianz.com/receipt/{payment_id}"
        }
        
        return receipt
    
    def get_payment_statistics(self) -> Dict[str, Any]:
        """Get payment processing statistics for monitoring."""
        total_payments = len(self.payments)
        if total_payments == 0:
            return {"total_payments": 0}
        
        status_counts = {}
        total_amount = 0
        
        for payment in self.payments.values():
            status = payment.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
            if payment.status == PaymentStatus.SUCCESS:
                total_amount += payment.gateway_response.get("amount", 0)
        
        return {
            "total_payments": total_payments,
            "status_breakdown": status_counts,
            "total_successful_amount": total_amount,
            "success_rate": status_counts.get("success", 0) / total_payments,
            "failure_rate": status_counts.get("failed", 0) / total_payments
        }


# Global payment service instance
payment_service = MockPaymentService()