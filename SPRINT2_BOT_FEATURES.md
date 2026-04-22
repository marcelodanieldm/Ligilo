# Sprint 2 - Features del Bot Telegram 🤖
## Lista de Implementación para el Equipo de Desarrollo

---

## 📋 Feature 1: `/miaj_punktoj` - Stelo-Meter Visual

**Ubicación:** `fastapi_app/services/telegram_bot_sprint2.py` → `handle_miaj_punktoj()`

### Funcionalidad
Comando que muestra el progreso visual de la patrulla hacia el parche SEL (Stelo-Meter).

### Respuesta del Bot
```
🥈 Stelo-Meter

Patrulla: `Patrulla Los Halcones`
Delegación: `Argentina - Buenos Aires`

Puntos SEL: `1245`
Tier Actual: Plata

Progreso hacia parche:
`██████░░░░` 60%

🎯 Meta próxima: 2000 pts (faltan 755 pts)

✅ ¡Listo para el parche Plata!
Usa `/qr` para obtener el código QR en el stand SEL.
```

### Detalles Técnicos
- **Barra de progreso**: 10 segmentos (█░)
- **Tier emojis**: 🥉 Bronce (500pts) | 🥈 Plata (1000pts) | 🥇 Oro (2000pts)
- **Integración**: Llama a `build_certification_qr_payload()` del db_bridge
- **Datos mostrados**:
  - Nombre patrulla + delegación
  - SEL puntos totales
  - Tier certificado actual
  - Porcentaje hacia próximo tier
  - Puntos faltantes

### Comportamiento Edge Cases
- Si patrulla no está vinculada: Solicita `/start`
- Si no hay datos de certificación: Muestra "Sin certificar" con 0 puntos
- Si patrulla ha alcanzado Oro (2000+): Dice "Meta alcanzada ✅"

---

## 💬 Feature 2: Notificación Proactiva - Audio Hermano

**Ubicación:** `fastapi_app/services/telegram_bot_sprint2.py` → `notify_sister_patrol_on_audio()`

### Funcionalidad
Cuando una patrulla envía un audio validado en Esperanto, el bot notifica automáticamente a su patrulla hermana (matched patrol) para responder y ganar puntos.

### Flujo de Activación
```
1. Usuario A envía audio en Telegram
2. Bot valida y da +50 pts a Usuario A
3. Bot busca patrulla hermana (PatrolMatch con status='active')
4. Bot envía notificación a chat de patrulla hermana:
```

### Mensaje Enviado
```
🎤 ¡La patrulla *Patrulla Los Halcones* te envió un mensaje en Esperanto!

Escúchalo en el stand SEL y responde para ganar *+50 puntos extra*.

Delegación: Argentina - Buenos Aires
```

### Detalles Técnicos
- **Consulta DB**: `PatrolMatch.objects.filter(patrol_a_id=patrol_id OR patrol_b_id=patrol_id, status='active')`
- **Wrapped con `@sync_to_async`**: Permite async calls a Django ORM
- **Envío**: Usa `update.effective_user.bot.send_message()` con chat_id de patrulla hermana
- **Error handling**: Logs silenciosos si patrulla hermana no tiene telegram_chat_id

### Comportamiento Edge Cases
- Si patrulla no tiene hermana vinculada: No envía notificación
- Si chat_id hermano es nulo: Skips (logs error)
- Si múltiples matches (rara): Notifica a todas

---

## 💳 Feature 3: `/pagi` - Stripe Payment Buttons

**Ubicación:** `fastapi_app/services/telegram_bot_sprint2.py` → `handle_pagi()` + `handle_payment_callback()`

### Funcionalidad
Despliega un menú de compra integrado con Stripe Payment Links en Telegram.

### Interfaz en Bot
Botones interactivos:
```
[🎟️ Stelo Pass ($3)]
[⭐ Premium Features ($5)]
[🚀 Training Boost ($2)]
[ℹ️ Más info]
```

### Productos & Precios
| Producto | Precio | Descripción |
|----------|--------|-------------|
| **Stelo Pass** | $3 USD | Acceso a misiones avanzadas y desafíos especiales |
| **Premium Features** | $5 USD | Analytics de patrulla, reportes semanales, badges |
| **Training Boost** | $2 USD | 5 sesiones extra de tutoría fónica con IA |

### Flujo de Pago
```
1. Usuario ejecuta /pagi
2. Bot muestra 4 botones (3 productos + info)
3. Usuario hace clic en producto
4. Bot dispara handle_payment_callback()
5. Stripe crea sesión de checkout
6. Bot envía link de pago a usuario
7. Usuario abre link → Stripe checkout en navegador
```

### Detalles Técnicos
- **Callback pattern**: `payment:{product_type}:{patrol_id}`
- **Products enum**: stelo_pass | premium_features | training_boost
- **Precios en centavos USD**: 300 | 500 | 200
- **Stripe Session metadata**:
  ```python
  {
    "patrol_id": str(patrol_id),
    "product_type": product_type,
    "telegram_chat_id": str(chat_id)
  }
  ```
- **URLs de redirección** (env vars):
  - `STRIPE_SUCCESS_URL` (default: https://ligilo.sel.org/success)
  - `STRIPE_CANCEL_URL` (default: https://ligilo.sel.org/cancel)

### Configuración Requerida
```bash
# .env variables
STRIPE_SECRET_KEY=sk_test_... | sk_live_...
STRIPE_SUCCESS_URL=https://ligilo.sel.org/success
STRIPE_CANCEL_URL=https://ligilo.sel.org/cancel
```

### Webhook de Confirmación (POST-IMPLEMENTACIÓN)
Después del primer pago, registrar webhook Stripe en:
```
POST /fastapi/stripe-webhook
Event types: payment_intent.succeeded, charge.refunded
```

---

## 🔧 Registro de Handlers en Bot

Los handlers están registrados en `init_telegram_application()`:

```python
# Comandos
app.add_handler(CommandHandler("miaj_punktoj", handle_miaj_punktoj))
app.add_handler(CommandHandler("pagi", handle_pagi))

# Callbacks de pago
app.add_handler(CallbackQueryHandler(handle_payment_callback, pattern=r"^payment:"))

# Dentro de handle_voice_message (para notificación proactiva)
await notify_sister_patrol_on_audio(update, patrol.get("id"))
```

---

## 📦 Dependencias Verificadas

✅ `python-telegram-bot>=21.7,<22.0` - Ya instalado
✅ `stripe>=10.0` - Ya en requirements.txt
✅ `PyJWT>=2.8,<3.0` - Ya instalado (para QR)
✅ `asgiref` - Ya en Django

**Nueva función en db_bridge:**
- `build_certification_qr_payload(patrol_id)` → Returns: tier, current_points, required_points, eligible

---

## 🧪 Testing Manual

### Test 1: `/miaj_punktoj`
```
1. Enviar comando /miaj_punktoj
2. Verificar:
   - ✅ Muestra nombre patrulla
   - ✅ Barra de progreso (10 segmentos)
   - ✅ Tier correcto basado en puntos
   - ✅ Calcula porcentaje correctamente
```

### Test 2: Notificación Hermana
```
1. Crear 2 patrullas vinculadas (PatrolMatch active)
2. Patrulla A envía audio validable en Esperanto
3. Verificar:
   - ✅ Patrulla A obtiene +50 pts
   - ✅ Patrulla B recibe mensaje en su chat
   - ✅ Mensaje incluye nombre Patrulla A y delegación
```

### Test 3: `/pagi` → Stripe
```
1. Enviar comando /pagi
2. Hacer clic en "Stelo Pass ($3)"
3. Verificar:
   - ✅ Bot genera URL de checkout Stripe
   - ✅ Se envía link al usuario
   - ✅ Link abre en navegador (test payment works)
4. Post-pago verificar metadata en Stripe dashboard
```

---

## 📝 Notas de Implementación

1. **Proactive Notification**: Usa `@sync_to_async` porque consulta Django ORM desde contexto async de FastAPI
2. **Stripe Keys**: Usar `sk_test_*` en desarrollo, cambiar a `sk_live_*` en producción
3. **Error Handling**: Todas las funciones loguean errores pero no rompen el flujo del bot
4. **Performance**: Las querys se hacen con `.select_related()` para reducir DB calls
5. **Timezone**: Los puntos y fechas usan `timezone.now()` (Django)

---

## 🚀 Orden de Implementación Recomendado

1. **Feature 1**: `/miaj_punktoj` (simple, sin dependencias externas)
2. **Feature 2**: Notificación proactiva (simple, solo consulta DB)
3. **Feature 3**: `/pagi` (requiere Stripe API key y webhooks)

---

## 📞 Contacto & Preguntas

- **Puntos SEL**: Ver `POINT_RULES` en `apps/scouting/models.py`
- **Stelo-Meter tiers**: 500/1000/2000 puntos
- **Stripe test card**: 4242 4242 4242 4242 (expires: 12/34 cvv: 123)

**Status**: ✅ Sintaxis validada | ✅ Django checks pass | 🟡 Listo para implementación
