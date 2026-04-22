"""
Sprint 2 Telegram Bot Features
==============================
1. /miaj_punktoj - Stelo-Meter progress display
2. Proactive sister patrol notification on audio submission
3. /pagi - Stripe payment button integration
"""
import asyncio
import os
from decimal import Decimal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from django.db.models import Q
from asgiref.sync import sync_to_async

from apps.scouting.models import Patrol, PatrolMatch
from fastapi_app.db_bridge import build_certification_qr_payload
from fastapi_app.services.patrol_service import find_patrol_by_chat_id


async def handle_miaj_punktoj(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /miaj_punktoj: Display Stelo-Meter progress bar with visual gauge
    Shows current SEL points, tier status, and progress to next milestone.
    """
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    patrol = await find_patrol_by_chat_id(chat_id)
    if patrol is None:
        await update.message.reply_text(
            "Para ver tu Stelo-Meter, primero vincula tu patrulla con /start."
        )
        return

    # Get certification info (includes tier and progress)
    patrol_id = patrol.get("id")
    cert_payload = await build_certification_qr_payload(patrol_id)
    
    sel_points = patrol.get("sel_points", 0)
    tier = cert_payload.get("tier")
    eligible = cert_payload.get("eligible")
    
    # Determine thresholds
    thresholds = {"bronze": 500, "silver": 1000, "gold": 2000}
    current_threshold = 500
    for t, threshold in thresholds.items():
        if sel_points >= threshold:
            current_threshold = threshold
    next_threshold = {500: 1000, 1000: 2000, 2000: 2000}.get(current_threshold, 2000)
    
    # Visual progress bar (10 segments)
    progress_pct = min(100, max(0, (sel_points - (current_threshold - 500)) * 100 // (next_threshold - current_threshold + 1)))
    bar_length = 10
    filled = int(bar_length * progress_pct / 100)
    bar = "█" * filled + "░" * (bar_length - filled)
    
    # Tier emoji
    tier_emoji = {"bronze": "🥉", "silver": "🥈", "gold": "🥇"}.get(tier, "⏳")
    tier_name = {"bronze": "Bronce", "silver": "Plata", "gold": "Oro"}.get(tier, "Sin certificar")
    
    message = (
        f"*{tier_emoji} Stelo-Meter*\n\n"
        f"Patrulla: `{patrol.get('name')}`\n"
        f"Delegación: `{patrol.get('delegation_name')}`\n\n"
        f"*Puntos SEL*: `{sel_points}`\n"
        f"*Tier Actual*: {tier_name}\n\n"
        f"Progreso hacia parche:\n"
        f"`{bar}` {progress_pct}%\n\n"
        f"🎯 Meta proxima: {next_threshold} pts (faltan {max(0, next_threshold - sel_points)} pts)\n"
    )
    
    if eligible and tier:
        message += (
            f"\n✅ *¡Listo para el parche {tier_name}!*\n"
            f"Usa `/qr` para obtener el codigo QR en el stand SEL."
        )
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def notify_sister_patrol_on_audio(update: Update, patrol_id: int) -> None:
    """
    After audio validation, notify the sister patrol (matched patrol).
    Sends: "¡La patrulla [Nombre] te envió un mensaje en Esperanto! Escúchalo y responde para ganar puntos extra"
    """
    try:
        # Find the matched patrol(s) for this patrol
        @sync_to_async
        def get_matches_and_this_patrol():
            matches = PatrolMatch.objects.filter(
                Q(patrol_a_id=patrol_id) | Q(patrol_b_id=patrol_id),
                status="active"
            ).select_related("patrol_a", "patrol_b")
            this_patrol = Patrol.objects.get(pk=patrol_id)
            return list(matches), this_patrol
        
        matches, this_patrol = await get_matches_and_this_patrol()
        
        for match in matches:
            # Determine which patrol is the "other" one
            sister_patrol = match.patrol_b if match.patrol_a_id == patrol_id else match.patrol_a
            
            # Send notification to sister patrol
            if sister_patrol.telegram_chat_id:
                try:
                    await update.effective_user.bot.send_message(
                        chat_id=sister_patrol.telegram_chat_id,
                        text=(
                            f"🎤 ¡La patrulla *{this_patrol.name}* te envió un mensaje en Esperanto!\n\n"
                            f"Escúchalo en el stand SEL y responde para ganar *+50 puntos extra*.\n\n"
                            f"Delegación: {this_patrol.delegation_name}"
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    print(f"Failed to notify sister patrol {sister_patrol.id}: {e}")
    except Exception as e:
        print(f"Error in proactive notification: {e}")


async def handle_pagi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /pagi: Display Stripe payment buttons for premium features.
    Three tiers:
    - Stelo Pass (3 USD) - unlock missions
    - Premium Features (5 USD) - advanced analytics
    - Training Boost (2 USD) - extra tutor interactions
    """
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    patrol = await find_patrol_by_chat_id(chat_id)
    if patrol is None:
        await update.message.reply_text(
            "Para acceder a pagos, primero vincula tu patrulla con /start."
        )
        return

    patrol_id = patrol.get("id")
    
    # Create inline keyboard with payment buttons
    # Each button will trigger a callback that initiates Stripe payment
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎟️ Stelo Pass ($3)",
                callback_data=f"payment:stelo_pass:{patrol_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "⭐ Premium Features ($5)",
                callback_data=f"payment:premium_features:{patrol_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🚀 Training Boost ($2)",
                callback_data=f"payment:training_boost:{patrol_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Más info",
                callback_data="payment:info"
            )
        ],
    ])

    message = (
        "*💳 Tienda SEL Ligilo*\n\n"
        "*Stelo Pass* ($3)\n"
        "Acceso a misiones avanzadas y desafíos especiales.\n\n"
        "*Premium Features* ($5)\n"
        "Analytics de tu patrulla, reportes semanales y badges especiales.\n\n"
        "*Training Boost* ($2)\n"
        "5 sesiones extra de tutoría fónica con IA.\n\n"
        "Selecciona un producto para continuar con Stripe:"
    )

    await update.message.reply_text(message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)


async def handle_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle payment button clicks: initiate Stripe checkout session.
    Callback format: "payment:{product_type}:{patrol_id}"
    """
    if not update.callback_query:
        return

    query = update.callback_query
    callback_data = query.data
    
    # Parse callback: payment:stelo_pass:123
    parts = callback_data.split(":")
    if len(parts) < 2:
        await query.answer("Error procesando pago", show_alert=True)
        return
    
    action = parts[0]
    if action != "payment":
        return
    
    if parts[1] == "info":
        await query.answer(
            "Todos los pagos son seguros via Stripe. "
            "Después de pagar, obtendrás acceso inmediato.",
            show_alert=True
        )
        return
    
    product_type = parts[1]  # stelo_pass, premium_features, training_boost
    try:
        patrol_id = int(parts[2])
    except (ValueError, IndexError):
        await query.answer("Error al procesar el producto", show_alert=True)
        return
    
    # Product pricing (in cents USD)
    products = {
        "stelo_pass": {"price_cents": 300, "name": "Stelo Pass"},
        "premium_features": {"price_cents": 500, "name": "Premium Features"},
        "training_boost": {"price_cents": 200, "name": "Training Boost"},
    }
    
    if product_type not in products:
        await query.answer("Producto no válido", show_alert=True)
        return
    
    product_info = products[product_type]
    
    # Import Stripe and create checkout session
    try:
        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        
        # Create a Stripe Checkout Session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": product_info["name"],
                            "description": f"Ligilo - {product_info['name']}",
                        },
                        "unit_amount": product_info["price_cents"],
                    },
                    "quantity": 1,
                }
            ],
            success_url=os.getenv("STRIPE_SUCCESS_URL", "https://ligilo.sel.org/success"),
            cancel_url=os.getenv("STRIPE_CANCEL_URL", "https://ligilo.sel.org/cancel"),
            metadata={
                "patrol_id": str(patrol_id),
                "product_type": product_type,
                "telegram_chat_id": str(query.message.chat_id),
            },
        )
        
        # Send checkout link to user
        checkout_link = checkout_session.url
        await query.edit_message_text(
            text=(
                f"*Iniciando pago para {product_info['name']}*\n\n"
                f"Haz clic en el enlace para completar tu compra:\n"
                f"[Ir a pagar →]({checkout_link})\n\n"
                f"El pago es seguro y procesado por Stripe."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        await query.answer()
        
    except ImportError:
        await query.answer("Stripe no está configurado", show_alert=True)
    except Exception as e:
        await query.answer(f"Error al crear sesión de pago: {str(e)[:50]}", show_alert=True)
