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

from fastapi_app.services.audio_stt_validator import transcribe_and_score_audio
from fastapi_app.services.gemini_seed_validator import validate_esperanto_content
from fastapi_app.services.media_storage import store_success_audio_sample
from fastapi_app.services.patrol_service import (
    award_patrol_points,
    bind_chat_with_invitation_token,
    find_patrol_by_chat_id,
    get_match_celebration_payloads,
    get_scout_registration_status,
    increase_training_points,
    mark_match_celebration_interaction,
)
from fastapi_app.services.training_tutor import generate_training_tutor_reply
from fastapi_app.services.voice_pipeline import (
    download_and_convert_voice,
    extract_youtube_video_id,
)
from fastapi_app.services.telegram_bot_sprint2 import (
    handle_miaj_punktoj,
    handle_pagi,
    handle_payment_callback,
    notify_sister_patrol_on_audio,
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


def _country_flag(country_code: str | None) -> str:
    code = (country_code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return "🏳️"
    return chr(127397 + ord(code[0])) + chr(127397 + ord(code[1]))


def _build_match_card_message(payload: dict) -> str:
    patrol = payload.get("patrol") or {}
    sister = payload.get("sister_patrol") or {}
    own_flag = _country_flag(str(patrol.get("country_code") or ""))
    sister_flag = _country_flag(str(sister.get("country_code") or ""))
    own_name = _escape_markdown_v2(str(patrol.get("name") or "Patrulla"))
    own_delegation = _escape_markdown_v2(str(patrol.get("delegation_name") or ""))
    sister_name = _escape_markdown_v2(str(sister.get("name") or "Patrulla hermana"))
    sister_delegation = _escape_markdown_v2(str(sister.get("delegation_name") or ""))
    phrase = _escape_markdown_v2(str(payload.get("suggested_phrase") or "Saluton, amikoj!"))

    return (
        "🎉 *MATCH ENCONTRADO*\n\n"
        f"{own_flag} *{own_name}* \\- {own_delegation}\n"
        "🤝\n"
        f"{sister_flag} *{sister_name}* \\- {sister_delegation}\n\n"
        "Primera frase sugerida en Esperanto\\:\n"
        f"`{phrase}`"
    )


async def _send_match_cards_to_patrols(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    payloads = await get_match_celebration_payloads(chat_id)
    for payload in payloads:
        target_chat = payload.get("chat_id")
        if not target_chat:
            continue
        await context.bot.send_message(
            chat_id=target_chat,
            text=_build_match_card_message(payload),
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def _validate_linked_patrol_message(text: str) -> dict[str, object]:
    return await asyncio.to_thread(validate_esperanto_content, text)


async def _generate_tutor_message(text: str) -> str:
    return await asyncio.to_thread(generate_training_tutor_reply, text)


async def _transcribe_voice_with_gemini(audio_path: str) -> dict[str, object]:
    return await asyncio.to_thread(transcribe_and_score_audio, audio_path)


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

    registration = await get_scout_registration_status(chat_id)
    real_match_ready = bool(registration.get("has_sister_patrol")) and not bool(
        registration.get("is_training")
    )

    if real_match_ready and context.user_data.get("training_mode"):
        sister = registration.get("sister_patrol") or {}
        own = registration.get("patrol") or {}
        match_id = registration.get("match_id")
        if context.user_data.get("last_swap_match_id") != match_id:
            await update.message.reply_text(
                "Stelo: Misión cumplida, patrulla. Ahora les toca conocer a su match internacional real."
            )
            await update.message.reply_text(
                "Nueva conexion humana activa.\n"
                f"Patrulla: {own.get('delegation_name')} / {own.get('name')}\n"
                f"Patrulla hermana: {sister.get('delegation_name')} / {sister.get('name')}\n"
                "Saluden con: Saluton, amikoj!"
            )
            context.user_data["last_swap_match_id"] = match_id
        context.user_data["training_mode"] = False

    if not real_match_ready:
        context.user_data["training_mode"] = True
        tutor_reply = await _generate_tutor_message(incoming_text)
        await update.message.reply_text(f"Patrulla Stelo (Tutor IA):\n{tutor_reply}")
        total_points = await increase_training_points(chat_id, 1)
        await update.message.reply_text(
            f"Puntos de entrenamiento acumulados: {total_points}. Se conservaran al pasar a match real."
        )
        return

    await _send_match_cards_to_patrols(context, chat_id)
    await mark_match_celebration_interaction(chat_id)

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
    points_result = await award_patrol_points(
        chat_id,
        event_type="text_validated",
        metadata={"source": "telegram_text"},
    )
    if points_result.get("awarded"):
        await update.message.reply_text(
            f"+10 puntos SEL por mensaje validado. Total: {points_result.get('sel_points', 0)}"
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
            f"Puntos de entrenamiento: {patrol.get('training_points', 0)}\n"
            f"Puntos SEL: {patrol.get('sel_points', 0)}\n"
            f"Patrulla hermana: {sister_patrol.get('delegation_name')} / {sister_patrol.get('name')} "
            f"({sister_patrol.get('status')})."
        )
        return

    if status.get("is_training"):
        await update.message.reply_text(
            "Estado de perfil: EN ENTRENAMIENTO.\n"
            f"Patrulla vinculada: {patrol.get('delegation_name')} / {patrol.get('name')}\n"
            f"Puntos de entrenamiento: {patrol.get('training_points', 0)}\n"
            f"Puntos SEL: {patrol.get('sel_points', 0)}\n"
            "Tutor activo: Patrulla Stelo."
        )
        return

    await update.message.reply_text(
        "Estado de perfil: PARCIAL.\n"
        f"Patrulla vinculada: {patrol.get('delegation_name')} / {patrol.get('name')}\n"
        f"Puntos de entrenamiento: {patrol.get('training_points', 0)}\n"
        f"Puntos SEL: {patrol.get('sel_points', 0)}\n"
        "Pendiente: asignacion de patrulla hermana."
    )


async def handle_entregar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return

    patrol = await find_patrol_by_chat_id(update.effective_chat.id)
    if patrol is None:
        await update.message.reply_text(
            "Antes de entregar contenido, debes vincular tu patrulla. Usa /start."
        )
        return

    raw_link = " ".join(context.args).strip() if context.args else ""
    if not raw_link:
        await update.message.reply_text(
            "Uso: /entregar <link_de_youtube>. Ejemplo: /entregar https://youtu.be/ABCDEFGHIJK"
        )
        return

    video_id = extract_youtube_video_id(raw_link)
    if not video_id:
        await update.message.reply_text(
            "No pude validar ese link de YouTube. Comparte una URL valida de watch, shorts, embed o youtu.be."
        )
        return

    await update.message.reply_text(
        "Entrega registrada.\n"
        f"video_id: {video_id}\n"
        "Tu lider podra revisar este recurso en el dashboard."
    )

    points_result = await award_patrol_points(
        update.effective_chat.id,
        event_type="youtube_mission",
        external_ref=video_id,
        metadata={"video_id": video_id, "raw_link": raw_link},
    )
    if points_result.get("awarded"):
        await update.message.reply_text(
            f"+500 puntos SEL por mision YouTube cumplida. Total: {points_result.get('sel_points', 0)}"
        )
    elif points_result.get("reason") == "already_awarded":
        await update.message.reply_text(
            "Ese video ya fue contado antes para esta patrulla."
        )


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message or not update.message.voice:
        return

    chat_id = update.effective_chat.id
    patrol = await find_patrol_by_chat_id(chat_id)
    if patrol is None:
        await update.message.reply_text(
            "Para enviar audio, primero vincula tu patrulla con /start."
        )
        return

    await update.message.reply_text("Audio recibido. Estoy preparando la transcripcion...")

    telegram_file = await context.bot.get_file(update.message.voice.file_id)
    try:
        media_paths = await download_and_convert_voice(
            telegram_file=telegram_file,
            chat_id=chat_id,
            target_ext=os.getenv("VOICE_TARGET_FORMAT", "mp3"),
        )
    except RuntimeError:
        await update.message.reply_text(
            "No pude convertir el audio en este momento. Intenta de nuevo en unos minutos."
        )
        return

    try:
        stt_result = await _transcribe_voice_with_gemini(media_paths["converted_path"])
    except ValueError:
        await update.message.reply_text(
            "No tengo configurada la clave de Gemini para transcribir audio."
        )
        return
    except RuntimeError:
        await update.message.reply_text(
            "No pude transcribir el audio ahora. Intenta de nuevo en unos minutos."
        )
        return

    transcript_text = str(stt_result.get("transcript_text") or "").strip()
    pronunciation_score = int(stt_result.get("pronunciation_score") or 1)
    should_repeat = bool(stt_result.get("should_repeat"))
    feedback_message = str(stt_result.get("feedback_message") or "").strip()

    if should_repeat or not transcript_text:
        await update.message.reply_text(
            "No logre entender bien tu audio. ¿Podrias repetirlo, por favor?"
        )
        if feedback_message:
            await update.message.reply_text(f"Tutor fonetico: {feedback_message}")
        return

    await update.message.reply_text(
        "Transcripcion:\n"
        f"{transcript_text}\n\n"
        f"Pronunciacion estimada (1-5): {pronunciation_score}"
    )
    if feedback_message:
        await update.message.reply_text(f"Feedback fonetico: {feedback_message}")

    validation = await _validate_linked_patrol_message(transcript_text)
    if bool(validation.get("flagged")) or not bool(validation.get("comprehensible")):
        await update.message.reply_text(
            "Recibi la transcripcion, pero aun no cumple el criterio de muestra de exito."
        )
        return

    storage_info = await asyncio.to_thread(
        store_success_audio_sample,
        Path(media_paths["converted_path"]),
        patrol_id=patrol.get("id"),
    )
    await update.message.reply_text(
        "Excelente trabajo. Tu audio se guardo como muestra de exito.\n"
        f"Ubicacion: {storage_info.get('storage_path')}"
    )
    points_result = await award_patrol_points(
        chat_id,
        event_type="audio_validated",
        external_ref=str(update.message.voice.file_id),
        metadata={
            "duration_seconds": update.message.voice.duration,
            "pronunciation_score": pronunciation_score,
            "storage_path": storage_info.get("storage_path"),
        },
    )
    if points_result.get("awarded"):
        await update.message.reply_text(
            f"+50 puntos SEL por audio validado. Total: {points_result.get('sel_points', 0)}"
        )
        # Sprint 2: Notify sister patrol about the audio
        await notify_sister_patrol_on_audio(update, patrol.get("id"))


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
        app.add_handler(CommandHandler("entregar", handle_entregar))
        app.add_handler(CommandHandler("miaj_punktoj", handle_miaj_punktoj))
        app.add_handler(CommandHandler("pagi", handle_pagi))
        app.add_handler(CallbackQueryHandler(handle_payment_callback, pattern=r"^payment:"))
        app.add_handler(registration_handler)
        app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
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
