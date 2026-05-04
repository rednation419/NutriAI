import os
import logging
import json
from datetime import date, datetime, time as dtime, timedelta
from io import BytesIO
from PIL import Image
import pytz

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler
)
import google.generativeai as genai
from supabase import create_client

# === ЛОГИ ===
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# === ENV ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# === ИНИТ ===
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-flash-latest')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# === СОСТОЯНИЯ РЕГИСТРАЦИИ ===
NAME, AGE, SEX, HEIGHT, WEIGHT, TARGET_WEIGHT, ACTIVITY, TIMEZONE = range(8)

# === КНОПКИ ===
BTN_STATS = "📊 Статистика"
BTN_PROFILE = "👤 Профиль"
BTN_ASK = "💬 Спросить диетолога"
BTN_FAVORITES = "🔁 Частые блюда"
BTN_LABEL = "🏷️ Анализ этикетки"
BTN_MENU = "🍱 Придумать меню"
BTN_WORKOUT = "🏃 Тренировка"
BTN_HISTORY = "📈 История"
BTN_SETTINGS = "⚙️ Настройки"
BTN_HELP = "ℹ️ Помощь"
BTN_DONATE = "⭐ Поблагодарить автора"
BTN_RESET = "🔄 Сбросить профиль"
BTN_EDIT = "✏️ Изменить данные"
BTN_BACK = "⬅️ В меню"

# === ЧАСОВЫЕ ПОЯСА ===
TIMEZONES = {
    "🇺🇦 Киев": "Europe/Kyiv", "🇷🇺 Москва": "Europe/Moscow",
    "🇧🇾 Минск": "Europe/Minsk", "🇰🇿 Алматы": "Asia/Almaty",
    "🇺🇿 Ташкент": "Asia/Tashkent", "🇩🇪 Берлин": "Europe/Berlin",
    "🇬🇧 Лондон": "Europe/London", "🇺🇸 Нью-Йорк": "America/New_York",
    "🇺🇸 Лос-Анджелес": "America/Los_Angeles", "🇦🇪 Дубай": "Asia/Dubai",
    "🇹🇭 Бангкок": "Asia/Bangkok", "🇯🇵 Токио": "Asia/Tokyo",
}
TIMEZONE_LABELS = {v: k for k, v in TIMEZONES.items()}

# === ТРЕНИРОВКИ ===
WORKOUT_TYPES = {
    "🚶 Ходьба": 4, "🏃 Бег": 11, "🚴 Велосипед": 8,
    "🏊 Плавание": 9, "💪 Силовая": 7, "🧘 Йога/растяжка": 3,
    "🥊 Бокс/единоборства": 12, "⚽ Командный спорт": 9,
    "🏋️ Кроссфит/HIIT": 13, "🤸 Танцы": 6,
}

WORKOUT_INTENSITY = {
    "easy": {"label": "🟢 Лёгкая", "factor": 0.75, "desc": "разминка, спокойный темп"},
    "medium": {"label": "🟡 Средняя", "factor": 1.0, "desc": "обычная тренировка, есть пот"},
    "hard": {"label": "🔴 Тяжёлая", "factor": 1.3, "desc": "до отказа, высокий пульс"},
}

# === ДОНАТЫ ===
DONATE_TIERS = [
    {"stars": 50, "label": "⭐ 50 Stars", "emoji": "☕", "msg": "За кофе автору"},
    {"stars": 150, "label": "⭐⭐ 150 Stars", "emoji": "🍕", "msg": "На пиццу"},
    {"stars": 500, "label": "⭐⭐⭐ 500 Stars", "emoji": "🎉", "msg": "Большая поддержка"},
    {"stars": 1000, "label": "⭐⭐⭐⭐ 1000 Stars", "emoji": "💎", "msg": "Огромный респект"},
]

# === ПОЛЯ РЕДАКТИРОВАНИЯ ===
EDIT_FIELDS = {
    "edit_name": {"label": "🏷️ Имя", "prompt": "Введи новое имя:", "type": "text"},
    "edit_age": {"label": "🎂 Возраст", "prompt": "Введи новый возраст (10-100):", "type": "int", "min": 10, "max": 100},
    "edit_sex": {"label": "⚧ Пол", "prompt": "Выбери пол:", "type": "choice", "options": ["Мужской", "Женский"]},
    "edit_height": {"label": "📏 Рост", "prompt": "Введи новый рост в см (100-250):", "type": "int", "min": 100, "max": 250},
    "edit_weight": {"label": "⚖️ Текущий вес", "prompt": "Введи новый текущий вес в кг (30-300):", "type": "float", "min": 30, "max": 300},
    "edit_target": {"label": "🎯 Желаемый вес", "prompt": "Введи новый желаемый вес в кг (30-300):", "type": "float", "min": 30, "max": 300},
    "edit_activity": {"label": "🏃 Активность", "prompt": "Выбери уровень активности:", "type": "choice",
                      "options": ["Минимальная", "Лёгкая", "Умеренная", "Высокая", "Очень высокая"]},
    "edit_tz": {"label": "🌍 Часовой пояс", "prompt": "Выбери часовой пояс:", "type": "choice",
                "options": list(TIMEZONES.keys())},
}

# === МЕНЮ ===
def main_menu():
    keyboard = [
        [BTN_STATS, BTN_HISTORY],
        [BTN_FAVORITES, BTN_WORKOUT],
        [BTN_LABEL, BTN_MENU],
        [BTN_ASK, BTN_PROFILE],
        [BTN_SETTINGS, BTN_HELP],
        [BTN_DONATE]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def back_menu():
    return ReplyKeyboardMarkup([[BTN_BACK]], resize_keyboard=True, is_persistent=True)

def settings_menu(daily_summary_on):
    toggle = "🔕 Выключить вечерний отчёт" if daily_summary_on else "🔔 Включить вечерний отчёт"
    return ReplyKeyboardMarkup([[BTN_EDIT], [toggle], [BTN_RESET], [BTN_BACK]],
                               resize_keyboard=True, is_persistent=True)

# === УТИЛИТЫ ===
def get_user_today(tz_str):
    try:
        return datetime.now(pytz.timezone(tz_str)).date().isoformat()
    except Exception:
        return date.today().isoformat()

def get_user_now(tz_str):
    try:
        return datetime.now(pytz.timezone(tz_str))
    except Exception:
        return datetime.now()

def calculate_norms(sex, age, height, weight, activity, target_weight):
    bmr = 10*weight + 6.25*height - 5*age + (5 if sex == "Мужской" else -161)
    activity_map = {"Минимальная": 1.2, "Лёгкая": 1.375, "Умеренная": 1.55, "Высокая": 1.725, "Очень высокая": 1.9}
    tdee = bmr * activity_map.get(activity, 1.2)
    if target_weight < weight - 1:
        cal = tdee - 400
    elif target_weight > weight + 1:
        cal = tdee + 300
    else:
        cal = tdee
    cal = round(cal)
    p = round(weight * 1.8)
    f = round(cal * 0.25 / 9)
    c = round((cal - p*4 - f*9) / 4)
    return cal, p, f, c

def make_progress_bar(current, goal, length=10):
    if goal == 0:
        return ""
    pct = min(current/goal, 1.0)
    filled = int(length * pct)
    return f"[{'█'*filled}{'░'*(length-filled)}] {int(pct*100)}%"

def get_user(user_id):
    r = supabase.table("users").select("*").eq("user_id", user_id).execute()
    return r.data[0] if r.data else None

def get_today_meals(user_id, today):
    r = supabase.table("meals").select("*").eq("user_id", user_id).eq("date", today).execute()
    return r.data or []

def get_today_workouts(user_id, today):
    r = supabase.table("workouts").select("*").eq("user_id", user_id).eq("date", today).execute()
    return r.data or []

def daily_calories_burned(user_id, today):
    return sum(w['calories_burned'] for w in get_today_workouts(user_id, today))

# === /start ===
async def start(update, context):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)

    if user:
        if user.get('daily_summary', True):
            schedule_daily_summary(context.application, user)
        await update.message.reply_text(
            f"👋 С возвращением, {user['name']}!\n\n"
            f"📊 Норма: {user['calories_goal']} ккал/день\n\nИспользуй меню внизу 👇",
            reply_markup=main_menu())
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Привет! Я NutriAI — твой умный диетолог.\n\n"
        "Сначала ответь на вопросы для расчёта нормы.\n\nКак тебя зовут?",
        reply_markup=ReplyKeyboardRemove())
    return NAME

# === РЕГИСТРАЦИЯ ===
async def get_name(update, context):
    context.user_data['name'] = update.message.text
    await update.message.reply_text(f"Приятно, {update.message.text}! 😊\n\nСколько тебе лет?")
    return AGE

async def get_age(update, context):
    try:
        age = int(update.message.text)
        if age < 10 or age > 100:
            await update.message.reply_text("Возраст 10-100.")
            return AGE
        context.user_data['age'] = age
        await update.message.reply_text("Пол:",
            reply_markup=ReplyKeyboardMarkup([["Мужской", "Женский"]], one_time_keyboard=True, resize_keyboard=True))
        return SEX
    except ValueError:
        await update.message.reply_text("Введи число.")
        return AGE

async def get_sex(update, context):
    if update.message.text not in ["Мужской", "Женский"]:
        await update.message.reply_text("Выбери из кнопок.",
            reply_markup=ReplyKeyboardMarkup([["Мужской", "Женский"]], one_time_keyboard=True, resize_keyboard=True))
        return SEX
    context.user_data['sex'] = update.message.text
    await update.message.reply_text("Рост в см?", reply_markup=ReplyKeyboardRemove())
    return HEIGHT

async def get_height(update, context):
    try:
        h = int(update.message.text)
        if h < 100 or h > 250:
            await update.message.reply_text("Рост 100-250.")
            return HEIGHT
        context.user_data['height'] = h
        await update.message.reply_text("Текущий вес в кг?")
        return WEIGHT
    except ValueError:
        await update.message.reply_text("Введи число.")
        return HEIGHT

async def get_weight(update, context):
    try:
        w = float(update.message.text.replace(',', '.'))
        if w < 30 or w > 300:
            await update.message.reply_text("Вес 30-300.")
            return WEIGHT
        context.user_data['weight'] = w
        await update.message.reply_text("Желаемый вес в кг?")
        return TARGET_WEIGHT
    except ValueError:
        await update.message.reply_text("Введи число.")
        return WEIGHT

async def get_target_weight(update, context):
    try:
        t = float(update.message.text.replace(',', '.'))
        if t < 30 or t > 300:
            await update.message.reply_text("Вес 30-300.")
            return TARGET_WEIGHT
        context.user_data['target_weight'] = t
        kb = [["Минимальная", "Лёгкая"], ["Умеренная", "Высокая"], ["Очень высокая"]]
        await update.message.reply_text(
            "Активность?\n\n🪑 Минимальная — сидячая\n🚶 Лёгкая — 1-3 тренировки\n"
            "🏃 Умеренная — 3-5\n💪 Высокая — 6-7\n🏋️ Очень высокая — труд+спорт",
            reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
        return ACTIVITY
    except ValueError:
        await update.message.reply_text("Введи число.")
        return TARGET_WEIGHT

async def get_activity(update, context):
    opts = ["Минимальная", "Лёгкая", "Умеренная", "Высокая", "Очень высокая"]
    if update.message.text not in opts:
        kb = [["Минимальная", "Лёгкая"], ["Умеренная", "Высокая"], ["Очень высокая"]]
        await update.message.reply_text("Выбери из кнопок.",
            reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
        return ACTIVITY
    context.user_data['activity'] = update.message.text
    tz_btns = list(TIMEZONES.keys())
    kb = [tz_btns[i:i+2] for i in range(0, len(tz_btns), 2)]
    await update.message.reply_text("🌍 Часовой пояс?",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
    return TIMEZONE

async def get_timezone(update, context):
    sel = update.message.text
    if sel not in TIMEZONES:
        tz_btns = list(TIMEZONES.keys())
        kb = [tz_btns[i:i+2] for i in range(0, len(tz_btns), 2)]
        await update.message.reply_text("Выбери из кнопок.",
            reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
        return TIMEZONE

    context.user_data['timezone'] = TIMEZONES[sel]
    user_id = str(update.effective_user.id)
    d = context.user_data
    cal, p, f, c = calculate_norms(d['sex'], d['age'], d['height'], d['weight'], d['activity'], d['target_weight'])

    user_data = {
        "user_id": user_id, "name": d['name'], "age": d['age'], "sex": d['sex'],
        "height": d['height'], "weight": d['weight'], "target_weight": d['target_weight'],
        "activity": d['activity'], "calories_goal": cal, "protein_goal": p,
        "fat_goal": f, "carbs_goal": c, "timezone": d['timezone'], "daily_summary": True
    }
    supabase.table("users").insert(user_data).execute()
    schedule_daily_summary(context.application, user_data)

    await update.message.reply_text(
        f"✅ Профиль создан, {d['name']}!\n\n"
        f"📊 Норма:\n🔥 {cal} ккал | 🥩 {p}г Б | 🧈 {f}г Ж | 🍞 {c}г У\n\n"
        f"🌙 В 23:59 буду присылать итог дня (можно выключить).\n\nМеню внизу 👇",
        reply_markup=main_menu())
    return ConversationHandler.END

# === АНАЛИЗ ЕДЫ ===
def analyze_food_with_ai(description=None, image=None, clarifications=None):
    prompt = """Ты — опытный диетолог. Оцени КБЖУ блюда БЫСТРО.

🎯 ПРИНЦИП: Делай разумные допущения. НЕ задавай вопросов если погрешность <20%.

📌 ДОПУЩЕНИЯ:
- Хлопья+молоко → 40г+200мл 2.5%
- Жареное → 1ч.л. масла
- Салат → 1ч.л. масла или без
- Каши → варка без масла
- Размер непонятен → стандартная порция 250-350г

❓ ВОПРОСЫ ТОЛЬКО ЕСЛИ:
1. Не идентифицировать блюдо
2. Явно много необычной заправки
3. Видно много жира
4. Нестандартная порция

ФОРМАТ:
Если оценил — JSON:
{"status":"ok","dish":"...","weight_g":350,"calories":580,"protein":28,"fat":22,"carbs":60,"comment":"..."}

Нужно уточнение — JSON:
{"status":"need_info","question":"..."}

Только JSON, без markdown."""

    try:
        full = prompt
        if clarifications:
            full += f"\n\nУТОЧНЕНИЯ: {clarifications}\n\nДай финальную оценку."
        if image:
            response = model.generate_content([full, image, description or "Что на фото?"])
        else:
            response = model.generate_content(f"{full}\n\nОписание: {description}")
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"AI error: {e}")
        return {"status": "error", "message": str(e)}

# === ДИЕТОЛОГ ===
def ask_dietitian_ai(question, user):
    prompt = f"""Ты — сертифицированный диетолог-нутрициолог с 15-летним опытом.

ПОЛЬЗОВАТЕЛЬ: {user['name']}, {user['age']}л, {user['sex']}, {user['height']}см, {user['weight']}кг → цель {user['target_weight']}кг, активность: {user['activity']}
НОРМА: {user['calories_goal']}ккал, Б{user['protein_goal']}/Ж{user['fat_goal']}/У{user['carbs_goal']}

ПРАВИЛА:
- Опирайся на данные пользователя
- Конкретные рекомендации с цифрами и продуктами
- Объясняй ПОЧЕМУ
- При болезнях — к врачу
- Не давай советы по лекарствам/БАДам в лечебных целях
- 150-400 слов, живой язык, без markdown

ВОПРОС: {question}"""
    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        logger.error(f"Dietitian error: {e}")
        return "❌ Ошибка. Попробуй позже."

# === ОБРАБОТКА ФОТО ===
async def handle_photo(update, context):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Сначала /start", reply_markup=ReplyKeyboardRemove())
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    image = Image.open(BytesIO(bytes(file_bytes)))
    caption = update.message.caption or ""

    mode = context.user_data.get('photo_mode', 'food')

    if mode == 'label':
        await update.message.reply_text("🏷️ Анализирую этикетку...")
        result = analyze_label_with_ai(image, user)
        await update.message.reply_text(result, reply_markup=main_menu())
        context.user_data['photo_mode'] = 'food'
        return

    if mode == 'fridge':
        await update.message.reply_text("🍱 Изучаю содержимое холодильника...")
        result = generate_menu_from_fridge(image, user)
        await update.message.reply_text(result, reply_markup=main_menu())
        context.user_data['photo_mode'] = 'food'
        return

    await update.message.reply_text("🔍 Анализирую фото...")
    result = analyze_food_with_ai(description=caption, image=image)
    if result.get('status') == 'need_info':
        context.user_data['awaiting_clarification'] = True
        context.user_data['original_description'] = caption
        context.user_data['original_image'] = image
        context.user_data['clarifications'] = ''
    await process_ai_result(update, context, result, user)

# === ОБРАБОТКА ТЕКСТА ===
async def handle_text(update, context):
    text = update.message.text

    button_handlers = {
        BTN_STATS: stats, BTN_PROFILE: profile, BTN_HELP: help_cmd,
        BTN_SETTINGS: settings_view, BTN_ASK: ask_mode_on,
        BTN_FAVORITES: favorites_view, BTN_LABEL: label_mode_on,
        BTN_MENU: menu_mode_on, BTN_WORKOUT: workout_view,
        BTN_HISTORY: history_view, BTN_RESET: reset_confirm,
        BTN_DONATE: donate_view, BTN_EDIT: edit_view,
    }
    if text in button_handlers:
        await button_handlers[text](update, context)
        return

    if text == BTN_BACK:
        context.user_data['ask_mode'] = False
        context.user_data['photo_mode'] = 'food'
        context.user_data['awaiting_menu_text'] = False
        context.user_data['adding_favorite'] = False
        context.user_data['editing_field'] = None
        await update.message.reply_text("Главное меню:", reply_markup=main_menu())
        return
    if text == "✅ Да, сбросить":
        await reset_do(update, context)
        return
    if text == "❌ Отмена":
        await update.message.reply_text("Отмена.", reply_markup=main_menu())
        return
    if text == "🔕 Выключить вечерний отчёт":
        await toggle_summary(update, context, False)
        return
    if text == "🔔 Включить вечерний отчёт":
        await toggle_summary(update, context, True)
        return
    if text == "➕ Добавить частое блюдо":
        await add_favorite_start(update, context)
        return
    if text == "🍳 Без продуктов — сгенерируй меню":
        await generate_menu_no_fridge(update, context)
        return

    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Сначала /start", reply_markup=ReplyKeyboardRemove())
        return

    # === ОБРАБОТКА РЕДАКТИРОВАНИЯ ПОЛЯ ===
    if context.user_data.get('editing_field'):
        await edit_process(update, context, user)
        return

    if context.user_data.get('adding_favorite'):
        await add_favorite_process(update, context, user)
        return

    if context.user_data.get('awaiting_menu_text'):
        await update.message.reply_text("🍱 Генерирую меню...")
        result = generate_menu_from_text(text, user)
        await update.message.reply_text(result, reply_markup=main_menu())
        context.user_data['awaiting_menu_text'] = False
        return

    if context.user_data.get('ask_mode'):
        await update.message.reply_text("💭 Думаю...")
        answer = ask_dietitian_ai(text, user)
        await update.message.reply_text(
            f"👨‍⚕️ {answer}\n\n━━━━━━━━━━━━━━━\n💬 Можешь задать ещё вопрос или нажми «{BTN_BACK}»",
            reply_markup=back_menu())
        return

    if context.user_data.get('awaiting_clarification'):
        original = context.user_data.get('original_description', '')
        original_image = context.user_data.get('original_image', None)
        prev = context.user_data.get('clarifications', '')
        new_clar = prev + f"\n- {text}" if prev else f"- {text}"
        await update.message.reply_text("🔍 Учитываю уточнения...")
        result = analyze_food_with_ai(description=original, image=original_image, clarifications=new_clar)
        if result.get('status') == 'need_info':
            context.user_data['clarifications'] = new_clar
        else:
            context.user_data['awaiting_clarification'] = False
            context.user_data['original_description'] = ''
            context.user_data['original_image'] = None
            context.user_data['clarifications'] = ''
    else:
        await update.message.reply_text("🔍 Анализирую...")
        result = analyze_food_with_ai(description=text)
        if result.get('status') == 'need_info':
            context.user_data['awaiting_clarification'] = True
            context.user_data['original_description'] = text
            context.user_data['original_image'] = None
            context.user_data['clarifications'] = ''

    await process_ai_result(update, context, result, user)

# === РЕЗУЛЬТАТ АНАЛИЗА ===
async def process_ai_result(update, context, result, user):
    if result.get('status') == 'error':
        await update.message.reply_text("❌ Ошибка. Попробуй ещё раз.", reply_markup=main_menu())
        return
    if result.get('status') == 'need_info':
        await update.message.reply_text(f"❓ {result['question']}", reply_markup=main_menu())
        return
    if result.get('status') == 'ok':
        user_id = str(update.effective_user.id)
        tz_str = user.get('timezone', 'Europe/Kyiv')
        today = get_user_today(tz_str)

        supabase.table("meals").insert({
            "user_id": user_id, "date": today,
            "description": result.get('dish', 'Блюдо'),
            "calories": result.get('calories', 0), "protein": result.get('protein', 0),
            "fat": result.get('fat', 0), "carbs": result.get('carbs', 0)
        }).execute()

        meals = get_today_meals(user_id, today)
        burned = daily_calories_burned(user_id, today)
        total_cal = sum(m['calories'] for m in meals)
        total_p = sum(m['protein'] for m in meals)
        total_f = sum(m['fat'] for m in meals)
        total_c = sum(m['carbs'] for m in meals)
        net_cal = total_cal - burned
        cal_goal = user['calories_goal']

        bar = make_progress_bar(net_cal, cal_goal)
        burned_str = f"\n🏃 Сожжено тренировками: -{burned} ккал" if burned > 0 else ""

        keyboard = [[InlineKeyboardButton("⭐ Сохранить как частое", callback_data=f"savefav:{result.get('dish', 'Блюдо')[:50]}")]]
        await update.message.reply_text(
            f"✅ {result.get('dish', 'Блюдо')} (≈{result.get('weight_g', '?')}г)\n"
            f"🔥 {result['calories']} ккал | 🥩 {result['protein']}г | 🧈 {result['fat']}г | 🍞 {result['carbs']}г\n"
            f"💬 {result.get('comment', '')}\n\n"
            f"━━━━━━━━━━━━━━━\n📊 ЗА СЕГОДНЯ:\n{bar}\n\n"
            f"🔥 {total_cal} / {cal_goal} ккал{burned_str}\n"
            f"🥩 Б: {total_p:.0f}/{user['protein_goal']} | 🧈 Ж: {total_f:.0f}/{user['fat_goal']} | 🍞 У: {total_c:.0f}/{user['carbs_goal']}",
            reply_markup=InlineKeyboardMarkup(keyboard))

        context.user_data['last_meal'] = {
            'name': result.get('dish', 'Блюдо'),
            'description': result.get('dish', 'Блюдо'),
            'calories': result.get('calories', 0),
            'protein': result.get('protein', 0),
            'fat': result.get('fat', 0),
            'carbs': result.get('carbs', 0),
            'weight_g': result.get('weight_g', 0)
        }

# === СТАТИСТИКА ===
async def stats(update, context):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Сначала /start", reply_markup=ReplyKeyboardRemove())
        return

    tz_str = user.get('timezone', 'Europe/Kyiv')
    today = get_user_today(tz_str)
    now = get_user_now(tz_str)
    months = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
    weekdays = ['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье']
    date_str = f"{now.day} {months[now.month-1]} ({weekdays[now.weekday()]})"
    time_str = now.strftime("%H:%M")

    meals = get_today_meals(user_id, today)
    workouts = get_today_workouts(user_id, today)
    burned = sum(w['calories_burned'] for w in workouts)

    if not meals and not workouts:
        await update.message.reply_text(
            f"📊 СТАТИСТИКА\n📅 {date_str}\n🕐 {time_str}\n\nСегодня пусто.\n\n🎯 Норма: {user['calories_goal']} ккал",
            reply_markup=main_menu())
        return

    total_cal = sum(m['calories'] for m in meals)
    total_p = sum(m['protein'] for m in meals)
    total_f = sum(m['fat'] for m in meals)
    total_c = sum(m['carbs'] for m in meals)
    net = total_cal - burned
    bar = make_progress_bar(net, user['calories_goal'])

    meals_list = "\n".join([f"• {m['description']} — {m['calories']} ккал" for m in meals]) or "—"
    workouts_list = "\n".join([f"• {w['type']} {w['duration_min']}мин — {w['calories_burned']} ккал" for w in workouts]) or ""

    text = f"📊 СТАТИСТИКА\n📅 {date_str}\n🕐 {time_str}\n\n{bar}\n\n"
    text += f"🔥 Съедено: {total_cal} / {user['calories_goal']}\n"
    if burned:
        text += f"🏃 Сожжено: -{burned} (нетто: {net})\n"
    text += f"🥩 Б: {total_p:.0f}/{user['protein_goal']} | 🧈 Ж: {total_f:.0f}/{user['fat_goal']} | 🍞 У: {total_c:.0f}/{user['carbs_goal']}\n\n"
    text += f"🍽️ Приёмы пищи ({len(meals)}):\n{meals_list}"
    if workouts_list:
        text += f"\n\n🏃 Тренировки:\n{workouts_list}"

    await update.message.reply_text(text, reply_markup=main_menu())

# === ИСТОРИЯ ===
async def history_view(update, context):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Сначала /start", reply_markup=ReplyKeyboardRemove())
        return

    keyboard = [[InlineKeyboardButton("📅 Неделя", callback_data="hist:7"),
                 InlineKeyboardButton("📆 Месяц", callback_data="hist:30")]]
    await update.message.reply_text("📈 За какой период?",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def history_callback(update, context):
    query = update.callback_query
    await query.answer()
    days = int(query.data.split(":")[1])

    user_id = str(query.from_user.id)
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("Сначала /start")
        return

    tz_str = user.get('timezone', 'Europe/Kyiv')
    today = datetime.now(pytz.timezone(tz_str)).date()
    start_date = (today - timedelta(days=days-1)).isoformat()
    today_str = today.isoformat()

    meals = supabase.table("meals").select("*").eq("user_id", user_id).gte("date", start_date).lte("date", today_str).execute().data or []
    workouts = supabase.table("workouts").select("*").eq("user_id", user_id).gte("date", start_date).lte("date", today_str).execute().data or []

    if not meals:
        await query.edit_message_text(f"📈 За последние {days} дней нет данных.")
        return

    by_day = {}
    for m in meals:
        d = m['date']
        if d not in by_day:
            by_day[d] = {'cal': 0, 'p': 0, 'f': 0, 'c': 0, 'burned': 0}
        by_day[d]['cal'] += m['calories']
        by_day[d]['p'] += m['protein']
        by_day[d]['f'] += m['fat']
        by_day[d]['c'] += m['carbs']
    for w in workouts:
        d = w['date']
        if d not in by_day:
            by_day[d] = {'cal': 0, 'p': 0, 'f': 0, 'c': 0, 'burned': 0}
        by_day[d]['burned'] += w['calories_burned']

    days_count = len(by_day)
    avg_cal = sum(d['cal'] for d in by_day.values()) / days_count
    avg_p = sum(d['p'] for d in by_day.values()) / days_count
    avg_f = sum(d['f'] for d in by_day.values()) / days_count
    avg_c = sum(d['c'] for d in by_day.values()) / days_count
    avg_burned = sum(d['burned'] for d in by_day.values()) / days_count

    in_norm = sum(1 for d in by_day.values() if abs(d['cal'] - user['calories_goal']) / user['calories_goal'] < 0.15)
    norm_pct = round(in_norm / days_count * 100)

    dish_count = {}
    for m in meals:
        dish_count[m['description']] = dish_count.get(m['description'], 0) + 1
    top_dishes = sorted(dish_count.items(), key=lambda x: -x[1])[:5]
    top_str = "\n".join([f"• {d} ({c}р.)" for d, c in top_dishes])

    period = "недели" if days == 7 else "месяца"
    text = (f"📈 ИСТОРИЯ ЗА {days} дн.\n\n"
            f"📊 Дней с записями: {days_count}/{days}\n"
            f"🎯 В норме калорий: {in_norm} дней ({norm_pct}%)\n\n"
            f"📐 СРЕДНИЕ ЗА ДЕНЬ:\n"
            f"🔥 {avg_cal:.0f} ккал (норма {user['calories_goal']})\n"
            f"🥩 Б: {avg_p:.0f} | 🧈 Ж: {avg_f:.0f} | 🍞 У: {avg_c:.0f}\n")
    if avg_burned > 10:
        text += f"🏃 Сожжено тренировками: {avg_burned:.0f} ккал/день\n"
    text += f"\n🏆 ТОП блюд {period}:\n{top_str}"

    await query.edit_message_text(text)

# === ЧАСТЫЕ БЛЮДА ===
async def favorites_view(update, context):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Сначала /start", reply_markup=ReplyKeyboardRemove())
        return

    favs = supabase.table("favorite_meals").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data or []

    if not favs:
        keyboard = [["➕ Добавить частое блюдо"], [BTN_BACK]]
        await update.message.reply_text(
            "🔁 ЧАСТЫЕ БЛЮДА\n\nЗдесь ещё пусто.\n\n"
            "Сюда сохраняются регулярные блюда. Чтобы каждый раз не вводить заново.\n\n"
            "💡 После обычного добавления блюда — нажми «⭐ Сохранить как частое».",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True))
        return

    text = "🔁 ТВОИ ЧАСТЫЕ БЛЮДА:\n\nНажми чтобы добавить в дневник."
    keyboard = []
    for f in favs[:20]:
        btn_text = f"+ {f['name']} ({f['calories']} ккал)"
        keyboard.append([InlineKeyboardButton(btn_text[:60], callback_data=f"addfav:{f['id']}")])
        keyboard.append([InlineKeyboardButton(f"🗑️ Удалить «{f['name'][:25]}»", callback_data=f"delfav:{f['id']}")])

    bottom = [["➕ Добавить частое блюдо"], [BTN_BACK]]
    await update.message.reply_text(text,
        reply_markup=ReplyKeyboardMarkup(bottom, resize_keyboard=True, is_persistent=True))
    await update.message.reply_text("👇 Список:", reply_markup=InlineKeyboardMarkup(keyboard))

async def add_favorite_start(update, context):
    context.user_data['adding_favorite'] = True
    context.user_data['fav_step'] = 'name'
    await update.message.reply_text(
        "➕ Добавление частого блюда\n\nШаг 1/2: Название (например: «Овсянка с бананом»)",
        reply_markup=ReplyKeyboardMarkup([[BTN_BACK]], resize_keyboard=True))

async def add_favorite_process(update, context, user):
    text = update.message.text
    step = context.user_data.get('fav_step')

    if step == 'name':
        context.user_data['fav_name'] = text
        context.user_data['fav_step'] = 'description'
        await update.message.reply_text(
            f"✓ Название: {text}\n\nШаг 2/2: Состав и порция",
            reply_markup=ReplyKeyboardMarkup([[BTN_BACK]], resize_keyboard=True))
        return

    if step == 'description':
        await update.message.reply_text("🔍 Анализирую состав...")
        result = analyze_food_with_ai(description=text)

        if result.get('status') != 'ok':
            await update.message.reply_text(
                "❌ Не распознал. Опиши подробнее или нажми «⬅️ В меню».",
                reply_markup=ReplyKeyboardMarkup([[BTN_BACK]], resize_keyboard=True))
            return

        user_id = str(update.effective_user.id)
        supabase.table("favorite_meals").insert({
            "user_id": user_id, "name": context.user_data['fav_name'],
            "description": text, "calories": result['calories'],
            "protein": result['protein'], "fat": result['fat'],
            "carbs": result['carbs'], "weight_g": result.get('weight_g', 0)
        }).execute()

        context.user_data['adding_favorite'] = False
        context.user_data['fav_step'] = None

        await update.message.reply_text(
            f"✅ Сохранено!\n\n⭐ {context.user_data['fav_name']}\n"
            f"🔥 {result['calories']} ккал | 🥩 {result['protein']}г | 🧈 {result['fat']}г | 🍞 {result['carbs']}г",
            reply_markup=main_menu())

async def add_fav_callback(update, context):
    query = update.callback_query
    await query.answer()
    fav_id = int(query.data.split(":")[1])

    user_id = str(query.from_user.id)
    user = get_user(user_id)
    if not user:
        return

    fav = supabase.table("favorite_meals").select("*").eq("id", fav_id).execute().data
    if not fav:
        await query.edit_message_text("Блюдо не найдено.")
        return
    fav = fav[0]

    tz_str = user.get('timezone', 'Europe/Kyiv')
    today = get_user_today(tz_str)

    supabase.table("meals").insert({
        "user_id": user_id, "date": today,
        "description": fav['name'], "calories": fav['calories'],
        "protein": fav['protein'], "fat": fav['fat'], "carbs": fav['carbs']
    }).execute()

    meals = get_today_meals(user_id, today)
    total = sum(m['calories'] for m in meals)
    await query.message.reply_text(
        f"✅ Добавил: {fav['name']} ({fav['calories']} ккал)\n\n📊 Сегодня: {total} / {user['calories_goal']} ккал",
        reply_markup=main_menu())

async def del_fav_callback(update, context):
    query = update.callback_query
    await query.answer()
    fav_id = int(query.data.split(":")[1])
    user_id = str(query.from_user.id)
    supabase.table("favorite_meals").delete().eq("id", fav_id).eq("user_id", user_id).execute()
    await query.message.reply_text("🗑️ Удалено", reply_markup=main_menu())

async def save_fav_callback(update, context):
    query = update.callback_query
    user_id = str(query.from_user.id)
    last = context.user_data.get('last_meal')
    if not last:
        await query.answer("Нечего сохранять — отправь блюдо заново", show_alert=True)
        return

    supabase.table("favorite_meals").insert({
        "user_id": user_id, "name": last['name'][:50],
        "description": last.get('description', ''), "calories": last['calories'],
        "protein": last['protein'], "fat": last['fat'], "carbs": last['carbs'],
        "weight_g": last.get('weight_g', 0)
    }).execute()

    await query.answer("⭐ Сохранено в частые!", show_alert=True)
    await query.edit_message_reply_markup(reply_markup=None)

# === АНАЛИЗ ЭТИКЕТКИ ===
def analyze_label_with_ai(image, user):
    prompt = f"""Ты — диетолог-нутрициолог. Проанализируй ЭТИКЕТКУ продукта на фото.

ПОЛЬЗОВАТЕЛЬ: {user['sex']}, {user['age']}л, цель {user['target_weight']}кг (текущий {user['weight']}кг), активность {user['activity']}
НОРМА: {user['calories_goal']}ккал, Б{user['protein_goal']}/Ж{user['fat_goal']}/У{user['carbs_goal']}

ФОРМАТ:

🏷️ ПРОДУКТ
[Название если видно]

📊 СОСТАВ И КБЖУ (на 100г и упаковку)

⚠️ КРАСНЫЕ ФЛАГИ
[Трансжиры, добавленный сахар, искусственные подсластители, E-добавки, плохие масла, избыток натрия]

✅ ПЛЮСЫ

🎯 ВЕРДИКТ ДЛЯ ТЕБЯ
[ДА/НЕТ/ОГРАНИЧЕННО и ПОЧЕМУ]

🔄 ЧЕМ ЗАМЕНИТЬ
[2-3 альтернативы]

ВАЖНО: без markdown, 200-350 слов. Если не этикетка — попроси переснять."""

    try:
        return model.generate_content([prompt, image]).text.strip()
    except Exception as e:
        logger.error(f"Label error: {e}")
        return "❌ Ошибка. Попробуй ещё раз с чётким фото."

async def label_mode_on(update, context):
    context.user_data['photo_mode'] = 'label'
    await update.message.reply_text(
        "🏷️ АНАЛИЗ ЭТИКЕТКИ\n\nСфотографируй этикетку (состав, КБЖУ).\n\n"
        "📸 Советы:\n• Хорошее освещение\n• Текст в фокусе\n• Видно состав И таблицу",
        reply_markup=back_menu())

# === ГЕНЕРАТОР МЕНЮ ===
def generate_menu_from_fridge(image, user):
    prompt = f"""Ты — диетолог. На фото — холодильник пользователя.

ПОЛЬЗОВАТЕЛЬ: {user['name']}, {user['sex']}, {user['age']}л, цель {user['target_weight']}кг
НОРМА: {user['calories_goal']}ккал, Б{user['protein_goal']}/Ж{user['fat_goal']}/У{user['carbs_goal']}

ФОРМАТ:

🛒 ВИЖУ В ХОЛОДИЛЬНИКЕ

🍳 ЗАВТРАК (~25%)
☀️ ОБЕД (~35%)
🍎 ПЕРЕКУС (~10%)
🌙 УЖИН (~30%)

📊 ИТОГО
🔥 ХХХХ | 🥩 ХХ | 🧈 ХХ | 🍞 ХХ

💡 ЧЕГО НЕ ХВАТАЕТ

ВАЖНО: без markdown, 250-400 слов."""

    try:
        return model.generate_content([prompt, image]).text.strip()
    except Exception as e:
        logger.error(f"Fridge error: {e}")
        return "❌ Ошибка."

def generate_menu_from_text(text, user):
    prompt = f"""Ты — диетолог. Составь МЕНЮ НА ДЕНЬ.

ПОЛЬЗОВАТЕЛЬ: {user['name']}, {user['sex']}, {user['age']}л, цель {user['target_weight']}кг
НОРМА: {user['calories_goal']}ккал, Б{user['protein_goal']}/Ж{user['fat_goal']}/У{user['carbs_goal']}

ПОЖЕЛАНИЯ: {text}

ФОРМАТ:

🍳 ЗАВТРАК (~25%)
☀️ ОБЕД (~35%)
🍎 ПЕРЕКУС (~10%)
🌙 УЖИН (~30%)

📊 ИТОГО
🛒 СПИСОК ПОКУПОК
💡 СОВЕТ ДИЕТОЛОГА

ВАЖНО: без markdown, 300-450 слов."""

    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        logger.error(f"Menu error: {e}")
        return "❌ Ошибка."

async def menu_mode_on(update, context):
    context.user_data['photo_mode'] = 'fridge'
    keyboard = [["🍳 Без продуктов — сгенерируй меню"], [BTN_BACK]]
    await update.message.reply_text(
        "🍱 ГЕНЕРАТОР МЕНЮ\n\n📸 Сфотографируй холодильник или нажми кнопку ниже.",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True))

async def generate_menu_no_fridge(update, context):
    context.user_data['photo_mode'] = 'food'
    context.user_data['awaiting_menu_text'] = True
    await update.message.reply_text(
        "✍️ Опиши пожелания\n\nНапример: «Просто и быстро», «Без мяса», «Бюджетно», «Много овощей»",
        reply_markup=back_menu())

# === ТРЕНИРОВКИ ===
async def workout_view(update, context):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Сначала /start", reply_markup=ReplyKeyboardRemove())
        return

    keyboard = [[InlineKeyboardButton(t, callback_data=f"wktype:{t}")] for t in WORKOUT_TYPES.keys()]
    await update.message.reply_text(
        "🏃 ДОБАВИТЬ ТРЕНИРОВКУ\n\nШаг 1/3: Тип:",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def workout_type_callback(update, context):
    query = update.callback_query
    await query.answer()
    workout_type = query.data.split(":", 1)[1]
    context.user_data['workout_type'] = workout_type

    keyboard = [[InlineKeyboardButton(f"{info['label']} — {info['desc']}", callback_data=f"wkint:{code}")]
                for code, info in WORKOUT_INTENSITY.items()]
    await query.edit_message_text(
        f"🏃 {workout_type}\n\nШаг 2/3: Сложность?",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def workout_intensity_callback(update, context):
    query = update.callback_query
    await query.answer()
    intensity_code = query.data.split(":")[1]
    context.user_data['workout_intensity'] = intensity_code
    workout_type = context.user_data.get('workout_type', '')
    intensity_label = WORKOUT_INTENSITY[intensity_code]['label']

    keyboard = [
        [InlineKeyboardButton("15 мин", callback_data="wkdur:15"), InlineKeyboardButton("30 мин", callback_data="wkdur:30")],
        [InlineKeyboardButton("45 мин", callback_data="wkdur:45"), InlineKeyboardButton("60 мин", callback_data="wkdur:60")],
        [InlineKeyboardButton("90 мин", callback_data="wkdur:90"), InlineKeyboardButton("120 мин", callback_data="wkdur:120")]
    ]
    await query.edit_message_text(
        f"🏃 {workout_type}\n💪 Сложность: {intensity_label}\n\nШаг 3/3: Длительность?",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def workout_duration_callback(update, context):
    query = update.callback_query
    await query.answer()
    duration = int(query.data.split(":")[1])
    workout_type = context.user_data.get('workout_type')
    intensity_code = context.user_data.get('workout_intensity', 'medium')

    user_id = str(query.from_user.id)
    user = get_user(user_id)
    if not user or not workout_type:
        await query.edit_message_text("Ошибка.")
        return

    intensity = WORKOUT_INTENSITY[intensity_code]
    weight_factor = user['weight'] / 70
    base_kcal = WORKOUT_TYPES[workout_type] * duration * weight_factor
    calories_burned = round(base_kcal * intensity['factor'])

    tz_str = user.get('timezone', 'Europe/Kyiv')
    today = get_user_today(tz_str)

    supabase.table("workouts").insert({
        "user_id": user_id, "date": today,
        "type": f"{workout_type} {intensity['label']}",
        "duration_min": duration, "calories_burned": calories_burned
    }).execute()

    burned_today = daily_calories_burned(user_id, today)
    meals = get_today_meals(user_id, today)
    eaten = sum(m['calories'] for m in meals)
    net = eaten - burned_today

    await query.edit_message_text(
        f"✅ Тренировка добавлена!\n\n"
        f"🏃 {workout_type}\n💪 {intensity['label']}\n⏱️ {duration} мин\n"
        f"🔥 Сожжено: ~{calories_burned} ккал\n\n"
        f"📊 Сегодня:\n🍽️ Съедено: {eaten} ккал\n🏃 Сожжено: {burned_today} ккал\n"
        f"⚡ Нетто: {net} / {user['calories_goal']} ккал")

# === ДОНАТЫ ===
async def donate_view(update, context):
    keyboard = []
    for tier in DONATE_TIERS:
        keyboard.append([InlineKeyboardButton(
            f"{tier['emoji']} {tier['label']} — {tier['msg']}",
            callback_data=f"donate:{tier['stars']}")])

    await update.message.reply_text(
        "💛 ПОБЛАГОДАРИТЬ АВТОРА\n\nПривет! 👋\n\n"
        "Этот бот полностью бесплатный — без подписок и рекламы. "
        "В отличие от платных аналогов из AppStore (FatSecret, MyFitnessPal Premium, YAZIO Pro), "
        "которые берут от $5 до $15 в месяц.\n\n"
        "Если бот помогает — можно поблагодарить через Telegram Stars ⭐\n\n"
        "На что пойдут средства:\n💰 Серверы\n🤖 ИИ-API\n✨ Новые фишки\n\nСпасибо ❤️",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def donate_callback(update, context):
    query = update.callback_query
    await query.answer()
    stars = int(query.data.split(":")[1])

    tier = next((t for t in DONATE_TIERS if t['stars'] == stars), None)
    if not tier:
        return

    prices = [LabeledPrice(label=f"Поддержка NutriAI", amount=stars)]

    try:
        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title=f"{tier['emoji']} {tier['msg']}",
            description=f"Спасибо за поддержку NutriAI!",
            payload=f"donate_{stars}_{query.from_user.id}",
            provider_token="",
            currency="XTR",
            prices=prices
        )
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await query.message.reply_text("❌ Не удалось создать платёж.")

async def precheckout_callback(update, context):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment_callback(update, context):
    payment = update.message.successful_payment
    stars = payment.total_amount

    user_id = str(update.effective_user.id)
    try:
        supabase.table("donations").insert({
            "user_id": user_id, "stars": stars,
            "payload": payment.invoice_payload
        }).execute()
    except Exception as e:
        logger.error(f"Donation save error: {e}")

    await update.message.reply_text(
        f"💛 ОГРОМНОЕ СПАСИБО!\n\n⭐ {stars} Stars получены — это очень ценная поддержка!\n\n"
        f"Хорошего дня! 🌟",
        reply_markup=main_menu())

# === ДИЕТОЛОГ ===
async def ask_mode_on(update, context):
    context.user_data['ask_mode'] = True
    context.user_data['awaiting_clarification'] = False
    await update.message.reply_text(
        "👨‍⚕️ ВОПРОС ДИЕТОЛОГУ\n\nЗадай любой вопрос. Например:\n"
        "• Что добавить для белка?\n• Можно ли есть после 18:00?\n"
        "• Полезные перекусы?\n• Чем заменить сахар?",
        reply_markup=back_menu())

# === ПРОФИЛЬ ===
async def profile(update, context):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Сначала /start", reply_markup=ReplyKeyboardRemove())
        return

    tz_d = TIMEZONE_LABELS.get(user.get('timezone', 'Europe/Kyiv'), user.get('timezone', 'Europe/Kyiv'))
    summary = "✅ Включён" if user.get('daily_summary', True) else "❌ Выключен"

    await update.message.reply_text(
        f"👤 ПРОФИЛЬ\n\n"
        f"🏷️ {user['name']}, {user['age']}л, {user['sex']}\n"
        f"📏 {user['height']}см, ⚖️ {user['weight']}кг → 🎯 {user['target_weight']}кг\n"
        f"🏃 {user['activity']}\n🌍 {tz_d}\n🌙 Вечерний отчёт: {summary}\n\n"
        f"━━━━━━━━━━━━━━━\n📊 НОРМА:\n🔥 {user['calories_goal']} ккал\n"
        f"🥩 Б: {user['protein_goal']} | 🧈 Ж: {user['fat_goal']} | 🍞 У: {user['carbs_goal']}\n\n"
        f"💡 Изменить данные → Настройки → ✏️ Изменить данные",
        reply_markup=main_menu())

# === НАСТРОЙКИ ===
async def settings_view(update, context):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Сначала /start", reply_markup=ReplyKeyboardRemove())
        return

    daily = user.get('daily_summary', True)
    status = "✅ ВКЛЮЧЁН" if daily else "❌ ВЫКЛЮЧЕН"
    await update.message.reply_text(
        f"⚙️ НАСТРОЙКИ\n\n🌙 Вечерний отчёт: {status}\n\n"
        f"В 23:59 я могу присылать итог дня.\n\n"
        f"✏️ Изменить данные — обновить вес, рост, цель и др.",
        reply_markup=settings_menu(daily))

async def toggle_summary(update, context, enable):
    user_id = str(update.effective_user.id)
    supabase.table("users").update({"daily_summary": enable}).eq("user_id", user_id).execute()

    job_name = f"daily_summary_{user_id}"
    for job in context.application.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    if enable:
        user = get_user(user_id)
        if user:
            schedule_daily_summary(context.application, user)
        msg = "🔔 Включён."
    else:
        msg = "🔕 Выключен."
    await update.message.reply_text(msg, reply_markup=main_menu())

# === ✏️ РЕДАКТИРОВАНИЕ ДАННЫХ ===
async def edit_view(update, context):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Сначала /start", reply_markup=ReplyKeyboardRemove())
        return

    tz_label = TIMEZONE_LABELS.get(user.get('timezone', 'Europe/Kyiv'), user.get('timezone', '?'))

    keyboard = [
        [InlineKeyboardButton(f"🏷️ Имя ({user['name']})", callback_data="edit:edit_name")],
        [InlineKeyboardButton(f"🎂 Возраст ({user['age']})", callback_data="edit:edit_age")],
        [InlineKeyboardButton(f"⚧ Пол ({user['sex']})", callback_data="edit:edit_sex")],
        [InlineKeyboardButton(f"📏 Рост ({user['height']} см)", callback_data="edit:edit_height")],
        [InlineKeyboardButton(f"⚖️ Вес ({user['weight']} кг)", callback_data="edit:edit_weight")],
        [InlineKeyboardButton(f"🎯 Цель ({user['target_weight']} кг)", callback_data="edit:edit_target")],
        [InlineKeyboardButton(f"🏃 Активность ({user['activity']})", callback_data="edit:edit_activity")],
        [InlineKeyboardButton(f"🌍 Часовой пояс ({tz_label})", callback_data="edit:edit_tz")],
    ]

    await update.message.reply_text(
        "✏️ ИЗМЕНЕНИЕ ДАННЫХ\n\n"
        "Выбери что изменить.\n\n"
        "💡 При изменении веса, роста, возраста, пола, цели или активности — "
        "норма КБЖУ автоматически пересчитается.",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def edit_callback(update, context):
    query = update.callback_query
    await query.answer()
    field_key = query.data.split(":")[1]

    field = EDIT_FIELDS.get(field_key)
    if not field:
        return

    context.user_data['editing_field'] = field_key

    if field['type'] == 'choice':
        # Выбор из списка
        opts = field['options']
        if field_key == 'edit_tz':
            kb = [opts[i:i+2] for i in range(0, len(opts), 2)]
        elif field_key == 'edit_activity':
            kb = [["Минимальная", "Лёгкая"], ["Умеренная", "Высокая"], ["Очень высокая"]]
        else:
            kb = [opts]
        kb.append([BTN_BACK])
        await query.message.reply_text(
            f"{field['label']}\n\n{field['prompt']}",
            reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
    else:
        # Ввод текста/числа
        await query.message.reply_text(
            f"{field['label']}\n\n{field['prompt']}",
            reply_markup=ReplyKeyboardMarkup([[BTN_BACK]], resize_keyboard=True))

async def edit_process(update, context, user):
    field_key = context.user_data.get('editing_field')
    if not field_key:
        return

    field = EDIT_FIELDS.get(field_key)
    text = update.message.text
    user_id = str(update.effective_user.id)

    # Парсим значение
    new_value = None
    db_field = None

    if field_key == 'edit_name':
        new_value = text.strip()
        if len(new_value) < 1 or len(new_value) > 50:
            await update.message.reply_text("Имя 1-50 символов.")
            return
        db_field = 'name'

    elif field_key == 'edit_age':
        try:
            v = int(text)
            if v < field['min'] or v > field['max']:
                await update.message.reply_text(f"Возраст {field['min']}-{field['max']}.")
                return
            new_value = v
            db_field = 'age'
        except ValueError:
            await update.message.reply_text("Введи число.")
            return

    elif field_key == 'edit_sex':
        if text not in field['options']:
            await update.message.reply_text("Выбери из кнопок.",
                reply_markup=ReplyKeyboardMarkup([field['options'], [BTN_BACK]],
                    one_time_keyboard=True, resize_keyboard=True))
            return
        new_value = text
        db_field = 'sex'

    elif field_key == 'edit_height':
        try:
            v = int(text)
            if v < field['min'] or v > field['max']:
                await update.message.reply_text(f"Рост {field['min']}-{field['max']}.")
                return
            new_value = v
            db_field = 'height'
        except ValueError:
            await update.message.reply_text("Введи число.")
            return

    elif field_key in ('edit_weight', 'edit_target'):
        try:
            v = float(text.replace(',', '.'))
            if v < field['min'] or v > field['max']:
                await update.message.reply_text(f"Вес {field['min']}-{field['max']}.")
                return
            new_value = v
            db_field = 'weight' if field_key == 'edit_weight' else 'target_weight'
        except ValueError:
            await update.message.reply_text("Введи число.")
            return

    elif field_key == 'edit_activity':
        if text not in field['options']:
            kb = [["Минимальная", "Лёгкая"], ["Умеренная", "Высокая"], ["Очень высокая"], [BTN_BACK]]
            await update.message.reply_text("Выбери из кнопок.",
                reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
            return
        new_value = text
        db_field = 'activity'

    elif field_key == 'edit_tz':
        if text not in TIMEZONES:
            tz_btns = list(TIMEZONES.keys())
            kb = [tz_btns[i:i+2] for i in range(0, len(tz_btns), 2)]
            kb.append([BTN_BACK])
            await update.message.reply_text("Выбери из кнопок.",
                reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
            return
        new_value = TIMEZONES[text]
        db_field = 'timezone'

    # Сохраняем в базу
    update_data = {db_field: new_value}

    # Если меняли вес/рост/возраст/пол/цель/активность — пересчитываем нормы
    recalc_fields = {'weight', 'height', 'age', 'sex', 'target_weight', 'activity'}
    if db_field in recalc_fields:
        # Берём актуальные значения с учётом обновляемого
        current = {
            'weight': user['weight'], 'height': user['height'], 'age': user['age'],
            'sex': user['sex'], 'target_weight': user['target_weight'], 'activity': user['activity']
        }
        current[db_field] = new_value
        cal, p, f, c = calculate_norms(
            current['sex'], current['age'], current['height'],
            current['weight'], current['activity'], current['target_weight'])
        update_data['calories_goal'] = cal
        update_data['protein_goal'] = p
        update_data['fat_goal'] = f
        update_data['carbs_goal'] = c

    supabase.table("users").update(update_data).eq("user_id", user_id).execute()

    # Если меняли часовой пояс — пересоздаём задачу вечернего отчёта
    if db_field == 'timezone':
        updated_user = get_user(user_id)
        if updated_user and updated_user.get('daily_summary', True):
            schedule_daily_summary(context.application, updated_user)

    context.user_data['editing_field'] = None

    # Сообщение об успехе
    if 'calories_goal' in update_data:
        await update.message.reply_text(
            f"✅ {field['label']} обновлён!\n\n"
            f"📊 Новая норма пересчитана:\n"
            f"🔥 {update_data['calories_goal']} ккал\n"
            f"🥩 Б: {update_data['protein_goal']} | 🧈 Ж: {update_data['fat_goal']} | 🍞 У: {update_data['carbs_goal']}",
            reply_markup=main_menu())
    else:
        await update.message.reply_text(
            f"✅ {field['label']} обновлён!",
            reply_markup=main_menu())

# === СБРОС ===
async def reset_confirm(update, context):
    keyboard = [["✅ Да, сбросить"], ["❌ Отмена"]]
    await update.message.reply_text(
        "⚠️ Уверен? Все данные удалятся.\n\n"
        "💡 Если нужно изменить только вес/рост/цель — используй «✏️ Изменить данные» в Настройках.",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))

async def reset_do(update, context):
    user_id = str(update.effective_user.id)
    job_name = f"daily_summary_{user_id}"
    for job in context.application.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    supabase.table("users").delete().eq("user_id", user_id).execute()
    supabase.table("meals").delete().eq("user_id", user_id).execute()
    supabase.table("workouts").delete().eq("user_id", user_id).execute()
    supabase.table("favorite_meals").delete().eq("user_id", user_id).execute()
    await update.message.reply_text(
        "🔄 Профиль удалён.\n\n/start чтобы создать заново.",
        reply_markup=ReplyKeyboardRemove())

# === ПОМОЩЬ ===
async def help_cmd(update, context):
    await update.message.reply_text(
        "ℹ️ КАК ПОЛЬЗОВАТЬСЯ\n\n"
        "🍽️ Учёт еды:\n• Фото или текст — посчитаю КБЖУ\n• «⭐ Сохранить как частое»\n\n"
        f"📊 {BTN_STATS} — сегодня\n"
        f"📈 {BTN_HISTORY} — неделя/месяц\n"
        f"🔁 {BTN_FAVORITES} — частые блюда в один тап\n"
        f"🏃 {BTN_WORKOUT} — тренировки списываются с калорий\n"
        f"🏷️ {BTN_LABEL} — фото этикетки → стоит ли брать\n"
        f"🍱 {BTN_MENU} — меню по холодильнику или пожеланиям\n"
        f"💬 {BTN_ASK} — любой вопрос диетологу\n"
        f"⚙️ {BTN_SETTINGS} — отчёт 23:59, изменить данные, сброс\n"
        f"⭐ {BTN_DONATE} — поддержать автора\n\n"
        "💡 Совет: фоткай еду сверху для точной оценки.",
        reply_markup=main_menu())

# === ВЕЧЕРНИЙ ОТЧЁТ ===
def generate_daily_summary(user, meals, workouts):
    burned = sum(w['calories_burned'] for w in workouts) if workouts else 0
    workouts_text = ""
    if workouts:
        workouts_text = "🏃 ТРЕНИРОВКИ:\n" + "\n".join([f"- {w['type']} {w['duration_min']}мин: -{w['calories_burned']}ккал" for w in workouts]) + "\n\n"

    if not meals:
        prompt = f"""Ты — диетолог. {user['name']} сегодня НЕ вносил еду.\n\n{workouts_text}\nНапиши тёплое напоминание (60-100 слов). Без морализаторства, мотивирующе, без markdown."""
    else:
        meals_text = "\n".join([f"- {m['description']}: {m['calories']}ккал, Б{m['protein']}/Ж{m['fat']}/У{m['carbs']}" for m in meals])
        total_cal = sum(m['calories'] for m in meals)
        total_p = sum(m['protein'] for m in meals)
        total_f = sum(m['fat'] for m in meals)
        total_c = sum(m['carbs'] for m in meals)
        net = total_cal - burned

        prompt = f"""Ты — сертифицированный диетолог-нутрициолог с 15-летним опытом.

ПОЛЬЗОВАТЕЛЬ: {user['name']}, {user['age']}л, {user['sex']}, {user['height']}см, {user['weight']}кг → {user['target_weight']}кг, активность {user['activity']}
НОРМА: {user['calories_goal']}ккал, Б{user['protein_goal']}/Ж{user['fat_goal']}/У{user['carbs_goal']}

СЪЕДЕНО:
{meals_text}

{workouts_text}ИТОГО:
- Калории: {total_cal}/{user['calories_goal']} (нетто: {net})
- Б: {total_p:.0f}/{user['protein_goal']} | Ж: {total_f:.0f}/{user['fat_goal']} | У: {total_c:.0f}/{user['carbs_goal']}

ФОРМАТ:

🎯 ОЦЕНКА ДНЯ
✅ ЧТО БЫЛО ХОРОШО
⚠️ ЧТО УЛУЧШИТЬ (с объяснением ПОЧЕМУ)
💡 РЕКОМЕНДАЦИИ НА ЗАВТРА (с продуктами и количеством)
🌟 ИНСАЙТ ДНЯ

ВАЖНО: тёплый профессионал, конкретика, без воды, без markdown, 250-400 слов."""

    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        logger.error(f"Summary error: {e}")
        return None

async def send_daily_summary(context):
    job = context.job
    user_id = job.data['user_id']
    user = get_user(user_id)
    if not user or not user.get('daily_summary', True):
        return

    tz_str = user.get('timezone', 'Europe/Kyiv')
    today = get_user_today(tz_str)
    meals = get_today_meals(user_id, today)
    workouts = get_today_workouts(user_id, today)

    summary = generate_daily_summary(user, meals, workouts)
    if not summary:
        return

    total_cal = sum(m['calories'] for m in meals) if meals else 0
    burned = sum(w['calories_burned'] for w in workouts) if workouts else 0
    net = total_cal - burned
    bar = make_progress_bar(net, user['calories_goal'])

    burned_str = f"\n🏃 Сожжено: -{burned} ккал" if burned > 0 else ""
    msg = (f"🌙 ИТОГ ДНЯ\n━━━━━━━━━━━━━━━\n\n{bar}\n"
           f"🔥 {total_cal} / {user['calories_goal']} ккал{burned_str}\n\n"
           f"━━━━━━━━━━━━━━━\n\n{summary}\n\n"
           f"━━━━━━━━━━━━━━━\n💤 Хорошего сна!")

    try:
        await context.bot.send_message(chat_id=int(user_id), text=msg)
    except Exception as e:
        logger.error(f"Send summary fail {user_id}: {e}")

def schedule_daily_summary(application, user):
    user_id = user['user_id']
    tz_str = user.get('timezone', 'Europe/Kyiv')
    job_name = f"daily_summary_{user_id}"
    for job in application.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    try:
        tz = pytz.timezone(tz_str)
        application.job_queue.run_daily(
            send_daily_summary,
            time=dtime(hour=23, minute=59, tzinfo=tz),
            data={'user_id': user_id}, name=job_name)
        logger.info(f"Scheduled for {user_id}")
    except Exception as e:
        logger.error(f"Schedule fail {user_id}: {e}")

async def restore_all_jobs(application):
    try:
        users = supabase.table("users").select("*").execute()
        for u in users.data:
            if u.get('daily_summary', True):
                schedule_daily_summary(application, u)
        logger.info(f"Restored {len(users.data)} jobs")
    except Exception as e:
        logger.error(f"Restore fail: {e}")

async def cancel(update, context):
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def post_init(application):
    await restore_all_jobs(application)

# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            SEX: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sex)],
            HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_height)],
            WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_weight)],
            TARGET_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_target_weight)],
            ACTIVITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_activity)],
            TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_timezone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("reset", reset_confirm))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("settings", settings_view))
    app.add_handler(CommandHandler("donate", donate_view))

    app.add_handler(CallbackQueryHandler(history_callback, pattern=r"^hist:"))
    app.add_handler(CallbackQueryHandler(add_fav_callback, pattern=r"^addfav:"))
    app.add_handler(CallbackQueryHandler(del_fav_callback, pattern=r"^delfav:"))
    app.add_handler(CallbackQueryHandler(save_fav_callback, pattern=r"^savefav:"))
    app.add_handler(CallbackQueryHandler(workout_type_callback, pattern=r"^wktype:"))
    app.add_handler(CallbackQueryHandler(workout_intensity_callback, pattern=r"^wkint:"))
    app.add_handler(CallbackQueryHandler(workout_duration_callback, pattern=r"^wkdur:"))
    app.add_handler(CallbackQueryHandler(donate_callback, pattern=r"^donate:"))
    app.add_handler(CallbackQueryHandler(edit_callback, pattern=r"^edit:"))

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
