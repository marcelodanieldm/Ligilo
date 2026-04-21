import asyncio
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from fastapi_app.services.patrol_service import bind_chat_with_invitation_token, find_patrol_by_chat_id

_telegram_app: Application | None = None
_init_lock = asyncio.Lock()


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    patrol = await find_patrol_by_chat_id(chat_id)

    if patrol:
        await update.message.reply_text(
            f"Saluton! Ya estás vinculado a la patrulla {patrol['delegation_name']} / {patrol['name']}."
        )
        return

    await update.message.reply_text(
        "Saluton, scout. Antes de continuar, envíame tu Codigo de Invitacion generado en el admin."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    patrol = await find_patrol_by_chat_id(chat_id)
    if patrol:
        await update.message.reply_text("Tu chat ya está vinculado. Pronto recibirás tus misiones.")
        return

    token = update.message.text.strip()
    result = await bind_chat_with_invitation_token(chat_id, token)
    status = result.get("status")

    if status == "bound":
        bound_patrol = result["patrol"]
        await update.message.reply_text(
            "Vinculacion completada. "
            f"Patrulla: {bound_patrol['delegation_name']} / {bound_patrol['name']}."
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
