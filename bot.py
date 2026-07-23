# -*- coding: utf-8 -*-
"""
Bot Manada — check-in diario de 4 hábitos.

Todos los días a las 9:00pm (hora México) manda 4 preguntas con botones
Sí/No, guarda las respuestas y muestra rachas. Comandos: /start /hoy /resumen.

Variables de entorno:
  BOT_TOKEN      token de @BotFather (obligatoria)
  SUPABASE_URL   https://xxxx.supabase.co   (opcional pero recomendada)
  SUPABASE_KEY   secret key de Supabase     (opcional pero recomendada)

Sin Supabase guarda en archivo local (se pierde al reiniciar el servidor).
"""
import asyncio
import copy
import json
import logging
import os
import time
from datetime import datetime, time as dt_time, timedelta

import pytz
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN    = os.environ["BOT_TOKEN"]
TIMEZONE = pytz.timezone("America/Mexico_City")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_KEY)
SUPABASE_TABLE_URL = f"{SUPABASE_URL}/rest/v1/bot_data" if SUPABASE_ENABLED else None

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registro.json")

HABITOS = [
    ("agua",      "💧 ¿Tomé al menos 2 litros de agua?"),
    ("oracion",   "🙏 ¿Tuve una oración profunda con Jehová?"),
    ("lectura",   "📖 ¿Leí al menos 10 minutos?"),
    ("ejercicio", "💪 ¿Hice al menos 30 minutos de ejercicio?"),
]


# ---------------------------------------------------------------- storage
def _headers(extra=None):
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    if extra:
        h.update(extra)
    return h


_cache = {"value": None, "ts": 0.0}
_CACHE_TTL = 3
# Anti-wipe: no escribir a Supabase hasta haber leído bien al menos una vez.
_read_ok_once = False


def load_data() -> dict:
    global _read_ok_once
    if SUPABASE_ENABLED:
        now = time.monotonic()
        if _cache["value"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
            data = copy.deepcopy(_cache["value"])
        else:
            try:
                resp = requests.get(
                    SUPABASE_TABLE_URL,
                    params={"id": "eq.1", "select": "data"},
                    headers=_headers(), timeout=10,
                )
                resp.raise_for_status()
                rows = resp.json()
                data = rows[0]["data"] if rows else {}
                _read_ok_once = True
                _cache["value"] = copy.deepcopy(data)
                _cache["ts"] = now
            except Exception as e:
                logger.error(f"Supabase read error ({e}); usando cache")
                data = copy.deepcopy(_cache["value"]) if _cache["value"] is not None else {}
    else:
        data = {}
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"registro.json ilegible ({e})")
    data.setdefault("chat_id", None)
    data.setdefault("habitos", [])
    data.setdefault("flow", None)
    return data


def save_data(data: dict):
    if SUPABASE_ENABLED:
        if not _read_ok_once:
            logger.error("save bloqueado: sin lectura exitosa previa (anti-wipe)")
            return
        try:
            resp = requests.post(
                SUPABASE_TABLE_URL,
                params={"on_conflict": "id"},
                headers=_headers({"Content-Type": "application/json",
                                  "Prefer": "resolution=merge-duplicates,return=minimal"}),
                json={"id": 1, "data": data}, timeout=10,
            )
            resp.raise_for_status()
            _cache["value"] = copy.deepcopy(data)
            _cache["ts"] = time.monotonic()
            return
        except Exception as e:
            logger.error(f"Supabase write error ({e}); guardando local")
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


# ---------------------------------------------------------------- dominio
def hoy_str() -> str:
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")


def registrar_dia(data: dict, respuestas: dict):
    fecha = hoy_str()
    data["habitos"] = [h for h in data["habitos"] if h["fecha"] != fecha]
    data["habitos"].append({"fecha": fecha, "respuestas": respuestas})
    data["habitos"].sort(key=lambda h: h["fecha"])
    data["flow"] = None
    save_data(data)


def get_streak(data: dict, clave: str) -> int:
    """Días consecutivos cumpliendo el hábito, contando hacia atrás desde el
    registro más reciente."""
    regs = sorted(data["habitos"], key=lambda h: h["fecha"], reverse=True)
    streak = 0
    expected = None
    for h in regs:
        hdate = datetime.strptime(h["fecha"], "%Y-%m-%d").date()
        if expected is None:
            expected = hdate
        if hdate == expected:
            if h["respuestas"].get(clave):
                streak += 1
                expected = hdate - timedelta(days=1)
            else:
                break
        elif hdate < expected:
            break
    return streak


def rachas_text(data: dict) -> str:
    lines = []
    for clave, pregunta in HABITOS:
        s = get_streak(data, clave)
        if s >= 2:
            emoji = pregunta.split()[0]
            lines.append(f"{emoji} racha de {s} días")
    return "\n".join(lines)


NOMBRES_CORTOS = {
    "agua":      "💧 Agua (2L)",
    "oracion":   "🙏 Oración",
    "lectura":   "📖 Lectura",
    "ejercicio": "💪 Ejercicio",
}


def resumen_periodo(data: dict, titulo: str, fecha_ini: str, fecha_fin: str,
                    dias_periodo: int) -> str:
    """Retroalimentación de un rango de fechas (inclusive), texto plano."""
    regs = [h for h in data["habitos"] if fecha_ini <= h["fecha"] <= fecha_fin]
    if not regs:
        return f"{titulo}\n\nSin registros en este periodo. ¡La próxima vez sí! 💛"

    total = len(regs)
    texto = f"{titulo}\n({fecha_ini} → {fecha_fin})\n\n"
    mejor, peor = None, None
    for clave, _ in HABITOS:
        cumplidos = sum(1 for h in regs if h["respuestas"].get(clave))
        pct = round(cumplidos / total * 100)
        icon = "🌟" if pct >= 80 else "👍" if pct >= 50 else "🔴"
        texto += f"{NOMBRES_CORTOS[clave]}: {cumplidos}/{total} días ({pct}%) {icon}\n"
        if mejor is None or pct > mejor[1]:
            mejor = (clave, pct)
        if peor is None or pct < peor[1]:
            peor = (clave, pct)

    texto += f"\n📅 Días contestados: {total} de {dias_periodo}\n"

    rachas = rachas_text(data)
    if rachas:
        texto += f"\n🔥 Rachas activas:\n{rachas}\n"

    # Retroalimentación tipo coach
    promedio = sum(
        sum(1 for h in regs if h["respuestas"].get(c)) for c, _ in HABITOS
    ) / (total * len(HABITOS)) * 100
    texto += "\n💬 Retroalimentación:\n"
    if promedio >= 80:
        texto += "¡Excelente, Priscila! Constancia de lobo alfa 🐺✨ Sigue así."
    elif promedio >= 60:
        texto += "Buen ritmo 💪 Ya casi. Un empujoncito más y llegas al 80%."
    elif promedio >= 40:
        texto += "Vamos a medias 😌 Elige UN hábito y hazlo sagrado esta semana."
    else:
        texto += "Semana difícil, y está bien 💛 Hoy es un buen día para reiniciar."
    if mejor and peor and mejor[0] != peor[0] and mejor[1] != peor[1]:
        texto += f"\nTu fuerte: {NOMBRES_CORTOS[mejor[0]]}. A trabajar: {NOMBRES_CORTOS[peor[0]]}."
    return texto


def resumen_semanal(data: dict) -> str:
    hoy = datetime.now(TIMEZONE).date()
    ini = (hoy - timedelta(days=6)).strftime("%Y-%m-%d")
    return resumen_periodo(data, "📊 RETROALIMENTACIÓN SEMANAL", ini, hoy.strftime("%Y-%m-%d"), 7)


def resumen_mensual(data: dict, año: int, mes: int) -> str:
    import calendar as _cal
    dias_mes = _cal.monthrange(año, mes)[1]
    ini = f"{año:04d}-{mes:02d}-01"
    fin = f"{año:04d}-{mes:02d}-{dias_mes:02d}"
    nombre = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
              "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"][mes]
    return resumen_periodo(data, f"📆 RETROALIMENTACIÓN DE {nombre.upper()} {año}", ini, fin, dias_mes)


def resumen_anual(data: dict, año: int) -> str:
    ini = f"{año:04d}-01-01"
    fin = f"{año:04d}-12-31"
    dias = 366 if (año % 4 == 0 and (año % 100 != 0 or año % 400 == 0)) else 365
    return resumen_periodo(data, f"🎉 TU AÑO {año} EN HÁBITOS", ini, fin, dias)


# ---------------------------------------------------------------- teclado
def si_no_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sí", callback_data="hab_si"),
        InlineKeyboardButton("❌ No", callback_data="hab_no"),
    ]])


async def enviar_pregunta(bot, chat_id: int, paso: int):
    _, pregunta = HABITOS[paso]
    await bot.send_message(chat_id, pregunta, reply_markup=si_no_keyboard())


async def iniciar_checkin(bot, chat_id: int):
    data = load_data()
    data["flow"] = {"paso": 0, "respuestas": {}}
    save_data(data)
    await bot.send_message(chat_id, "🌙 Priscila, check-in del día. Responde con honestidad:")
    await enviar_pregunta(bot, chat_id, 0)


# ---------------------------------------------------------------- handlers
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["chat_id"]:
        data["chat_id"] = update.effective_chat.id
        save_data(data)
    await update.message.reply_text(
        "🐺 ¡Hola Priscila! Bienvenida a tu registro diario.\n\n"
        "Cada noche a las 10:00pm te haré 4 preguntas:\n\n"
        "💧 ¿Tomé al menos 2 litros de agua?\n"
        "🙏 ¿Tuve una oración profunda con Jehová?\n"
        "📖 ¿Leí al menos 10 minutos?\n"
        "💪 ¿Hice al menos 30 minutos de ejercicio?\n\n"
        "Comandos:\n"
        "/hoy — contestar ahora mismo\n"
        "/resumen — tus últimos 7 días y rachas"
    )


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await iniciar_checkin(context.bot, update.effective_chat.id)


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["habitos"]:
        await update.message.reply_text("Aún no tienes registros. Usa /hoy para empezar.")
        return
    cutoff = (datetime.now(TIMEZONE).date() - timedelta(days=6)).strftime("%Y-%m-%d")
    ultimos = [h for h in data["habitos"] if h["fecha"] >= cutoff]
    por_fecha = {h["fecha"]: h["respuestas"] for h in ultimos}
    dias = [(datetime.now(TIMEZONE).date() - timedelta(days=i)) for i in range(6, -1, -1)]

    texto = "📊 Últimos 7 días\n\n"
    for clave, pregunta in HABITOS:
        emoji = pregunta.split()[0]
        fila = ""
        cumplidos = 0
        for d in dias:
            r = por_fecha.get(d.strftime("%Y-%m-%d"))
            if r is None:
                fila += "▫️"
            elif r.get(clave):
                fila += "✅"
                cumplidos += 1
            else:
                fila += "❌"
        texto += f"{emoji} {fila}  {cumplidos}/7\n"
    rachas = rachas_text(data)
    if rachas:
        texto += f"\n🔥 Rachas activas:\n{rachas}"
    texto += f"\n\nDías registrados en total: {len(data['habitos'])}"
    await update.message.reply_text(texto)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data not in ("hab_si", "hab_no"):
        return
    data = load_data()
    flow = data.get("flow")
    if not flow:
        await query.answer("No hay check-in activo. Usa /hoy.")
        return
    paso = flow["paso"]
    respuestas = flow["respuestas"]
    clave, pregunta = HABITOS[paso]
    ok = query.data == "hab_si"
    respuestas[clave] = ok
    await query.message.edit_text(f"{pregunta}\n→ {'Sí ✅' if ok else 'No ❌'}")

    siguiente = paso + 1
    if siguiente < len(HABITOS):
        data["flow"] = {"paso": siguiente, "respuestas": respuestas}
        save_data(data)
        await enviar_pregunta(context.bot, query.message.chat_id, siguiente)
    else:
        registrar_dia(data, respuestas)
        cumplidos = sum(1 for v in respuestas.values() if v)
        total = len(HABITOS)
        emoji = "🔥" if cumplidos == total else "💪" if cumplidos >= 2 else "😤"
        txt = f"✅ Día guardado: {cumplidos}/{total} {emoji}"
        rachas = rachas_text(load_data())
        if rachas:
            txt += f"\n\n🔥 Rachas:\n{rachas}"
        await context.bot.send_message(query.message.chat_id, txt)


async def cmd_semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(resumen_semanal(load_data()))


async def cmd_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TIMEZONE)
    await update.message.reply_text(resumen_mensual(load_data(), now.year, now.month))


async def cmd_anual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TIMEZONE)
    await update.message.reply_text(resumen_anual(load_data(), now.year))


async def job_checkin(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    chat_id = data.get("chat_id")
    if not chat_id:
        logger.info("Sin chat_id todavía (nadie ha hecho /start)")
        return
    await iniciar_checkin(context.bot, chat_id)


async def job_resumen_semanal(context: ContextTypes.DEFAULT_TYPE):
    """Domingos 10:30pm — retroalimentación de la semana."""
    data = load_data()
    chat_id = data.get("chat_id")
    if not chat_id:
        return
    await context.bot.send_message(chat_id, resumen_semanal(data))


async def job_resumen_mensual(context: ContextTypes.DEFAULT_TYPE):
    """Día 1 de cada mes 9am — retroalimentación del mes anterior."""
    now = datetime.now(TIMEZONE)
    if now.day != 1:
        return
    data = load_data()
    chat_id = data.get("chat_id")
    if not chat_id:
        return
    año, mes = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    await context.bot.send_message(chat_id, resumen_mensual(data, año, mes))


async def job_resumen_anual(context: ContextTypes.DEFAULT_TYPE):
    """1 de enero 10am — retroalimentación del año anterior."""
    now = datetime.now(TIMEZONE)
    if now.month != 1 or now.day != 1:
        return
    data = load_data()
    chat_id = data.get("chat_id")
    if not chat_id:
        return
    await context.bot.send_message(chat_id, resumen_anual(data, now.year - 1))


async def error_handler(update, context):
    logger.error(f"Error no manejado: {context.error}")


# ---------------------------------------------------------------- main
def main():
    # Python 3.12+ ya no crea event loop automático en el hilo principal
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("hoy",     cmd_hoy))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("semana",  cmd_semana))
    app.add_handler(CommandHandler("mes",     cmd_mes))
    app.add_handler(CommandHandler("anual",   cmd_anual))
    app.add_handler(CallbackQueryHandler(button_callback))

    jq = app.job_queue
    jq.run_daily(job_checkin,         time=dt_time(22, 0,  tzinfo=TIMEZONE), name="checkin")
    jq.run_daily(job_resumen_semanal, time=dt_time(22, 30, tzinfo=TIMEZONE), days=(6,), name="resumen_semanal")
    jq.run_daily(job_resumen_mensual, time=dt_time(9,  0,  tzinfo=TIMEZONE), name="resumen_mensual")
    jq.run_daily(job_resumen_anual,   time=dt_time(10, 0,  tzinfo=TIMEZONE), name="resumen_anual")

    logger.info("Bot Manada iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
