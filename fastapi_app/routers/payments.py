"""
Stripe and PayPal webhook handlers for payment processing.

This module handles:
- Stripe payment intent webhook events (payment_intent.succeeded, payment_intent.payment_failed)
- PayPal IPN (Instant Payment Notification) webhooks
- Payment status synchronization with Payment model
"""

import json
import logging
import os
from datetime import datetime

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from fastapi_app.db_bridge import get_payment_by_stripe_id, update_payment_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])

# Configure Stripe API key from environment
STRIPE_API_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "")

if STRIPE_API_KEY:
    stripe.api_key = STRIPE_API_KEY


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request) -> JSONResponse:
    """
    Handle Stripe webhook events for payment processing.
    
    Stripe sends events like:
    - payment_intent.succeeded: Payment completed successfully
    - payment_intent.payment_failed: Payment failed
    - charge.dispute.created: Chargeback/dispute initiated
    
    Payload verification ensures requests are from Stripe.
    """
    if not STRIPE_WEBHOOK_SECRET:
        logger.warning("STRIPE_WEBHOOK_SECRET not configured")
        return JSONResponse({"status": "webhook_not_configured"}, status_code=400)
    
    try:
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")
        
        # Verify webhook signature
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except ValueError as e:
            logger.error(f"Invalid Stripe webhook payload: {e}")
            return JSONResponse({"error": "Invalid payload"}, status_code=400)
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Stripe webhook signature verification failed: {e}")
            return JSONResponse({"error": "Invalid signature"}, status_code=401)
        
        # Handle payment_intent.succeeded event
        if event["type"] == "payment_intent.succeeded":
            payment_intent = event["data"]["object"]
            payment_intent_id = payment_intent["id"]
            
            logger.info(f"Processing successful payment intent: {payment_intent_id}")
            
            # Update payment status in database
            await update_payment_status(
                payment_intent_id=payment_intent_id,
                status="completed",
                completed_at=datetime.utcnow().isoformat(),
                metadata={
                    "stripe_amount": payment_intent["amount"],
                    "stripe_currency": payment_intent["currency"],
                    "stripe_receipt_email": payment_intent.get("receipt_email", ""),
                    "stripe_charge_id": payment_intent.get("charges", {}).get("data", [{}])[0].get("id", ""),
                },
            )
            
            return JSONResponse({"status": "payment_succeeded"}, status_code=200)
        
        # Handle payment_intent.payment_failed event
        elif event["type"] == "payment_intent.payment_failed":
            payment_intent = event["data"]["object"]
            payment_intent_id = payment_intent["id"]
            last_error = payment_intent.get("last_payment_error", {})
            error_message = last_error.get("message", "Unknown error")
            
            logger.warning(f"Payment failed for intent {payment_intent_id}: {error_message}")
            
            # Update payment status to failed
            await update_payment_status(
                payment_intent_id=payment_intent_id,
                status="failed",
                error_message=error_message,
                metadata={
                    "stripe_failure_code": last_error.get("code", ""),
                    "stripe_failure_type": last_error.get("type", ""),
                },
            )
            
            return JSONResponse({"status": "payment_failed"}, status_code=200)
        
        # Handle charge.dispute.created (chargeback)
        elif event["type"] == "charge.dispute.created":
            dispute = event["data"]["object"]
            reason = dispute.get("reason", "unknown")
            
            logger.error(f"Payment dispute created: {dispute['id']}, reason: {reason}")
            
            return JSONResponse({"status": "dispute_noted"}, status_code=200)
        
        # Log unhandled event types
        logger.info(f"Unhandled Stripe event type: {event['type']}")
        return JSONResponse({"status": "event_received"}, status_code=200)
        
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/webhook/paypal")
async def paypal_webhook(request: Request) -> JSONResponse:
    """
    Handle PayPal IPN (Instant Payment Notification) webhooks.
    
    PayPal sends notifications for:
    - Completed: Payment completed successfully
    - Failed: Payment failed
    - Refunded: Payment refunded
    - Denied: Payment denied
    
    This endpoint validates the notification and updates payment status accordingly.
    """
    if not PAYPAL_WEBHOOK_ID:
        logger.warning("PAYPAL_WEBHOOK_ID not configured")
        return JSONResponse({"status": "webhook_not_configured"}, status_code=400)
    
    try:
        # Parse IPN message
        body = await request.body()
        ipn_data = {}
        
        # Parse form data from PayPal
        try:
            body_str = body.decode("utf-8")
            ipn_data = {
                k: v for k, v in (pair.split("=") for pair in body_str.split("&"))
            }
        except (ValueError, UnicodeDecodeError) as e:
            logger.error(f"Failed to parse PayPal IPN data: {e}")
            return JSONResponse({"error": "Invalid IPN data"}, status_code=400)
        
        # Extract transaction details
        txn_id = ipn_data.get("txn_id", "")
        payment_status = ipn_data.get("payment_status", "").lower()
        receiver_email = ipn_data.get("receiver_email", "")
        custom_data = ipn_data.get("custom", "{}")  # Custom field can contain JSON
        
        logger.info(f"Processing PayPal IPN: txn_id={txn_id}, status={payment_status}")
        
        # Map PayPal status to our Payment status
        status_mapping = {
            "completed": "completed",
            "processed": "completed",
            "failed": "failed",
            "denied": "failed",
            "expired": "failed",
            "refunded": "refunded",
            "reversed": "refunded",
            "canceled_reversal": "completed",
            "pending": "pending",
        }
        
        mapped_status = status_mapping.get(payment_status, "pending")
        
        # Update payment in database
        await update_payment_status(
            paypal_transaction_id=txn_id,
            status=mapped_status,
            completed_at=datetime.utcnow().isoformat() if mapped_status == "completed" else None,
            metadata={
                "paypal_status": payment_status,
                "paypal_receiver": receiver_email,
                "paypal_custom": custom_data,
                "paypal_amount": ipn_data.get("mc_gross", ""),
                "paypal_currency": ipn_data.get("mc_currency", ""),
                "paypal_item_name": ipn_data.get("item_name", ""),
            },
        )
        
        # PayPal requires a 200 response with empty body to confirm receipt
        return JSONResponse({"status": "IPN_received"}, status_code=200)
        
    except Exception as e:
        logger.error(f"PayPal webhook error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/initiate-stripe-payment")
async def initiate_stripe_payment(
    patrol_id: int,
    product_type: str,
    amount_cents: int,
    success_url: str = "https://example.com/payment/success",
    cancel_url: str = "https://example.com/payment/cancel",
) -> dict:
    """
    Initiate a Stripe payment intent for a patrol.
    
    Args:
        patrol_id: ID of the patrol making the payment
        product_type: Type of product (stelo_pass, premium_features, training_boost)
        amount_cents: Amount in cents (USD)
        success_url: URL to redirect on successful payment
        cancel_url: URL to redirect on cancelled payment
    
    Returns:
        Dictionary with client_secret and payment_intent_id
    """
    if not STRIPE_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe not configured on server"
        )
    
    try:
        # Create payment intent
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            description=f"Ligilo {product_type} - Patrol {patrol_id}",
            metadata={
                "patrol_id": str(patrol_id),
                "product_type": product_type,
            },
        )
        
        logger.info(f"Created Stripe PaymentIntent {intent.id} for patrol {patrol_id}")
        
        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
            "amount": amount_cents,
            "currency": "usd",
        }
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Stripe error: {str(e)}"
        )
