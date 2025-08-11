"""Payment API endpoints for handling insurance purchase payments."""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, Optional
import logging

from app.services.payment_service import payment_service, PaymentRequest, PaymentMethod
from app.models.session import session_manager, SessionState
from app.utils.logging import logger

router = APIRouter(prefix="/payment", tags=["payment"])


class PaymentInitiationRequest(BaseModel):
    session_id: str
    payment_method: PaymentMethod
    return_url: Optional[str] = "http://localhost:3000/payment/success"
    webhook_url: Optional[str] = "http://localhost:8000/api/payment/webhook"


class PaymentStatusResponse(BaseModel):
    payment_id: str
    status: str
    transaction_id: Optional[str] = None
    payment_url: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "INR"
    created_at: str
    updated_at: str


@router.post("/initiate", response_model=Dict[str, Any])
async def initiate_payment(request: PaymentInitiationRequest):
    """Initiate payment for insurance policy."""
    try:
        # Get session data
        session = session_manager.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Validate session has required data for payment
        required_fields = ["full_name", "age", "gender", "coverage_amount"]
        missing_fields = [field for field in required_fields 
                         if field not in session.customer_data or not session.customer_data[field]]
        
        if missing_fields:
            raise HTTPException(
                status_code=400, 
                detail=f"Missing required customer data: {', '.join(missing_fields)}"
            )
        
        # Calculate total amount (simplified)
        base_amount = float(session.customer_data.get("coverage_amount", 5000000)) * 0.002
        rider_amount = sum(rider.get("premium", 0) for rider in session.selected_riders)
        total_amount = base_amount + rider_amount
        
        # Create payment request
        payment_request = PaymentRequest(
            session_id=request.session_id,
            amount=total_amount,
            payment_method=request.payment_method,
            customer_details=session.customer_data,
            policy_details={
                "selected_variant": session.selected_product.get("variant"),
                "coverage_amount": session.customer_data.get("coverage_amount"),
                "policy_term": session.customer_data.get("policy_term"),
                "riders": session.selected_riders
            },
            return_url=request.return_url,
            webhook_url=request.webhook_url
        )
        
        # Initiate payment
        payment_response = await payment_service.initiate_payment(payment_request)
        
        # Update session state
        session.transition_state(SessionState.PAYMENT_INITIATED, {
            "payment_id": payment_response.payment_id,
            "payment_method": request.payment_method.value,
            "amount": total_amount
        })
        
        # Update payment data
        session.payment_data.update({
            "payment_id": payment_response.payment_id,
            "transaction_id": payment_response.transaction_id,
            "amount": total_amount,
            "payment_method": request.payment_method.value,
            "status": payment_response.status.value
        })
        
        session_manager.update_session(session)
        
        logger.info(f"Payment initiated for session {request.session_id}: {payment_response.payment_id}")
        
        return {
            "success": True,
            "payment_id": payment_response.payment_id,
            "payment_url": payment_response.payment_url,
            "transaction_id": payment_response.transaction_id,
            "amount": total_amount,
            "status": payment_response.status.value,
            "message": "Payment initiated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Payment initiation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Payment initiation failed")


@router.get("/status/{payment_id}", response_model=PaymentStatusResponse)
async def get_payment_status(payment_id: str):
    """Get current payment status."""
    try:
        payment = await payment_service.get_payment_status(payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        
        return PaymentStatusResponse(
            payment_id=payment.payment_id,
            status=payment.status.value,
            transaction_id=payment.transaction_id,
            payment_url=payment.payment_url,
            amount=payment.gateway_response.get("amount"),
            currency=payment.gateway_response.get("currency", "INR"),
            created_at=payment.created_at.isoformat(),
            updated_at=payment.updated_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get payment status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve payment status")


@router.post("/webhook")
async def payment_webhook(webhook_data: Dict[str, Any], background_tasks: BackgroundTasks):
    """Handle payment webhook from gateway."""
    try:
        # Process webhook
        result = await payment_service.process_webhook(webhook_data)
        
        if result.get("status") == "success":
            # Update session in background
            background_tasks.add_task(update_session_after_payment, webhook_data)
            
        return {"status": "success", "message": "Webhook processed"}
        
    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}")
        return {"status": "error", "message": "Webhook processing failed"}


async def update_session_after_payment(webhook_data: Dict[str, Any]):
    """Update session data after payment completion."""
    try:
        payment_id = webhook_data.get("payment_id")
        status = webhook_data.get("status")
        
        # Find session by payment_id (simplified - in real implementation, store mapping)
        # For now, we'll update based on webhook data
        
        if status == "success":
            # Generate policy number
            policy_number = payment_service.generate_policy_number("session_id", payment_id)
            
            logger.info(f"Payment successful: {payment_id}, Policy: {policy_number}")
            
            # Here you would update the session state to POLICY_ISSUED
            # and store policy details
            
    except Exception as e:
        logger.error(f"Failed to update session after payment: {str(e)}")


@router.post("/cancel/{payment_id}")
async def cancel_payment(payment_id: str):
    """Cancel a pending payment."""
    try:
        success = await payment_service.cancel_payment(payment_id)
        
        if success:
            return {"success": True, "message": "Payment cancelled successfully"}
        else:
            raise HTTPException(status_code=400, detail="Payment cannot be cancelled")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Payment cancellation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Payment cancellation failed")


@router.get("/receipt/{payment_id}")
async def get_payment_receipt(payment_id: str):
    """Generate and return payment receipt."""
    try:
        receipt = await payment_service.generate_payment_receipt(payment_id)
        
        if "error" in receipt:
            raise HTTPException(status_code=404, detail=receipt["error"])
        
        return receipt
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate receipt: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate receipt")


@router.get("/statistics")
async def get_payment_statistics():
    """Get payment processing statistics (admin endpoint)."""
    try:
        stats = payment_service.get_payment_statistics()
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get payment statistics: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve statistics")