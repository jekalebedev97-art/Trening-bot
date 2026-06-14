import os
import re
import logging
import base64
from datetime import date
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from groq import Groq
from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAIN_MENU, WORKOUT_ACTIVE, CHAT = range(3)
PROFILE_FILE = "athlete_profile.md"

DEFAULT_PROFILE = """# Профиль атлета

## Цели
(не указаны)

## Физические данные
(не указаны)

## Травмы и ограничения
(не указаны)

## Анализы и здоровье
(не указаны)

## БЖУ и питание
(не указаны)

## Предпочтения в тренировках
(не указаны)

## Реакция на нагрузку и восстановление
(не указана)

## Дополнительные заметки
(не указаны)
"""

def load_profile() -> str:
    if not os.path.exists(PROFILE_FILE):
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            f.write(DEFAULT_PROFILE)
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        return f.read()

def save_profile(content: str):
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def get_client():
    return Groq(api_key=os.environ["GROQ_API_KEY"])

def build_system(profile: str, extra_context: str = "") -> str:
    return f"""Ты персональный тренер и нутрициолог. Общаешься в Telegram.

# Профиль атлета
{profile}

# Дополнительный контекст
{extra_context if extra_context else "—"}

# Работа с профилем
Когда пользователь сообщает важную информацию — анализы, БЖУ, цели, травмы, предпочтения — добавь в конце ответа:

<UPDATE_PROFILE>
## Название раздела
Новое содержимое раздела
</UPDATE_PROFILE>

# Стиль
- Живой, конкретный, как тренер рядом
- Используй данные из профиля в каждом ответе где уместно
- Форматирование Telegram: *жирный*, _курсив_
- Русский язык
- Не давай медицинских диагнозов"""

PROMPT_START_EXERCISE = """Пользователь начинает упражнение.

История тренировок:
{workout_history}

Запрос: {user_message}

Дай развёрнутый план:
1. *Целевые мышцы* — что качаем, синергисты
2. *Техника* — положение тела, хват, траектория, дыхание, на что смотреть, чего избегать
3. *Ощущения* — что должно гореть, что не должно
4. *План на сегодня* — подходы, повторения, вес (с учётом профиля и истории)
5. *Главный совет* перед стартом

В конце: "Готов? Пиши результат: *вес × повторения*, например `80x10`. Добавь как шло."

Если в профиле есть травмы — учти явно."""

PROMPT_AFTER_SET = """Идёт тренировка.

Упражнение: {exercise_name}
Исходный план: {original_plan}
Подходы: {sets_done}
Новый результат: {new_set}
Комментарий: {user_comment}
Осталось подходов: {sets_remaining}

Ответь:
1. *Оценка подхода* — сравни с планом, конкретные цифры
2. *Скорректированный план* на оставшиеся подходы + почему
3. *Техническая подсказка* для следующего подхода

Если подходы закончились — подведи итог упражнения."""

PROMPT_MEMORY = """Сообщение пользователя:
"{message}"

Это содержит важную информацию об анализах, здоровье, питании, целях, травмах или предпочтениях?

Если ДА — ответь ТОЛЬКО блоком:
<UPDATE_PROFILE>
## Нужный раздел
Обновлённое содержимое
</UPDATE_PROFILE>

Если нет — ответь: NO_UPDATE

Текущий профиль:
{profile}"""

def main_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🏋️ Начать тренировку"), KeyboardButton("💬 Спросить тренера")],
        [KeyboardButton("📊 Мой прогресс"), KeyboardButton("📋 История")],
        [KeyboardButton("👤 Мой профиль")],
    ], resize_keyboard=True)

def workout_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➡️ Следующее упражнение"), KeyboardButton("✅ Завершить тренировку")],
    ], resize_keyboard=True)

def chat_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("◀️ Главное меню")]], resize_keyboard=True)

def today():
    return date.today().isoformat()

def fmt(d):
    try:
        from datetime import datetime
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y")
    except:
        return d

def build_workout_context(db, user_id):
    prog = db.get_progression_analysis(user_id)
    if not prog:
        return "Первая тренировка — данных пока нет."
    ctx = "История упражнений:\n"
    for ex, sessions in list(prog.items())[:12]:
        last = sessions[-1]
        ctx += f"  {ex}: {fmt(last['date'])} — {last['sets']}×{last['reps']} @ {last['weight']}кг"
        if last.get('note'):
            ctx += f" [{last['note']}]"
        ctx += "\n"
    return ctx

def call_groq(system: str, user_text: str, history=None) -> str:
    client = get_client()
    messages = [{"role": "system", "content": system}]
    if history:
        for h in history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_text})

    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=1500,
        temperature=0.7
    )
    return resp.choices[0].message.content

def call_groq_fast(system: str, user_text: str) -> str:
    client = get_client()
    resp = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text}
        ],
        max_tokens=500,
        temperature=0.3
    )
    return resp.choices[0].message.content

def extract_and_apply_profile_update(reply: str) -> tuple[str, bool]:
    pattern = r'<UPDATE_PROFILE>(.*?)</UPDATE_PROFILE>'
    match = re.search(pattern, reply, re.DOTALL)
    if not match:
        return reply, False

    update_text = match.group(1).strip()
    clean_reply = re.sub(pattern, '', reply, flags=re.DOTALL).strip()

    try:
        profile = load_profile()
        section_match = re.match(r'##\s+(.+)', update_text)
        if section_match:
            section_title = section_match.group(1).strip()
            section_pattern = rf'(##\s+{re.escape(section_title)}\n)(.*?)(?=\n##\s+|\Z)'
            new_section = f'## {section_title}\n{update_text[len(section_match.group(0)):].strip()}\n'
            if re.search(section_pattern, profile, re.DOTALL):
                updated = re.sub(section_pattern, new_section, profile, flags=re.DOTALL)
            else:
                updated = profile.rstrip() + f'\n\n{new_section}'
            save_profile(updated)
            return clean_reply, True
    except Exception as e:
        logger.error(f"Profile update error: {e}")

    return clean_reply, False

def maybe_update_profile(message: str) -> bool:
    keywords = ['анализ', 'кровь', 'гормон', 'витамин', 'бжу', 'белок', 'жир',
                'углевод', 'калори', 'травм', 'болит', 'боль', 'цель', 'хочу достичь',
                'вешу', 'рост', 'возраст', 'лет', 'сплю', 'тестостерон', 'инсулин',
                'холестерин', 'давление', 'пульс', 'запомни', 'вегетар', 'не ем',
                'аллерги', 'непереносимость']
    if not any(kw in message.lower() for kw in keywords):
        return False

    profile = load_profile()
    prompt = PROMPT_MEMORY.format(message=message, profile=profile)
    result = call_groq_fast("Ты помощник который извлекает важную информацию.", prompt)

    if "NO_UPDATE" in result or "<UPDATE_PROFILE>" not in result:
        return False

    _, updated = extract_and_apply_profile_update(result)
    return updated

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db: Database = ctx.bot_data["db"]
    u = update.effective_user
    db.ensure_user(u.id, u.first_name)
    ctx.user_data.clear()
    load_profile()

    await update.message.reply_text(
        f"Привет, {u.first_name}! 💪\n\n"
        "Я твой персональный тренер. Запоминаю всё — "
        "тренировки, анализы, БЖУ, ощущения, цели.\n\n"
        "Можешь сразу написать о себе или начинай тренировку.",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )
    return MAIN_MENU

async def handle_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    db: Database = ctx.bot_data["db"]

    if text == "🏋️ Начать тренировку":
        ctx.user_data["workout"] = {"date": today(), "current": None, "chat_history": []}
        await update.message.reply_text(
            "Скинь фото упражнения или напиши название.",
            reply_markup=workout_kb()
        )
        return WORKOUT_ACTIVE

    elif text == "💬 Спросить тренера":
        await update.message.reply_text(
            "Пиши — отвечу на любой вопрос. Можешь скинуть анализы, БЖУ, рацион — запомню.",
            reply_markup=chat_kb()
        )
        return CHAT

    elif text == "📊 Мой прогресс":
        await show_progress(update, ctx)
    elif text == "📋 История":
        await show_history(update, ctx)
    elif text == "👤 Мой профиль":
        await show_profile(update)

    return MAIN_MENU

async def handle_workout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db: Database = ctx.bot_data["db"]
    user_id = update.effective_user.id
    text = update.message.text or ""
    workout = ctx.user_data.get("workout", {})

    if text == "✅ Завершить тренировку":
        await finish_workout(update, ctx, db, user_id)
        return MAIN_MENU

    if text == "➡️ Следующее упражнение":
        workout["current"] = None
        await update.message.reply_text(
            "Следующее упражнение — напиши название:",
            reply_markup=workout_kb()
        )
        return WORKOUT_ACTIVE

    current = workout.get("current")

    # Фото — Groq не поддерживает изображения, просим написать название
    if update.message.photo:
        await update.message.reply_text(
            "Groq не поддерживает фото. Напиши название упражнения текстом.",
            reply_markup=workout_kb()
        )
        return WORKOUT_ACTIVE

    if not current:
        await update.message.chat.send_action("typing")
        profile = load_profile()
        wo_ctx = build_workout_context(db, user_id)
        system = build_system(profile, wo_ctx)
        prompt = PROMPT_START_EXERCISE.format(workout_history=wo_ctx, user_message=text)
        reply = call_groq(system, prompt)
        clean_reply, _ = extract_and_apply_profile_update(reply)

        workout["current"] = {
            "name": text[:60],
            "original_plan": clean_reply,
            "sets_done": [],
            "sets_remaining": 3,
        }
        workout["chat_history"].append({"role": "assistant", "content": clean_reply})
        await update.message.reply_text(clean_reply, parse_mode="Markdown", reply_markup=workout_kb())
        return WORKOUT_ACTIVE

    set_match = re.search(r'(\d+[\.,]?\d*)\s*[xXхХ×]\s*(\d+)', text)
    if set_match:
        await update.message.chat.send_action("typing")
        weight = set_match.group(1).replace(",", ".")
        reps = set_match.group(2)
        set_result = f"{weight}кг × {reps} повт"
        comment = re.sub(r'(\d+[\.,]?\d*)\s*[xXхХ×]\s*(\d+)', '', text).strip(" -—")

        current["sets_done"].append(f"{set_result}" + (f" — {comment}" if comment else ""))
        current["sets_remaining"] = max(0, current["sets_remaining"] - 1)

        try:
            db.add_workout(user_id, today(), current["name"], 1, int(reps), float(weight), comment)
        except:
            pass

        if comment:
            maybe_update_profile(comment)

        profile = load_profile()
        system = build_system(profile)
        prompt = PROMPT_AFTER_SET.format(
            exercise_name=current["name"],
            original_plan=current["original_plan"][:600],
            sets_done="\n".join(current["sets_done"]),
            new_set=set_result,
            user_comment=comment or "не указан",
            sets_remaining=current["sets_remaining"]
        )
        reply = call_groq(system, prompt)
        clean_reply, _ = extract_and_apply_profile_update(reply)

        workout["chat_history"] += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": clean_reply}
        ]
        await update.message.reply_text(clean_reply, parse_mode="Markdown", reply_markup=workout_kb())
        return WORKOUT_ACTIVE

    # Свободный текст во время тренировки
    await update.message.chat.send_action("typing")
    maybe_update_profile(text)
    profile = load_profile()
    system = build_system(profile, build_workout_context(db, user_id))
    history = workout.get("chat_history", [])[-10:]
    reply = call_groq(system, text, history=history)
    clean_reply, updated = extract_and_apply_profile_update(reply)
    workout["chat_history"] += [
        {"role": "user", "content": text},
        {"role": "assistant", "content": clean_reply}
    ]
    suffix = "\n\n_📝 Обновил твой профиль_" if updated else ""
    await update.message.reply_text(clean_reply + suffix, parse_mode="Markdown", reply_markup=workout_kb())
    return WORKOUT_ACTIVE

async def handle_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    db: Database = ctx.bot_data["db"]
    user_id = update.effective_user.id

    if text == "◀️ Главное меню":
        await update.message.reply_text("Главное меню:", reply_markup=main_kb())
        return MAIN_MENU

    await update.message.chat.send_action("typing")
    maybe_update_profile(text)

    profile = load_profile()
    wo_ctx = build_workout_context(db, user_id)
    system = build_system(profile, wo_ctx)
    history = ctx.user_data.get("chat_history", [])[-16:]

    reply = call_groq(system, text, history=history)
    clean_reply, updated = extract_and_apply_profile_update(reply)

    ctx.user_data.setdefault("chat_history", [])
    ctx.user_data["chat_history"] += [
        {"role": "user", "content": text},
        {"role": "assistant", "content": clean_reply}
    ]

    suffix = "\n\n_📝 Обновил твой профиль_" if updated else ""
    await update.message.reply_text(clean_reply + suffix, parse_mode="Markdown", reply_markup=chat_kb())
    return CHAT

async def show_profile(update: Update):
    profile = load_profile()
    if len(profile) > 3500:
        profile = profile[:3500] + "\n...(обрезано)"
    await update.message.reply_text(
        f"👤 *Твой профиль атлета:*\n\n{profile}",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

async def show_progress(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db: Database = ctx.bot_data["db"]
    user_id = update.effective_user.id
    weights = db.get_weights(user_id, 5)
    prog = db.get_progression_analysis(user_id)
    count = db.get_workouts_count(user_id)

    text = "📊 *Прогресс*\n\n"
    if weights:
        text += "*Вес тела:*\n"
        for w in weights:
            text += f"  {fmt(w['date'])}: {w['value']} кг\n"
        if len(weights) >= 2:
            diff = weights[0]['value'] - weights[-1]['value']
            text += f"  {'📉' if diff < 0 else '📈'} {diff:+.1f} кг\n"
        text += "\n"
    text += f"*Тренировок:* {count}\n\n"
    if prog:
        text += "*Рабочие веса:*\n"
        for ex, sessions in list(prog.items())[:8]:
            last = sessions[-1]
            first = sessions[0]
            diff = last['weight'] - first['weight']
            arrow = f" _(+{diff}кг)_" if diff > 0 else ""
            text += f"  {ex}: {last['weight']}кг{arrow}\n"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_kb())

async def show_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db: Database = ctx.bot_data["db"]
    user_id = update.effective_user.id
    workouts = db.get_workouts(user_id, 40)
    if not workouts:
        await update.message.reply_text("Тренировок пока нет 💪", reply_markup=main_kb())
        return

    by_date = {}
    for w in workouts:
        by_date.setdefault(w['date'], []).append(w)

    text = "📋 *Последние тренировки:*\n"
    for d in sorted(by_date.keys(), reverse=True)[:4]:
        text += f"\n*{fmt(d)}*\n"
        for e in by_date[d]:
            note = f" _{e['note']}_" if e.get('note') else ""
            text += f"  · {e['exercise']}: {e['sets']}×{e['reps']} @ {e['weight']}кг{note}\n"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_kb())

async def finish_workout(update, ctx, db, user_id):
    workouts = db.get_workouts(user_id, 20)
    today_exs = [e for e in workouts if e["date"] == today()]

    if today_exs:
        summary = f"Тренировка завершена ({fmt(today())}):\n"
        by_ex = {}
        for e in today_exs:
            by_ex.setdefault(e["exercise"], []).append(e)
        for ex, sets in by_ex.items():
            summary += f"- {ex}: {len(sets)} подх, последний {sets[-1]['weight']}кг×{sets[-1]['reps']}\n"
        summary += "\nДай краткий итог и одну главную рекомендацию на следующую тренировку."

        await update.message.chat.send_action("typing")
        profile = load_profile()
        system = build_system(profile)
        reply = call_groq(system, summary)
        clean_reply, _ = extract_and_apply_profile_update(reply)

        await update.message.reply_text(
            f"✅ *Тренировка сохранена!*\n\n{clean_reply}",
            parse_mode="Markdown", reply_markup=main_kb()
        )
    else:
        await update.message.reply_text("Тренировка завершена!", reply_markup=main_kb())

    ctx.user_data.clear()

def main():
    token = os.environ["TELEGRAM_TOKEN"]
    db = Database("fitness.db")

    app = Application.builder().token(token).build()
    app.bot_data["db"] = db

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main)],
            WORKOUT_ACTIVE: [
                MessageHandler(filters.PHOTO, handle_workout),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workout),
            ],
            CHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("menu", start)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
