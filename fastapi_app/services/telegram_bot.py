import asyncio
import os
from pathlib import Path

from django.core.mail import send_mail
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
from fastapi_app.services.gemini_seed_validator import evaluate_mcer_progress, validate_esperanto_content
from fastapi_app.services.media_storage import store_success_audio_sample
from fastapi_app.services.patrol_service import (
    award_patrol_points,
    bind_chat_with_invitation_token,
    create_rover_incident,
    create_youtube_submission_by_chat,
    find_patrol_by_chat_id,
    get_match_celebration_payloads,
    get_mcer_certificate,
    get_scout_registration_status,
    increase_training_points,
    mark_match_celebration_interaction,
    notify_leader_about_certificate,
)
from fastapi_app.services.youtube_validator import validate_youtube_video
from fastapi_app.services.video_auditor import audit_video_esperanto
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
    send_50_percent_milestone_message,
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


def _build_rover_incident_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚨 Seguridad", callback_data="rover_incident:Seguridad en actividad")],
            [InlineKeyboardButton("🛠️ Plataforma", callback_data="rover_incident:Fallo en plataforma o bot")],
            [InlineKeyboardButton("⚠️ Conducta", callback_data="rover_incident:Conducta inadecuada observada")],
        ]
    )


async def _notify_leader_for_final_approval(
    *,
    patrol_name: str,
    delegation_name: str,
    leader_email: str,
    review_url: str,
) -> None:
    if not leader_email:
        return

    subject = f"Ligilo: {patrol_name} requiere tu 'Siempre Listos'"
    body = (
        f"La patrulla {patrol_name} ({delegation_name}) ha completado su video de YouTube.\n\n"
        "La IA ya terminó la validación técnica y auditoría inicial.\n"
        "Ahora debes realizar la aprobación final humana según política WOSM.\n\n"
        "Haz clic aquí para dar tu 'Siempre Listos':\n"
        f"{review_url}\n"
    )
    await asyncio.to_thread(
        send_mail,
        subject,
        body,
        os.getenv("DEFAULT_FROM_EMAIL", "no-reply@ligilo.local"),
        [leader_email],
        False,
    )


async def _notify_sel_patch_preparation(
    *,
    patrol_name: str,
    delegation_name: str,
    effective_score: int,
) -> None:
    target = os.getenv("SEL_PATCH_PREP_EMAIL", "operations@sel.local")
    subject = f"SEL Patch Prep: {patrol_name} alcanzó B1"
    body = (
        f"La patrulla {patrol_name} ({delegation_name}) alcanzó nivel B1 en PoentaroEngine.\n"
        f"Puntaje compuesto actual: {effective_score}.\n\n"
        "Acción requerida: preparar logística de parche físico para stand SEL."
    )
    await asyncio.to_thread(
        send_mail,
        subject,
        body,
        os.getenv("DEFAULT_FROM_EMAIL", "no-reply@ligilo.local"),
        [target],
        False,
    )


async def _send_poentaro_milestone_messages(
    update: Update,
    patrol: dict,
    points_result: dict,
) -> None:
    milestones = list(points_result.get("mcer_milestones") or [])
    if not milestones:
        return

    if "A1" in milestones:
        await update.message.reply_text(
            "🌟 ¡Ánimo, patrulla! Superaron el umbral A1. "
            "Van por gran camino en vocabulario scout y comunicación básica."
        )

    if "A2" in milestones:
        await update.message.reply_text(
            "🎉 ¡Felicitaciones! Alcanzaron nivel A2. "
            "Su interacción en Esperanto ya es funcional y consistente en equipo."
        )

    if "B1" in milestones:
        await update.message.reply_text(
            "🏅 ¡Excelente! Alcanzaron nivel B1. "
            "Ya notificamos automáticamente a la SEL para la preparación del parche físico."
        )
        poentaro = points_result.get("poentaro") or {}
        try:
            await _notify_sel_patch_preparation(
                patrol_name=str(patrol.get("name") or "Patrulla"),
                delegation_name=str(patrol.get("delegation_name") or "Delegación"),
                effective_score=int(poentaro.get("effective_score") or 0),
            )
        except Exception:
            pass


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


def _resolve_mcer_level(sel_points: int) -> str:
    # Definitive SEL thresholds:
    # A1 0-1000, A2 1001-3000, B1 3001-6000, B2 6001+
    if sel_points >= 6001:
        return "B2"
    if sel_points >= 3001:
        return "B1"
    if sel_points >= 1001:
        return "A2"
    return "A1"


async def _evaluate_mcer_message(text: str, sel_points: int) -> dict[str, object]:
    level = _resolve_mcer_level(sel_points)
    return await asyncio.to_thread(
        evaluate_mcer_progress,
        text,
        mcer_level=level,
    )


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
        await _send_poentaro_milestone_messages(update, patrol, points_result)
        try:
            mcer = await _evaluate_mcer_message(
                incoming_text,
                int(points_result.get("sel_points") or patrol.get("sel_points") or 0),
            )
            await update.message.reply_text(
                "🎓 Skolto-Instruisto (MCER)\n"
                f"Nivel: {mcer.get('mcer_level')}\n"
                f"Lexiko: {mcer.get('lexical_score')}/100 | Gramatiko: {mcer.get('grammar_score')}/100\n"
                f"Partopreno: {mcer.get('participation_score')}/100\n\n"
                f"{mcer.get('personalized_congrats')}\n"
                f"Siguiente foco: {mcer.get('next_focus')}\n"
                f"Feedback asertivo: {mcer.get('assertive_feedback')}"
            )
        except Exception:
            # Keep mission flow resilient if pedagogical scoring fails.
            pass


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


async def handle_atestilo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /atestilo command: Generate MCER linguistic excellence certificate.
    
    - If < 80% of B1 (2,401 pts): Show watermarked preview + motivational message
    - If >= 80% of B1: Show full certificate without watermark
    - Notify leader via Dashboard when scouts request their certificate
    """
    if not update.effective_chat or not update.message:
        return

    patrol = await find_patrol_by_chat_id(update.effective_chat.id)
    if patrol is None:
        await update.message.reply_text(
            "Para solicitar tu certificado, primero vincula tu patrulla con /start."
        )
        return

    await update.message.reply_text(
        "🏆 Generando tu Atestilo de Ligilo...\n\n"
        "⏳ Un momento mientras calculamos tu progreso MCER..."
    )

    # Get or create certificate
    cert_data = await get_mcer_certificate(update.effective_chat.id)
    
    if not cert_data.get("ok"):
        await update.message.reply_text(
            "❌ No pude generar tu certificado ahora. Intenta nuevamente en unos minutos."
        )
        return

    patrol_name = cert_data.get("patrol_name")
    sister_name = cert_data.get("sister_patrol_name")
    mcer_level = cert_data.get("mcer_level")
    points = cert_data.get("points")
    with_watermark = cert_data.get("with_watermark")
    progress_pct = cert_data.get("progress_to_b1_pct")
    points_to_b1 = cert_data.get("points_to_b1")

    # Generate PDF
    from apps.scouting.services.certificate_generator import generate_mcer_certificate

    try:
        pdf_bytes = generate_mcer_certificate(
            patrol_name=patrol_name,
            sister_patrol_name=sister_name,
            delegation_name=cert_data.get("delegation_name"),
            mcer_level=mcer_level,
            points=points,
            match_start_date=cert_data.get("match_start_date"),
            certification_code=cert_data.get("certification_code"),
            qr_png_b64=cert_data.get("qr_png_b64"),
            leader_name=cert_data.get("leader_name"),
            with_watermark=with_watermark,
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error al generar el PDF: {str(e)[:100]}"
        )
        return

    # Determine message based on progress
    if with_watermark:
        # Preview mode (< 80% of B1)
        level_emoji_map = {"A1": "🌱", "A2": "🌿", "B1": "🌲", "B2": "🏔️"}
        level_emoji = level_emoji_map.get(mcer_level, "⭐")
        
        message = (
            f"{level_emoji} *¡Estás muy cerca, Explorador!*\n\n"
            f"Has alcanzado el nivel *{mcer_level}* con *{points} puntos*.\n"
            f"Progreso hacia B1: *{progress_pct}%*\n\n"
            f"Te faltan *{points_to_b1} puntos* para desbloquear tu certificación oficial sin marca de agua.\n\n"
            f"💡 *Próximo paso:* Completa tu video de YouTube con tu patrulla hermana "
            f"_{sister_name}_ para limpiar la previsualización.\n\n"
            f"_Este es tu Atestilo de Ligilo en modo vista previa._"
        )
    else:
        # Full certificate (>= 80% of B1)
        message = (
            f"🎉 *¡Felicitaciones, {patrol_name}!*\n\n"
            f"Has alcanzado el nivel *{mcer_level}* con *{points} puntos efectivos*.\n\n"
            f"Tu certificado de Excelencia Lingüística SEL está listo en alta resolución.\n\n"
            f"🤝 Compartido con tu patrulla hermana: *{sister_name}*\n\n"
            f"Escanea el código QR en tu certificado para ver tu progreso en el Muro de la Fama."
        )

    # Send PDF document
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=pdf_bytes,
        filename=f"Atestilo_{patrol_name}_{mcer_level}.pdf",
        caption=message,
        parse_mode=ParseMode.MARKDOWN,
    )

    # Notify leader
    notification_result = await notify_leader_about_certificate(update.effective_chat.id)
    if notification_result.get("notified"):
        leader_email = notification_result.get("leader_email")
        # Send email to leader (async, non-blocking)
        try:
            from django.core.mail import send_mail
            from asgiref.sync import sync_to_async
            
            await sync_to_async(send_mail)(
                subject=f"📊 {patrol_name} está visualizando su certificado MCER",
                message=(
                    f"Hola,\n\n"
                    f"La patrulla {patrol_name} acaba de solicitar su Atestilo de Ligilo.\n\n"
                    f"Nivel actual: {mcer_level}\n"
                    f"Puntos: {points}\n"
                    f"Progreso a B1: {progress_pct}%\n\n"
                    f"¿Deseas enviarles un mensaje de aliento para el tramo final?\n\n"
                    f"Accede al Dashboard del Líder para ver más detalles:\n"
                    f"{os.getenv('DJANGO_PUBLIC_BASE_URL', 'http://localhost:8000')}/scouts/dashboard/\n\n"
                    f"—\n"
                    f"Skolto-Instruisto (IA)"
                ),
                from_email=os.getenv("DEFAULT_FROM_EMAIL", "noreply@ligilo.org"),
                recipient_list=[leader_email],
                fail_silently=True,
            )
        except Exception:
            pass  # Emails are best-effort, don't block bot flow


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

    await update.message.reply_text("Recibi tu video. Validando metadata de YouTube...")
    validation = validate_youtube_video(raw_link, patrol_name=str(patrol.get("name") or ""))
    if not validation.get("valid"):
        errors = validation.get("errors") or ["No paso validacion de YouTube."]
        await update.message.reply_text(
            "No pude aceptar la entrega por ahora:\n- " + "\n- ".join(str(e) for e in errors)
        )
        return

    await update.message.reply_text("Metadata OK. Ejecutando auditoria IA del video...")
    audit = await audit_video_esperanto(
        video_url=raw_link,
        video_id=validation.get("video_id") or video_id,
        patrol_name=str(patrol.get("name") or ""),
    )

    submission_result = await create_youtube_submission_by_chat(
        update.effective_chat.id,
        youtube_url=raw_link,
        validation_result=validation,
        audit_result=audit,
    )
    if not submission_result.get("ok"):
        await update.message.reply_text("No pude guardar la entrega. Intenta de nuevo en unos minutos.")
        return

    if not audit.get("audit_valid"):
        await update.message.reply_text(
            "La auditoria IA marco esta entrega para revision adicional. "
            "Tu lider la evaluara manualmente antes de aprobarla."
        )
        return

    leader_email = submission_result.get("leader_email") or "(sin email de lider)"
    review_url = submission_result.get("leader_review_url") or ""
    if submission_result.get("leader_approval_required") and review_url:
        try:
            await _notify_leader_for_final_approval(
                patrol_name=str(patrol.get("name") or "Patrulla"),
                delegation_name=str(patrol.get("delegation_name") or "Delegación"),
                leader_email=str(submission_result.get("leader_email") or ""),
                review_url=review_url,
            )
        except Exception:
            # We keep bot flow resilient even if email delivery fails.
            pass

    await update.message.reply_text(
        "¡Entrega registrada y validada por IA!\n"
        "Ahora falta la validacion humana final del lider (Siempre Listos).\n\n"
        f"Notificacion enviada a: {leader_email}\n"
        f"Enlace de aprobacion: {review_url}"
    )


async def handle_reportar_incidencia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return

    patrol = await find_patrol_by_chat_id(update.effective_chat.id)
    if patrol is None:
        await update.message.reply_text("Antes de reportar, vincula tu patrulla con /start.")
        return

    if not patrol.get("is_rover_moderator"):
        await update.message.reply_text(
            "Este canal prioritario es exclusivo para Modo Rover (18+). "
            "Si necesitas ayuda, usa /status o contacta a tu lider."
        )
        return

    manual_text = " ".join(context.args).strip() if context.args else ""
    if manual_text:
        result = await create_rover_incident(update.effective_chat.id, description=manual_text)
        if result.get("ok"):
            await update.message.reply_text(
                f"Incidencia prioritaria registrada (#{result.get('incident_id')}). "
                "El equipo de lideres la revisara de inmediato."
            )
        else:
            await update.message.reply_text("No pude registrar la incidencia. Intenta nuevamente.")
        return

    await update.message.reply_text(
        "Modo Rover activo: selecciona tipo de incidencia prioritaria o envia texto directo con /reportar_incidencia <detalle>",
        reply_markup=_build_rover_incident_markup(),
    )


async def handle_rover_incident_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return

    query = update.callback_query
    payload = query.data or ""
    if not payload.startswith("rover_incident:"):
        return

    description = payload.split(":", 1)[1].strip()
    chat_id = query.message.chat_id if query.message else None
    if chat_id is None:
        await query.answer("No se pudo determinar el chat", show_alert=True)
        return

    result = await create_rover_incident(chat_id, description=description)
    if not result.get("ok"):
        await query.answer("No se pudo registrar la incidencia", show_alert=True)
        return

    await query.answer("Incidencia prioritaria enviada", show_alert=False)
    await query.edit_message_text(
        f"Incidencia prioritaria registrada (#{result.get('incident_id')}). Lideres notificados."
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
        await _send_poentaro_milestone_messages(update, patrol, points_result)
        try:
            mcer = await _evaluate_mcer_message(
                transcript_text,
                int(points_result.get("sel_points") or patrol.get("sel_points") or 0),
            )
            await update.message.reply_text(
                "🎓 Skolto-Instruisto (MCER)\n"
                f"Nivel: {mcer.get('mcer_level')}\n"
                f"Lexiko: {mcer.get('lexical_score')}/100 | Gramatiko: {mcer.get('grammar_score')}/100\n"
                f"Partopreno: {mcer.get('participation_score')}/100\n\n"
                f"{mcer.get('personalized_congrats')}\n"
                f"Siguiente foco: {mcer.get('next_focus')}\n"
                f"Feedback asertivo: {mcer.get('assertive_feedback')}"
            )
        except Exception:
            pass
        # Sprint 2: Notify sister patrol about the audio
        await notify_sister_patrol_on_audio(update, patrol.get("id"))
        
        # Sprint 2: Monetization trigger - check 50% milestone
        milestone_info = points_result.get("milestone_50_percent")
        if milestone_info and milestone_info.get("crossed_50_percent"):
            await send_50_percent_milestone_message(
                bot_instance=update.effective_user.bot,
                chat_id=chat_id,
                patrol_name=patrol.get("name", "Patrulla"),
                current_points=milestone_info.get("current_points", 0),
                target_points=milestone_info.get("milestone_target_points", 0),
                milestone_tier=milestone_info.get("milestone_tier", "bronze"),
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
        app.add_handler(CommandHandler("atestilo", handle_atestilo))
        app.add_handler(CommandHandler("entregar", handle_entregar))
        app.add_handler(CommandHandler("reportar_incidencia", handle_reportar_incidencia))
        app.add_handler(CommandHandler("miaj_punktoj", handle_miaj_punktoj))
        app.add_handler(CommandHandler("pagi", handle_pagi))
        app.add_handler(CallbackQueryHandler(handle_payment_callback, pattern=r"^payment:"))
        app.add_handler(CallbackQueryHandler(handle_rover_incident_callback, pattern=r"^rover_incident:"))
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
