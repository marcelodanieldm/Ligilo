import asyncio
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from fastapi_app.services.gemini_seed_validator import validate_esperanto_content
from fastapi_app.services.patrol_service import bind_chat_with_invitation_token, find_patrol_by_chat_id

_telegram_app: Application | None = None
_init_lock = asyncio.Lock()
_MARKDOWN_V2_RESERVED = "_[]()~`>#+-=|{}.!"


def _escape_markdown_v2(value: str) -> str:
    return "".join(f"\\{char}" if char in _MARKDOWN_V2_RESERVED else char for char in value)


def _build_welcome_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Tengo mi codigo scout", callback_data="welcome:token")],
            [InlineKeyboardButton("Necesito ayuda SEL", callback_data="welcome:help")],
        ]
    )


def _build_welcome_message() -> str:
    return (
        "*Saluton, scout* 🧭\n\n"
        "Bienvenido a *Ligilo* ⛺\n"
        "Te acompaño para vincular tu patrulla y dejarte listo para la misión\\.\n\n"
        "*Paso 1*\\: ten a mano tu `Codigo de Invitacion`\\.\n"
        "*Paso 2*\\: toca un botón de abajo para continuar sin perderte\\.\n\n"
        "_Tu líder puede regenerar el código si algo falla\\._"
    )


def _build_validation_error_message() -> str:
    return (
        "🌱 *Casi esta*\n\n"
        "Entendi tu intento, pero la frase en esperanto todavia no es clara para otro scout\\.\n"
        "Prueba una version mas corta con sujeto \\+ accion \\+ lugar\\.\n\n"
        "Ejemplo\\: `Ni renkontigxas apud la turo je la sesa\\.`\n\n"
        "Puedes intentarlo de nuevo ahora\\. Estoy aqui para ayudarte, no para penalizarte\\."
    )


def _build_success_validation_message(encouragement_message: str) -> str:
    safe_message = _escape_markdown_v2(encouragement_message)
    return (
        "✅ *Buen avance*\n\n"
        "Tu frase se entiende para trabajo de patrulla\\.\n"
        f"{safe_message}"
    )


def _build_flagged_message() -> str:
    return (
        "⚠️ *Mensaje bloqueado por seguridad*\n\n"
        "Detecte contenido que puede romper Safe from Harm\\.\n"
        "Reescribe tu mensaje en tono respetuoso y enfocado en la mision\\."
    )


async def _validate_linked_patrol_message(text: str) -> dict[str, object]:
    return await asyncio.to_thread(validate_esperanto_content, text)


async def handle_welcome_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not update.effective_chat:
        return

    query = update.callback_query
    await query.answer()

    if query.data == "welcome:token":
        await query.message.reply_text(
            "Perfecto. Enviame ahora tu Codigo de Invitacion tal como aparece en el panel SEL."
        )
        return

    await query.message.reply_text(
        "Sin problema. Si no tienes el codigo, pide a tu lider SEL que lo regenere desde Django Admin y vuelva a compartirlo contigo."
    )


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    patrol = await find_patrol_by_chat_id(chat_id)

    if patrol:
        patrol_name = _escape_markdown_v2(f"{patrol['delegation_name']} / {patrol['name']}")
        await update.message.reply_text(
            f"*Saluton\\!* Ya estas vinculado a *{patrol_name}*\\.\nPrepárate: pronto recibirás tus misiones ⛺",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await update.message.reply_text(
        _build_welcome_message(),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_build_welcome_markup(),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    incoming_text = update.message.text.strip()
    patrol = await find_patrol_by_chat_id(chat_id)
    if patrol:
        try:
            validation = await _validate_linked_patrol_message(incoming_text)
        except ValueError:
            await update.message.reply_text(
                "Validador semilla no disponible por ahora. Seguimos en modo mision normal."
            )
            return
        except Exception:
            await update.message.reply_text(
                "No pude validar en este momento. Reintenta en unos segundos."
            )
            return

        if bool(validation.get("flagged")):
            await update.message.reply_text(
                _build_flagged_message(),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        if not bool(validation.get("comprehensible")):
            await update.message.reply_text(
                _build_validation_error_message(),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        encouragement = str(validation.get("encouragement_message") or "Bone farite, daurigu!")
        await update.message.reply_text(
            _build_success_validation_message(encouragement),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    token = incoming_text
    result = await bind_chat_with_invitation_token(chat_id, token)
    status = result.get("status")

    if status == "bound":
        bound_patrol = result["patrol"]
        await update.message.reply_text(
            "Vinculacion completada. "
            f"Patrulla: {bound_patrol['delegation_name']} / {bound_patrol['name']}.\n"
            "Insignia activa: ya puedes recibir consignas y responder a tu lider.",
        )
        return

    if status == "token_already_used":
        await update.message.reply_text(
            "Ese Codigo de Invitacion ya fue usado por otro chat. Contacta a tu lider SEL."
        )
        return

    if status == "chat_already_bound":
        await update.message.reply_text("Este chat ya está vinculado a otra patrulla.")
        return

    await update.message.reply_text("Codigo invalido. Revisa el token y vuelve a intentarlo.")


async def init_telegram_application() -> Application:
    global _telegram_app

    if _telegram_app is not None:
        return _telegram_app

    async with _init_lock:
        if _telegram_app is not None:
            return _telegram_app

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required for Telegram webhook")

        app = Application.builder().token(bot_token).build()
        app.add_handler(CommandHandler("start", handle_start))
        app.add_handler(CallbackQueryHandler(handle_welcome_action, pattern=r"^welcome:"))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        await app.initialize()
        _telegram_app = app

    return _telegram_app


async def process_telegram_update(update_payload: dict) -> None:
    app = await init_telegram_application()
    update = Update.de_json(update_payload, app.bot)
    if update is None:
        return
    await app.process_update(update)
