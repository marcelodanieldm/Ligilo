# "El Momento del Pago" - Estrategia de Monetización Orgánica 💳

**Objetivo**: Activar CTAs (Call To Action) de pago cuando el usuario está más "enganchado" y receptivo.

---

## 🎯 Principio Core

Los scouts están más motivados a convertir (comprar) cuando:
1. **Ya tienen logro visible** (han progresado 50% del camino)
2. **Sienten momentum** (acaban de ganar puntos)
3. **Ven el destino cercano** (el próximo parche está "al alcance")

> **"No vendemos en frío. Vendemos un sueño que el usuario casi logró."**

---

## 🔄 Flujo de Activación

```
Scout envía audio
      ↓
Audio validado (+50 pts)
      ↓
Sistema detecta: ¿Cruzó 50% de progresión?
      ↓ SÍ
Bot envía mensaje celebratorio + CTA Stelo Pass
      ↓
Scout hace clic → Stripe checkout session
      ↓
Pago completado → QR activado + parche asegurado
```

---

## 📊 Ejemplo Real: Progresión a Plata

### Scenario 1: Scout en ruta a Plata (1000 pts)
```
Threshold actual: Bronze (500 pts)
Próximo threshold: Plata (1000 pts)
Bracket: 500 → 1000 (tamaño: 500)

Scout tiene: 680 pts
  - Progreso: (680 - 500) / 500 = 36%
  - 50% milestone NO activado aún

Scout recibe +50 pts → 730 pts
  - Progreso: (730 - 500) / 500 = 46%
  - 50% milestone NO activado aún

Scout recibe +50 pts → 780 pts
  - Progreso: (780 - 500) / 500 = 56% ✓
  - 50% MILESTONE CRUZADO! 🎉
```

**Bot envía:**
```
🥈 ¡Increíble progreso!

Ya eres medio-experto en Esperanto 🌟

Has alcanzado el 50% del camino hacia tu parche Plata:
`780 / 1000 puntos`

Ahora viene lo emocionante... ✨
¿Sabías que puedes asegurar tu parche físico de la SEL ya mismo?

Con Stelo Pass obtienes:
✅ Tu certificado digital con QR
✅ Acceso a misiones avanzadas
✅ Reconocimiento en la plataforma global SEL

Activar ahora es solo $3 y asegura tu logro.

[🎟️ Activar Stelo Pass →] [Quizás después]
```

---

## 🔧 Implementación Técnica

### A. Detección de 50% (db_bridge.py)

**Funciones nuevas:**
- `_get_tier_progress_info(sel_points)` → Calcula progreso en tier actual
- `_check_50_percent_milestone(prev_pts, new_pts)` → Detecta si se cruzó 50%

**Integración en `award_points_by_chat()`:**
```python
# Después de otorgar puntos:
milestone_info = _check_50_percent_milestone(previous_points, patrol.sel_points)
if milestone_info.get("crossed_50_percent"):
    result["milestone_50_percent"] = milestone_info
```

**Retorna:**
```python
{
    "crossed_50_percent": True,
    "milestone_tier": "silver",
    "milestone_target_points": 1000,
    "current_points": 780,
}
```

### B. Mensaje CTA (telegram_bot_sprint2.py)

**Nueva función:** `send_50_percent_milestone_message()`

**Parámetros:**
- `bot_instance` - Instancia del bot Telegram
- `chat_id` - Chat ID del scout
- `patrol_name` - Nombre de la patrulla
- `current_points` - Puntos actuales (ej: 780)
- `target_points` - Próximo threshold (ej: 1000)
- `milestone_tier` - Tier alcanzado (bronze/silver/gold)

**Características:**
- ✅ Mensaje celebratorio personalizado
- ✅ Emoji dinámico según tier (🥉 🥈 🥇)
- ✅ Botón CTA "Activar Stelo Pass" → Callback payment
- ✅ Botón "Quizás después" → Dismiss silencioso
- ✅ Error handling silencioso (no bloquea si falla)

### C. Integración en Bot (telegram_bot.py)

**En `handle_voice_message()`**, después de otorgar puntos:

```python
milestone_info = points_result.get("milestone_50_percent")
if milestone_info and milestone_info.get("crossed_50_percent"):
    await send_50_percent_milestone_message(
        bot_instance=update.effective_user.bot,
        chat_id=chat_id,
        patrol_name=patrol.get("name"),
        current_points=milestone_info.get("current_points"),
        target_points=milestone_info.get("milestone_target_points"),
        milestone_tier=milestone_info.get("milestone_tier"),
    )
```

---

## 💰 Conversion Psychology

### Por qué funciona en 50%:

| % de progreso | Psicología | Tasa conversión esperada |
|---|---|---|
| 0-25% | "Acabo de empezar" | 2% (muy bajo) |
| 25-50% | "Voy bien, pero lejos" | 5% (bajo) |
| **50-75%** | **"Casi lo logro"** | **35-40%** (ALTO) ⭐ |
| 75-100% | "Está cerca, pero..." | 45% (muy alto, pero tardo) |

**En 50%:** 
- Ya demostró engagement (no es flojo)
- Puede ver el finish line
- Falta poco → baja fricción mental
- "Asegurar" el logro suena razonable

---

## 📈 Métricas a Monitorear

### Post-Implementación:
```
1. CTR (Click-Through Rate) en CTA
   - Clicks en "Activar Stelo Pass" / Total mensajes enviados
   - Target: > 20%

2. Conversion Rate (CR)
   - Pagos completados / Clicks en CTA
   - Target: > 8%

3. Time-to-Conversion (TTC)
   - Minutos entre 50% milestone y pago
   - Baseline: < 5 minutos

4. Revenue per Milestone (RPM)
   - Total ingresos / Total milestones alcanzados
   - Target: > $0.25 USD

5. LTV Impact (Lifetime Value)
   - Comparar LTV de compradores vs no-compradores
   - Hipótesis: Compradores = 3x LTV
```

---

## 🛡️ Edge Cases & Handling

### Caso 1: Usuario salta 50% en un pago grande
```
Scout tiene 450 pts
Gana +500 pts (misión YouTube) → 950 pts

Cálculo:
- prev: 450 (progreso 0% en Bronze)
- new: 950 (progreso 90% en Silver)
- Salta de 0% → 90%, cruza 50% ✓

Mensaje enviado: SÍ, con tier "silver"
```

### Caso 2: Usuario llega a 100% sin pasar 50% en este award
```
Scout tiene 480 pts (96% en Bronze)
Gana +20 pts → 500 pts (alcanza Silver)

Cálculo:
- prev: 480 (96% en Bronze)
- new: 500 (0% en Silver, milestone boundary)
- No cruza 50% en Silver aún

Mensaje enviado: NO (esperaría siguientes puntos)
```

### Caso 3: Usuario ya rechazó en session anterior
```
Usuario vio 50% milestone, hizo clic "Quizás después"
Sistema registra: "dismissed_50_percent_cta"

Si cruza 50% en OTRO tier (ej: Silver → Gold):
Mensaje enviado: SÍ (nueva tier, nuevo momentum)
```

---

## 🚀 Activación Post-Deploy

1. **Day 1-3**: Monitor CTR en logs
2. **Day 4-7**: Ajustar mensaje si CTR < 15%
3. **Week 2**: Análisis de CR y Revenue
4. **Week 3**: A/B test variantes de CTA (si es necesario)

---

## 📋 Checklist de Lanzamiento

- ✅ `_check_50_percent_milestone()` detección en db_bridge
- ✅ `award_points_by_chat()` retorna milestone_info
- ✅ `send_50_percent_milestone_message()` handler creado
- ✅ Integración en `handle_voice_message()` 
- ✅ Sintaxis validada (py_compile ✓)
- ✅ Django checks pass ✓
- ✅ Documentación completa
- ⏳ **Pendiente:** Testing en staging con usuarios reales
- ⏳ **Pendiente:** Configurar webhook para registrar "payment_intent.succeeded" eventos

---

## 🎬 Próximas Fases

### Phase 2: Múltiples Triggers
- Milestone en 25% (early engagement tester)
- Milestone en 75% (urgency closer)
- Post-certification (lock-in phase)

### Phase 3: Personalización
- A/B test mensajes por idioma/región
- Descuentos dinámicos basados en cohort
- Gamified upsell ("gasta $5 más para Gold")

### Phase 4: Attribution
- Vincular pagos a específicos scouts/patrullas
- Cohort analysis: cuál tier tiene mejor LTV
- Predict churn risk y intervenir pre-50%

---

**Status**: ✅ Implementado | ✅ Validado | 🟡 Listo para staging
