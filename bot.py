import os
import logging
import json
from datetime import date, datetime
from io import BytesIO
from PIL import Image
import pytz

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
import google.generativeai as genai
from supabase import create_client

# === НАСТРОЙКА ЛОГОВ ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# === ИНИЦИАЛИЗАЦИЯ ===
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-flash-latest')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# === СОСТОЯНИЯ РЕГИСТРАЦИИ ===
NAME, AGE, SEX, HEIGHT, WEIGHT, TARGET_WEIGHT, ACTIVITY, TIMEZONE = range(8)

# === ТЕКСТЫ КНОПОК МЕНЮ ===
BTN_STATS = "📊 Статистика"
BTN_PROFILE = "👤 Мой профиль"
BTN_RESET = "🔄 Сбросить профиль"
BTN_HELP = "ℹ️ Помощь"

# === ПОПУЛЯРНЫЕ ЧАСОВЫЕ ПОЯСА ===
TIMEZONES = {
    "🇺🇦 Киев": "Europe/Kyiv",
    "🇷🇺 Москва": "Europe/Moscow",
    "🇧🇾 Минск": "Europe/Minsk",
    "🇰🇿 Алматы": "Asia/Almaty",
    "🇺🇿 Ташкент": "Asia/Tashkent",
    "🇩🇪 Берлин": "Europe/Berlin",
    "🇬🇧 Лондон": "Europe/London",
    "🇺🇸 Нью-Йорк": "America/New_York",
    "🇺🇸 Лос-Анджелес": "America/Los_Angeles",
    "🇦🇪 Дубай": "Asia/Dubai",
    "🇹🇭 Бангкок": "Asia/Bangkok",
    "🇯🇵 Токио": "Asia/Tokyo",
}

# === ГЛАВНОЕ МЕНЮ ===
def main_menu():
    keyboard = [
        [BTN_STATS, BTN_PROFILE],
        [BTN_RESET, BTN_HELP]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

# === ПОЛУЧИТЬ ТЕКУЩУЮ ДАТУ ПОЛЬЗОВАТЕЛЯ ===
def get_user_today(timezone_str):
    try:
        tz = pytz.timezone(timezone_str)
        return datetime.now(tz).date().isoformat()
    except Exception:
        return date.today().isoformat()

def get_user_now(timezone_str):
    try:
        tz = pytz.timezone(timezone_str)
        return datetime.now(tz)
    except Exception:
        return datetime.now()

# === РАСЧЁТ КАЛОРИЙ ===
def calculate_norms(sex, age, height, weight, activity, target_weight):
    if sex == "Мужской":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    activity_map = {
        "Минимальная": 1.2,
        "Лёгкая": 1.375,
        "Умеренная": 1.55,
        "Высокая": 1.725,
        "Очень высокая": 1.9
    }
    tdee = bmr * activity_map.get(activity, 1.2)

    if target_weight < weight - 1:
        calories = tdee - 400
    elif target_weight > weight + 1:
        calories = tdee + 300
    else:
        calories = tdee

    calories = round(calories)
    protein = round(weight * 1.8)
    fat = round(calories * 0.25 / 9)
    carbs = round((calories - protein * 4 - fat * 9) / 4)

    return calories, protein, fat, carbs

# === ПРОГРЕСС-БАР ===
def make_progress_bar(current, goal, length=10):
    if goal == 0:
        return ""
    percent = min(current / goal, 1.0)
    filled = int(length * percent)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {int(percent * 100)}%"

# === КОМАНДА /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    result = supabase.table("users").select("*").eq("user_id", user_id).execute()

    if result.data:
        user = result.data[0]
        await update.message.reply_text(
            f"👋 С возвращением, {user['name']}!\n\n"
            f"📊 Твоя норма: {user['calories_goal']} ккал в день\n\n"
            f"🍽️ Просто отправь фото или описание еды — я посчитаю калории.\n\n"
            f"Используй кнопки внизу для навигации 👇",
            reply_markup=main_menu()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Привет! Я NutriAI — твой умный помощник по питанию.\n\n"
        "🤖 Я анализирую еду по фото или описанию с помощью ИИ и считаю калории, белки, жиры и углеводы.\n\n"
        "Сначала ответь на несколько вопросов, чтобы я рассчитал твою персональную норму.\n\n"
        "Как тебя зовут?",
        reply_markup=ReplyKeyboardRemove()
    )
    return NAME

# === ШАГИ РЕГИСТРАЦИИ ===
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text(
        f"Приятно познакомиться, {update.message.text}! 😊\n\nСколько тебе лет?"
    )
    return AGE

async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
        if age < 10 or age > 100:
            await update.message.reply_text("Введи реальный возраст (10-100).")
            return AGE
        context.user_data['age'] = age
        keyboard = [["Мужской", "Женский"]]
        await update.message.reply_text(
            "Укажи свой пол:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return SEX
    except ValueError:
        await update.message.reply_text("Введи число. Сколько тебе лет?")
        return AGE

async def get_sex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text not in ["Мужской", "Женский"]:
        keyboard = [["Мужской", "Женский"]]
        await update.message.reply_text(
            "Выбери из кнопок:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return SEX
    context.user_data['sex'] = update.message.text
    await update.message.reply_text(
        "Какой у тебя рост в сантиметрах? (например: 175)",
        reply_markup=ReplyKeyboardRemove()
    )
    return HEIGHT

async def get_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        height = int(update.message.text)
        if height < 100 or height > 250:
            await update.message.reply_text("Введи реальный рост (100-250 см).")
            return HEIGHT
        context.user_data['height'] = height
        await update.message.reply_text("Какой у тебя текущий вес в кг? (например: 75.5)")
        return WEIGHT
    except ValueError:
        await update.message.reply_text("Введи число. Например: 175")
        return HEIGHT

async def get_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = float(update.message.text.replace(',', '.'))
        if weight < 30 or weight > 300:
            await update.message.reply_text("Введи реальный вес (30-300 кг).")
            return WEIGHT
        context.user_data['weight'] = weight
        await update.message.reply_text("Какой у тебя желаемый вес в кг?")
        return TARGET_WEIGHT
    except ValueError:
        await update.message.reply_text("Введи число. Например: 75.5")
        return WEIGHT

async def get_target_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = float(update.message.text.replace(',', '.'))
        if target < 30 or target > 300:
            await update.message.reply_text("Введи реальный желаемый вес.")
            return TARGET_WEIGHT
        context.user_data['target_weight'] = target
        keyboard = [["Минимальная", "Лёгкая"], ["Умеренная", "Высокая"], ["Очень высокая"]]
        await update.message.reply_text(
            "Какой у тебя уровень активности?\n\n"
            "🪑 Минимальная — сидячая работа, мало движения\n"
            "🚶 Лёгкая — лёгкие тренировки 1-3 раза в неделю\n"
            "🏃 Умеренная — тренировки 3-5 раз в неделю\n"
            "💪 Высокая — интенсивные тренировки 6-7 раз\n"
            "🏋️ Очень высокая — физический труд + спорт",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ACTIVITY
    except ValueError:
        await update.message.reply_text("Введи число.")
        return TARGET_WEIGHT

async def get_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    options = ["Минимальная", "Лёгкая", "Умеренная", "Высокая", "Очень высокая"]
    if update.message.text not in options:
        keyboard = [["Минимальная", "Лёгкая"], ["Умеренная", "Высокая"], ["Очень высокая"]]
        await update.message.reply_text(
            "Выбери из кнопок:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ACTIVITY

    context.user_data['activity'] = update.message.text

    # Спрашиваем часовой пояс
    tz_buttons = list(TIMEZONES.keys())
    keyboard = [tz_buttons[i:i+2] for i in range(0, len(tz_buttons), 2)]

    await update.message.reply_text(
        "🌍 Выбери свой часовой пояс — это нужно чтобы статистика правильно показывала «сегодня»:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return TIMEZONE

async def get_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected = update.message.text
    if selected not in TIMEZONES:
        tz_buttons = list(TIMEZONES.keys())
        keyboard = [tz_buttons[i:i+2] for i in range(0, len(tz_buttons), 2)]
        await update.message.reply_text(
            "Выбери из кнопок:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return TIMEZONE

    context.user_data['timezone'] = TIMEZONES[selected]
    user_id = str(update.effective_user.id)
    d = context.user_data

    calories, protein, fat, carbs = calculate_norms(
        d['sex'], d['age'], d['height'],
        d['weight'], d['activity'], d['target_weight']
    )

    supabase.table("users").insert({
        "user_id": user_id,
        "name": d['name'],
        "age": d['age'],
        "sex": d['sex'],
        "height": d['height'],
        "weight": d['weight'],
        "target_weight": d['target_weight'],
        "activity": d['activity'],
        "calories_goal": calories,
        "protein_goal": protein,
        "fat_goal": fat,
        "carbs_goal": carbs,
        "timezone": d['timezone']
    }).execute()

    await update.message.reply_text(
        f"✅ Отлично, {d['name']}! Профиль создан.\n\n"
        f"📊 Твоя дневная норма:\n"
        f"🔥 Калории: {calories} ккал\n"
        f"🥩 Белки: {protein} г\n"
        f"🧈 Жиры: {fat} г\n"
        f"🍞 Углеводы: {carbs} г\n\n"
        f"🍽️ Теперь отправляй фото или описание еды — я посчитаю!\n\n"
        f"Используй кнопки внизу для навигации 👇",
        reply_markup=main_menu()
    )
    return ConversationHandler.END

# === АНАЛИЗ ЕДЫ ЧЕРЕЗ GEMINI ===
def analyze_food_with_ai(description=None, image=None, clarifications=None):
    prompt = """Ты — опытный диетолог. Твоя главная задача — БЫСТРО и ТОЧНО оценить КБЖУ блюда.

🎯 ГЛАВНЫЙ ПРИНЦИП:
Делай разумные допущения по умолчанию для типичных блюд. НЕ ЗАДАВАЙ вопросов если можешь оценить с погрешностью ±15-20% — это нормальная точность.

📌 ТИПИЧНЫЕ ДОПУЩЕНИЯ (используй их БЕЗ вопросов):
- Хлопья/мюсли с молоком → стандартная порция 40г хлопьев + 200мл молока 2.5%
- Жареное мясо/яйца → жарка на 1 ч.л. растительного масла
- Салаты с зелёными листьями → заправка 1 ч.л. масла или без неё
- Паста, рис, гречка → стандартная варка без масла
- Бутерброд с маслом → 5г сливочного масла
- Кофе/чай → без сахара и молока (если не сказано)
- Овощи на гарнир → варёные или на пару
- Размер порции непонятен → стандартная порция взрослого человека (250-350г)
- Соусы, которые видно немного → учитывай как стандартный соус (10-20г)

❓ ЗАДАВАЙ ВОПРОСЫ ТОЛЬКО ЕСЛИ:
1. Блюдо НЕВОЗМОЖНО идентифицировать по фото/описанию
2. Видна явно НЕОБЫЧНАЯ заправка/соус в большом количестве (густой слой майонеза, сливочный соус щедро) — что СИЛЬНО изменит калорийность (>30%)
3. Видно много масла/жира где его быть не должно (плавает в масле)
4. Порция явно НЕстандартная (огромная или крошечная)
5. Пользователь дал противоречивую информацию

❌ НЕ ЗАДАВАЙ ВОПРОСЫ если:
- Блюдо обычное и узнаваемое (даже если жареное — предположи стандартную жарку)
- Можешь оценить с разумной точностью используя допущения выше
- Уточнение изменит результат меньше чем на 20%

📋 ФОРМАТ ОТВЕТА:

Если можешь оценить (90% случаев) — ТОЛЬКО JSON:
{
  "status": "ok",
  "dish": "Название блюда",
  "weight_g": 350,
  "calories": 580,
  "protein": 28,
  "fat": 22,
  "carbs": 60,
  "comment": "Краткий комментарий с указанием сделанных допущений (например: «учтена стандартная жарка на растительном масле»)"
}

Если ДЕЙСТВИТЕЛЬНО нужно уточнение — ТОЛЬКО JSON:
{
  "status": "need_info",
  "question": "Один конкретный вопрос или 2-3 связанных вопроса в одном сообщении"
}

ВАЖНО:
- Возвращай ТОЛЬКО JSON, без markdown-обёрток
- Лучше дать оценку с допущениями и указать их в comment, чем замучить вопросами
- Помни: пользователь может уточнить детали в следующем сообщении сам, если захочет"""

    try:
        full_prompt = prompt
        if clarifications:
            full_prompt += f"\n\n📌 УТОЧНЕНИЯ ОТ ПОЛЬЗОВАТЕЛЯ:\n{clarifications}\n\nТеперь дай финальную оценку КБЖУ."

        if image:
            user_msg = description if description else "Проанализируй еду на фото"
            response = model.generate_content([full_prompt, image, user_msg])
        else:
            response = model.generate_content(f"{full_prompt}\n\nОписание еды: {description}")

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        return json.loads(text)
    except Exception as e:
        logger.error(f"AI error: {e}")
        return {"status": "error", "message": str(e)}

# === ОБРАБОТКА ФОТО ===
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_result = supabase.table("users").select("*").eq("user_id", user_id).execute()

    if not user_result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start", reply_markup=ReplyKeyboardRemove())
        return

    await update.message.reply_text("🔍 Анализирую фото...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    image = Image.open(BytesIO(bytes(file_bytes)))

    caption = update.message.caption or ""
    result = analyze_food_with_ai(description=caption, image=image)

    if result.get('status') == 'need_info':
        context.user_data['awaiting_clarification'] = True
        context.user_data['original_description'] = caption
        context.user_data['original_image'] = image
        context.user_data['clarifications'] = ''

    await process_ai_result(update, context, result, user_result.data[0])

# === ОБРАБОТКА ТЕКСТА ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # Обработка кнопок меню
    if text == BTN_STATS:
        await stats(update, context)
        return
    if text == BTN_PROFILE:
        await profile(update, context)
        return
    if text == BTN_RESET:
        await reset_confirm(update, context)
        return
    if text == BTN_HELP:
        await help_cmd(update, context)
        return
    if text == "✅ Да, сбросить":
        await reset_do(update, context)
        return
    if text == "❌ Отмена":
        await update.message.reply_text("Отмена.", reply_markup=main_menu())
        return

    user_id = str(update.effective_user.id)
    user_result = supabase.table("users").select("*").eq("user_id", user_id).execute()

    if not user_result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start", reply_markup=ReplyKeyboardRemove())
        return

    # Если ждём уточнение
    if context.user_data.get('awaiting_clarification'):
        original = context.user_data.get('original_description', '')
        original_image = context.user_data.get('original_image', None)
        previous_clarifications = context.user_data.get('clarifications', '')
        new_clarifications = previous_clarifications + f"\n- {text}" if previous_clarifications else f"- {text}"

        await update.message.reply_text("🔍 Учитываю уточнения...")
        result = analyze_food_with_ai(
            description=original,
            image=original_image,
            clarifications=new_clarifications
        )

        if result.get('status') == 'need_info':
            context.user_data['clarifications'] = new_clarifications
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

    await process_ai_result(update, context, result, user_result.data[0])

# === ОБРАБОТКА РЕЗУЛЬТАТА ИИ ===
async def process_ai_result(update, context, result, user):
    if result.get('status') == 'error':
        await update.message.reply_text("❌ Ошибка анализа. Попробуй ещё раз.", reply_markup=main_menu())
        return

    if result.get('status') == 'need_info':
        await update.message.reply_text(f"❓ {result['question']}", reply_markup=main_menu())
        return

    if result.get('status') == 'ok':
        user_id = str(update.effective_user.id)
        timezone_str = user.get('timezone', 'Europe/Kyiv')
        today = get_user_today(timezone_str)

        supabase.table("meals").insert({
            "user_id": user_id,
            "date": today,
            "description": result.get('dish', 'Блюдо'),
            "calories": result.get('calories', 0),
            "protein": result.get('protein', 0),
            "fat": result.get('fat', 0),
            "carbs": result.get('carbs', 0)
        }).execute()

        meals_today = supabase.table("meals").select("*").eq("user_id", user_id).eq("date", today).execute()
        total_cal = sum(m['calories'] for m in meals_today.data)
        total_p = sum(m['protein'] for m in meals_today.data)
        total_f = sum(m['fat'] for m in meals_today.data)
        total_c = sum(m['carbs'] for m in meals_today.data)

        cal_left = user['calories_goal'] - total_cal
        p_left = user['protein_goal'] - total_p
        f_left = user['fat_goal'] - total_f
        c_left = user['carbs_goal'] - total_c

        progress_bar = make_progress_bar(total_cal, user['calories_goal'])

        await update.message.reply_text(
            f"✅ Записал: {result.get('dish', 'Блюдо')}\n"
            f"≈ {result.get('weight_g', '?')} г\n\n"
            f"🔥 {result['calories']} ккал | 🥩 {result['protein']}г Б | "
            f"🧈 {result['fat']}г Ж | 🍞 {result['carbs']}г У\n"
            f"💬 {result.get('comment', '')}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 ИТОГО ЗА СЕГОДНЯ:\n"
            f"{progress_bar}\n\n"
            f"🔥 Калории: {total_cal} / {user['calories_goal']} (осталось {cal_left})\n"
            f"🥩 Белки: {total_p:.0f} / {user['protein_goal']} (осталось {p_left:.0f})\n"
            f"🧈 Жиры: {total_f:.0f} / {user['fat_goal']} (осталось {f_left:.0f})\n"
            f"🍞 Углеводы: {total_c:.0f} / {user['carbs_goal']} (осталось {c_left:.0f})",
            reply_markup=main_menu()
        )

# === КНОПКА: СТАТИСТИКА ===
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_result = supabase.table("users").select("*").eq("user_id", user_id).execute()

    if not user_result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start", reply_markup=ReplyKeyboardRemove())
        return

    user = user_result.data[0]
    timezone_str = user.get('timezone', 'Europe/Kyiv')
    today = get_user_today(timezone_str)
    now = get_user_now(timezone_str)

    # Красивая дата
    months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
              'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
    weekdays = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
    date_str = f"{now.day} {months[now.month - 1]} ({weekdays[now.weekday()]})"
    time_str = now.strftime("%H:%M")

    meals = supabase.table("meals").select("*").eq("user_id", user_id).eq("date", today).execute()

    if not meals.data:
        await update.message.reply_text(
            f"📊 СТАТИСТИКА\n"
            f"📅 {date_str}\n"
            f"🕐 {time_str}\n\n"
            f"Сегодня ты ещё ничего не ел.\n\n"
            f"🎯 Твоя норма: {user['calories_goal']} ккал",
            reply_markup=main_menu()
        )
        return

    total_cal = sum(m['calories'] for m in meals.data)
    total_p = sum(m['protein'] for m in meals.data)
    total_f = sum(m['fat'] for m in meals.data)
    total_c = sum(m['carbs'] for m in meals.data)

    progress_bar = make_progress_bar(total_cal, user['calories_goal'])
    meals_list = "\n".join([f"• {m['description']} — {m['calories']} ккал" for m in meals.data])

    await update.message.reply_text(
        f"📊 СТАТИСТИКА\n"
        f"📅 {date_str}\n"
        f"🕐 {time_str}\n\n"
        f"{progress_bar}\n\n"
        f"🔥 Калории: {total_cal} / {user['calories_goal']} ккал\n"
        f"🥩 Белки: {total_p:.0f} / {user['protein_goal']} г\n"
        f"🧈 Жиры: {total_f:.0f} / {user['fat_goal']} г\n"
        f"🍞 Углеводы: {total_c:.0f} / {user['carbs_goal']} г\n\n"
        f"🍽️ Приёмы пищи ({len(meals.data)}):\n{meals_list}",
        reply_markup=main_menu()
    )

# === КНОПКА: ПРОФИЛЬ ===
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    result = supabase.table("users").select("*").eq("user_id", user_id).execute()

    if not result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start", reply_markup=ReplyKeyboardRemove())
        return

    user = result.data[0]
    tz_display = user.get('timezone', 'Europe/Kyiv').replace('_', ' ')

    await update.message.reply_text(
        f"👤 ТВОЙ ПРОФИЛЬ\n\n"
        f"🏷️ Имя: {user['name']}\n"
        f"🎂 Возраст: {user['age']} лет\n"
        f"⚧ Пол: {user['sex']}\n"
        f"📏 Рост: {user['height']} см\n"
        f"⚖️ Текущий вес: {user['weight']} кг\n"
        f"🎯 Желаемый вес: {user['target_weight']} кг\n"
        f"🏃 Активность: {user['activity']}\n"
        f"🌍 Часовой пояс: {tz_display}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 ДНЕВНАЯ НОРМА:\n"
        f"🔥 Калории: {user['calories_goal']} ккал\n"
        f"🥩 Белки: {user['protein_goal']} г\n"
        f"🧈 Жиры: {user['fat_goal']} г\n"
        f"🍞 Углеводы: {user['carbs_goal']} г",
        reply_markup=main_menu()
    )

# === КНОПКА: СБРОС (подтверждение) ===
async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["✅ Да, сбросить"], ["❌ Отмена"]]
    await update.message.reply_text(
        "⚠️ Ты уверен?\n\n"
        "Все твои данные и история питания будут удалены. Это действие нельзя отменить.",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

# === КНОПКА: СБРОС (выполнение) ===
async def reset_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    supabase.table("users").delete().eq("user_id", user_id).execute()
    supabase.table("meals").delete().eq("user_id", user_id).execute()
    await update.message.reply_text(
        "🔄 Профиль и история удалены.\n\nНапиши /start чтобы создать профиль заново.",
        reply_markup=ReplyKeyboardRemove()
    )

# === КНОПКА: ПОМОЩЬ ===
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ КАК ПОЛЬЗОВАТЬСЯ БОТОМ\n\n"
        "🍽️ Чтобы добавить приём пищи:\n"
        "• Отправь фото еды\n"
        "• Или опиши словами что ты ел\n\n"
        "🤖 ИИ проанализирует и посчитает КБЖУ. Если что-то непонятно — задаст уточняющие вопросы.\n\n"
        "📊 Кнопки меню:\n"
        f"• {BTN_STATS} — твоя статистика за сегодня\n"
        f"• {BTN_PROFILE} — твои данные и нормы\n"
        f"• {BTN_RESET} — удалить профиль и начать заново\n\n"
        "💡 Совет: фотографируй еду сверху — так ИИ точнее оценит порцию.",
        reply_markup=main_menu()
    )

# === ОТМЕНА ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# === ЗАПУСК ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()

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
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
