import asyncio
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)

from fastapi_app.services.gemini_seed_validator import validate_esperanto_content
from fastapi_app.services.patrol_service import (
    bind_chat_with_invitation_token,
    find_patrol_by_chat_id,
    get_scout_registration_status,
)

_telegram_app: Application | None = None
_init_lock = asyncio.Lock()
_MARKDOWN_V2_RESERVED = "_[]()~`>#+-=|{}.!"
REG_WAIT_TOKEN = 1


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
        return REG_WAIT_TOKEN

    query = update.callback_query
    await query.answer()

    if query.data == "welcome:token":
        await query.message.reply_text(
            "Perfecto. Enviame ahora tu Codigo de Invitacion tal como aparece en el panel SEL."
        )
        context.user_data["registration_step"] = "awaiting_token"
        return REG_WAIT_TOKEN

    await query.message.reply_text(
        "Sin problema. Si no tienes el codigo, pide a tu lider SEL que lo regenere desde Django Admin y vuelva a compartirlo contigo."
    )
    context.user_data["registration_step"] = "awaiting_token"
    return REG_WAIT_TOKEN


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    patrol = await find_patrol_by_chat_id(chat_id)

    if patrol:
        patrol_name = _escape_markdown_v2(f"{patrol['delegation_name']} / {patrol['name']}")
        await update.message.reply_text(
            f"*Saluton\\!* Ya estas vinculado a *{patrol_name}*\\.\nPrepárate: pronto recibirás tus misiones ⛺",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        context.user_data.pop("registration_step", None)
        return ConversationHandler.END

    await update.message.reply_text(
        _build_welcome_message(),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_build_welcome_markup(),
    )
    context.user_data["registration_step"] = "awaiting_token"
    return REG_WAIT_TOKEN


async def handle_registration_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_chat or not update.message or not update.message.text:
        return REG_WAIT_TOKEN

    chat_id = update.effective_chat.id
    token = update.message.text.strip()
    patrol = await find_patrol_by_chat_id(chat_id)
    if patrol:
        await update.message.reply_text(
            "Tu chat ya estaba vinculado. Puedes usar /status para ver tu progreso actual."
        )
        context.user_data.pop("registration_step", None)
        return ConversationHandler.END

    result = await bind_chat_with_invitation_token(chat_id, token)
    status = result.get("status")

    if status == "bound":
        bound_patrol = result["patrol"]
        await update.message.reply_text(
            "Vinculacion completada. "
            f"Patrulla: {bound_patrol['delegation_name']} / {bound_patrol['name']}.\n"
            "Insignia activa: ya puedes recibir consignas y responder a tu lider.",
        )
        context.user_data.pop("registration_step", None)
        return ConversationHandler.END

    if status == "token_already_used":
        await update.message.reply_text(
            "Ese Codigo de Invitacion ya fue usado por otro chat. Contacta a tu lider SEL."
        )
        return REG_WAIT_TOKEN

    if status == "chat_already_bound":
        await update.message.reply_text("Este chat ya está vinculado a otra patrulla.")
        context.user_data.pop("registration_step", None)
        return ConversationHandler.END

    await update.message.reply_text("Codigo invalido. Revisa el token y vuelve a intentarlo.")
    return REG_WAIT_TOKEN


async def handle_linked_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    incoming_text = update.message.text.strip()
    patrol = await find_patrol_by_chat_id(chat_id)
    if not patrol:
        if context.user_data.get("registration_step") == "awaiting_token":
            await update.message.reply_text(
                "Sigo esperando tu Codigo de Invitacion. Tambien puedes tocar /start para reiniciar el flujo."
            )
            return
        await update.message.reply_text(
            "Primero necesitamos vincularte a una patrulla. Usa /start para iniciar el registro."
        )
        return

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


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return

    status = await get_scout_registration_status(update.effective_chat.id)
    if not status.get("bound"):
        await update.message.reply_text(
            "Estado de perfil: INCOMPLETO.\nAun no estas vinculado a una patrulla. Usa /start para continuar."
        )
        return

    patrol = status.get("patrol") or {}
    sister_patrol = status.get("sister_patrol")
    if sister_patrol:
        await update.message.reply_text(
            "Estado de perfil: COMPLETO.\n"
            f"Patrulla: {patrol.get('delegation_name')} / {patrol.get('name')}\n"
            f"Patrulla hermana: {sister_patrol.get('delegation_name')} / {sister_patrol.get('name')} "
            f"({sister_patrol.get('status')})."
        )
        return

    await update.message.reply_text(
        "Estado de perfil: PARCIAL.\n"
        f"Patrulla vinculada: {patrol.get('delegation_name')} / {patrol.get('name')}\n"
        "Pendiente: asignacion de patrulla hermana."
    )


async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("Registro pausado. Cuando quieras retomar, usa /start.")
    context.user_data.pop("registration_step", None)
    return ConversationHandler.END


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

        base_dir = Path(__file__).resolve().parents[2]
        persistence_path = Path(
            os.getenv("TELEGRAM_PERSISTENCE_PATH", str(base_dir / "outputs" / "telegram_state.pkl"))
        )
        persistence_path.parent.mkdir(parents=True, exist_ok=True)
        persistence = PicklePersistence(filepath=str(persistence_path))

        app = Application.builder().token(bot_token).persistence(persistence).build()

        registration_handler = ConversationHandler(
            entry_points=[CommandHandler("start", handle_start)],
            states={
                REG_WAIT_TOKEN: [
                    CallbackQueryHandler(handle_welcome_action, pattern=r"^welcome:"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration_token),
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel_registration), CommandHandler("start", handle_start)],
            name="registration_handshake",
            persistent=True,
        )

        app.add_handler(CommandHandler("status", handle_status))
        app.add_handler(registration_handler)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_linked_text))
        await app.initialize()
        _telegram_app = app

    return _telegram_app


async def process_telegram_update(update_payload: dict) -> None:
    app = await init_telegram_application()
    update = Update.de_json(update_payload, app.bot)
    if update is None:
        return
    await app.process_update(update)
