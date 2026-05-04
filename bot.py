import os
import logging
import json
from datetime import date, datetime, time as dtime
from io import BytesIO
from PIL import Image
import pytz

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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

# === КНОПКИ МЕНЮ ===
BTN_STATS = "📊 Статистика"
BTN_PROFILE = "👤 Мой профиль"
BTN_ASK = "💬 Спросить диетолога"
BTN_SETTINGS = "⚙️ Настройки"
BTN_HELP = "ℹ️ Помощь"
BTN_RESET = "🔄 Сбросить профиль"

# === ЧАСОВЫЕ ПОЯСА ===
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

# === МЕНЮ ===
def main_menu():
    keyboard = [
        [BTN_STATS, BTN_ASK],
        [BTN_PROFILE, BTN_SETTINGS],
        [BTN_HELP]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def settings_menu(daily_summary_on):
    toggle = "🔕 Выключить вечерний отчёт" if daily_summary_on else "🔔 Включить вечерний отчёт"
    keyboard = [
        [toggle],
        [BTN_RESET],
        ["⬅️ Назад в меню"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

# === УТИЛИТЫ ВРЕМЕНИ ===
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
        "Минимальная": 1.2, "Лёгкая": 1.375, "Умеренная": 1.55,
        "Высокая": 1.725, "Очень высокая": 1.9
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
        # Планируем вечерний отчёт если включён
        if user.get('daily_summary', True):
            schedule_daily_summary(context.application, user)

        await update.message.reply_text(
            f"👋 С возвращением, {user['name']}!\n\n"
            f"📊 Твоя норма: {user['calories_goal']} ккал в день\n\n"
            f"🍽️ Отправь фото или описание еды — я посчитаю.\n"
            f"💬 Или нажми «Спросить диетолога» чтобы задать вопрос.\n\n"
            f"Используй кнопки внизу 👇",
            reply_markup=main_menu()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Привет! Я NutriAI — твой умный помощник по питанию.\n\n"
        "🤖 Я анализирую еду по фото или описанию, считаю КБЖУ и могу отвечать на вопросы по диетологии.\n\n"
        "Сначала ответь на несколько вопросов, чтобы я рассчитал твою персональную норму.\n\n"
        "Как тебя зовут?",
        reply_markup=ReplyKeyboardRemove()
    )
    return NAME

# === ШАГИ РЕГИСТРАЦИИ ===
async def get_name(update, context):
    context.user_data['name'] = update.message.text
    await update.message.reply_text(f"Приятно познакомиться, {update.message.text}! 😊\n\nСколько тебе лет?")
    return AGE

async def get_age(update, context):
    try:
        age = int(update.message.text)
        if age < 10 or age > 100:
            await update.message.reply_text("Введи реальный возраст (10-100).")
            return AGE
        context.user_data['age'] = age
        keyboard = [["Мужской", "Женский"]]
        await update.message.reply_text("Укажи свой пол:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return SEX
    except ValueError:
        await update.message.reply_text("Введи число.")
        return AGE

async def get_sex(update, context):
    if update.message.text not in ["Мужской", "Женский"]:
        keyboard = [["Мужской", "Женский"]]
        await update.message.reply_text("Выбери из кнопок:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return SEX
    context.user_data['sex'] = update.message.text
    await update.message.reply_text("Какой у тебя рост в сантиметрах? (например: 175)",
        reply_markup=ReplyKeyboardRemove())
    return HEIGHT

async def get_height(update, context):
    try:
        height = int(update.message.text)
        if height < 100 or height > 250:
            await update.message.reply_text("Введи реальный рост (100-250 см).")
            return HEIGHT
        context.user_data['height'] = height
        await update.message.reply_text("Какой у тебя текущий вес в кг?")
        return WEIGHT
    except ValueError:
        await update.message.reply_text("Введи число.")
        return HEIGHT

async def get_weight(update, context):
    try:
        weight = float(update.message.text.replace(',', '.'))
        if weight < 30 or weight > 300:
            await update.message.reply_text("Введи реальный вес (30-300 кг).")
            return WEIGHT
        context.user_data['weight'] = weight
        await update.message.reply_text("Какой у тебя желаемый вес в кг?")
        return TARGET_WEIGHT
    except ValueError:
        await update.message.reply_text("Введи число.")
        return WEIGHT

async def get_target_weight(update, context):
    try:
        target = float(update.message.text.replace(',', '.'))
        if target < 30 or target > 300:
            await update.message.reply_text("Введи реальный вес.")
            return TARGET_WEIGHT
        context.user_data['target_weight'] = target
        keyboard = [["Минимальная", "Лёгкая"], ["Умеренная", "Высокая"], ["Очень высокая"]]
        await update.message.reply_text(
            "Какой у тебя уровень активности?\n\n"
            "🪑 Минимальная — сидячая работа\n"
            "🚶 Лёгкая — 1-3 тренировки в неделю\n"
            "🏃 Умеренная — 3-5 тренировок\n"
            "💪 Высокая — 6-7 тренировок\n"
            "🏋️ Очень высокая — физический труд + спорт",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return ACTIVITY
    except ValueError:
        await update.message.reply_text("Введи число.")
        return TARGET_WEIGHT

async def get_activity(update, context):
    options = ["Минимальная", "Лёгкая", "Умеренная", "Высокая", "Очень высокая"]
    if update.message.text not in options:
        keyboard = [["Минимальная", "Лёгкая"], ["Умеренная", "Высокая"], ["Очень высокая"]]
        await update.message.reply_text("Выбери из кнопок:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return ACTIVITY

    context.user_data['activity'] = update.message.text
    tz_buttons = list(TIMEZONES.keys())
    keyboard = [tz_buttons[i:i+2] for i in range(0, len(tz_buttons), 2)]
    await update.message.reply_text(
        "🌍 Выбери свой часовой пояс:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return TIMEZONE

async def get_timezone(update, context):
    selected = update.message.text
    if selected not in TIMEZONES:
        tz_buttons = list(TIMEZONES.keys())
        keyboard = [tz_buttons[i:i+2] for i in range(0, len(tz_buttons), 2)]
        await update.message.reply_text("Выбери из кнопок:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return TIMEZONE

    context.user_data['timezone'] = TIMEZONES[selected]
    user_id = str(update.effective_user.id)
    d = context.user_data

    calories, protein, fat, carbs = calculate_norms(
        d['sex'], d['age'], d['height'], d['weight'], d['activity'], d['target_weight'])

    user_data = {
        "user_id": user_id, "name": d['name'], "age": d['age'], "sex": d['sex'],
        "height": d['height'], "weight": d['weight'], "target_weight": d['target_weight'],
        "activity": d['activity'], "calories_goal": calories, "protein_goal": protein,
        "fat_goal": fat, "carbs_goal": carbs, "timezone": d['timezone'],
        "daily_summary": True
    }

    supabase.table("users").insert(user_data).execute()

    # Запускаем ежедневный отчёт
    schedule_daily_summary(context.application, user_data)

    await update.message.reply_text(
        f"✅ Отлично, {d['name']}! Профиль создан.\n\n"
        f"📊 Твоя дневная норма:\n"
        f"🔥 Калории: {calories} ккал\n"
        f"🥩 Белки: {protein} г\n"
        f"🧈 Жиры: {fat} г\n"
        f"🍞 Углеводы: {carbs} г\n\n"
        f"🌙 Каждый день в 23:59 я буду присылать итог дня с рекомендациями диетолога. "
        f"Можно выключить в Настройках.\n\n"
        f"Используй кнопки внизу 👇",
        reply_markup=main_menu())
    return ConversationHandler.END

# === АНАЛИЗ ЕДЫ ===
def analyze_food_with_ai(description=None, image=None, clarifications=None):
    prompt = """Ты — опытный диетолог. Твоя главная задача — БЫСТРО и ТОЧНО оценить КБЖУ блюда.

🎯 ГЛАВНЫЙ ПРИНЦИП:
Делай разумные допущения по умолчанию. НЕ ЗАДАВАЙ вопросов если можешь оценить с погрешностью ±15-20%.

📌 ТИПИЧНЫЕ ДОПУЩЕНИЯ:
- Хлопья/мюсли с молоком → 40г хлопьев + 200мл молока 2.5%
- Жареное мясо/яйца → 1 ч.л. растительного масла
- Салаты с зелёными листьями → 1 ч.л. масла или без
- Паста, рис, гречка → варка без масла
- Бутерброд → 5г сливочного масла
- Кофе/чай → без сахара
- Овощи на гарнир → варёные/на пару
- Размер непонятен → стандартная порция (250-350г)

❓ ЗАДАВАЙ ВОПРОСЫ ТОЛЬКО ЕСЛИ:
1. Блюдо невозможно идентифицировать
2. Видна явно НЕОБЫЧНАЯ заправка в большом количестве
3. Видно много масла где его быть не должно
4. Порция явно нестандартная
5. Противоречивая информация

📋 ФОРМАТ:

Если можешь оценить — ТОЛЬКО JSON:
{
  "status": "ok",
  "dish": "Название",
  "weight_g": 350,
  "calories": 580,
  "protein": 28,
  "fat": 22,
  "carbs": 60,
  "comment": "Комментарий с допущениями"
}

Если нужно уточнение — ТОЛЬКО JSON:
{
  "status": "need_info",
  "question": "Вопрос"
}

Только JSON, без markdown."""

    try:
        full_prompt = prompt
        if clarifications:
            full_prompt += f"\n\n📌 УТОЧНЕНИЯ:\n{clarifications}\n\nДай финальную оценку."

        if image:
            user_msg = description if description else "Проанализируй еду на фото"
            response = model.generate_content([full_prompt, image, user_msg])
        else:
            response = model.generate_content(f"{full_prompt}\n\nОписание: {description}")

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

# === СПРОСИТЬ ДИЕТОЛОГА (свободный диалог) ===
def ask_dietitian_ai(question, user_data):
    prompt = f"""Ты — сертифицированный диетолог-нутрициолог с 15-летним опытом. Отвечай на вопрос пользователя профессионально, но дружелюбно и понятно.

📋 ДАННЫЕ ПОЛЬЗОВАТЕЛЯ:
- Имя: {user_data['name']}
- Возраст: {user_data['age']}, пол: {user_data['sex']}
- Рост: {user_data['height']} см, вес: {user_data['weight']} кг
- Цель: {user_data['target_weight']} кг
- Активность: {user_data['activity']}
- Норма: {user_data['calories_goal']} ккал, Б{user_data['protein_goal']}/Ж{user_data['fat_goal']}/У{user_data['carbs_goal']}

🎯 ПРАВИЛА ОТВЕТА:
- Опирайся на данные пользователя выше когда это уместно
- Давай конкретные рекомендации с цифрами и примерами продуктов
- Объясняй ПОЧЕМУ, а не только ЧТО
- Если вопрос требует медицинского осмотра — порекомендуй обратиться к врачу
- НЕ давай советы по лекарствам, БАДам в лечебных целях, диетам при болезнях
- Используй эмодзи умеренно для структурирования
- Длина ответа: 150-400 слов в зависимости от сложности вопроса
- Если вопрос НЕ про питание/здоровье — мягко верни к теме питания

❓ ВОПРОС ПОЛЬЗОВАТЕЛЯ:
{question}

Ответь живым человеческим языком, без markdown-разметки. Можешь использовать эмодзи и переносы строк для структурирования."""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Dietitian AI error: {e}")
        return "❌ Не получилось связаться с ИИ-диетологом. Попробуй ещё раз через минуту."

# === ОБРАБОТКА ФОТО ===
async def handle_photo(update, context):
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
        context.user_data['ask_mode'] = False

    await process_ai_result(update, context, result, user_result.data[0])

# === ОБРАБОТКА ТЕКСТА ===
async def handle_text(update, context):
    text = update.message.text

    # Кнопки меню
    if text == BTN_STATS:
        await stats(update, context)
        return
    if text == BTN_PROFILE:
        await profile(update, context)
        return
    if text == BTN_HELP:
        await help_cmd(update, context)
        return
    if text == BTN_SETTINGS:
        await settings_view(update, context)
        return
    if text == BTN_ASK:
        await ask_mode_on(update, context)
        return
    if text == "⬅️ Назад в меню":
        context.user_data['ask_mode'] = False
        await update.message.reply_text("Главное меню:", reply_markup=main_menu())
        return
    if text == BTN_RESET:
        await reset_confirm(update, context)
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

    user_id = str(update.effective_user.id)
    user_result = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not user_result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start", reply_markup=ReplyKeyboardRemove())
        return

    user = user_result.data[0]

    # Режим "Спросить диетолога"
    if context.user_data.get('ask_mode'):
        await update.message.reply_text("💭 Думаю над ответом...")
        answer = ask_dietitian_ai(text, user)
        await update.message.reply_text(
            f"👨‍⚕️ {answer}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💬 Можешь задать ещё вопрос или нажми «⬅️ Назад в меню»",
            reply_markup=ReplyKeyboardMarkup(
                [["⬅️ Назад в меню"]], resize_keyboard=True, is_persistent=True))
        return

    # Уточнение по предыдущему блюду
    if context.user_data.get('awaiting_clarification'):
        original = context.user_data.get('original_description', '')
        original_image = context.user_data.get('original_image', None)
        previous = context.user_data.get('clarifications', '')
        new_clar = previous + f"\n- {text}" if previous else f"- {text}"

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

# === ВКЛЮЧЕНИЕ РЕЖИМА "СПРОСИТЬ ДИЕТОЛОГА" ===
async def ask_mode_on(update, context):
    context.user_data['ask_mode'] = True
    context.user_data['awaiting_clarification'] = False
    await update.message.reply_text(
        "👨‍⚕️ РЕЖИМ ВОПРОСОВ ДИЕТОЛОГУ\n\n"
        "Задай любой вопрос о питании, например:\n"
        "• Что добавить в рацион чтобы было больше белка?\n"
        "• Можно ли есть после 18:00?\n"
        "• Какие перекусы будут полезными?\n"
        "• Чем заменить сахар?\n"
        "• Что есть до и после тренировки?\n\n"
        "Напиши свой вопрос 👇",
        reply_markup=ReplyKeyboardMarkup(
            [["⬅️ Назад в меню"]], resize_keyboard=True, is_persistent=True))

# === ОБРАБОТКА РЕЗУЛЬТАТА АНАЛИЗА ЕДЫ ===
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
            "user_id": user_id, "date": today,
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

        progress_bar = make_progress_bar(total_cal, user['calories_goal'])

        await update.message.reply_text(
            f"✅ Записал: {result.get('dish', 'Блюдо')}\n"
            f"≈ {result.get('weight_g', '?')} г\n\n"
            f"🔥 {result['calories']} ккал | 🥩 {result['protein']}г Б | "
            f"🧈 {result['fat']}г Ж | 🍞 {result['carbs']}г У\n"
            f"💬 {result.get('comment', '')}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 ИТОГО ЗА СЕГОДНЯ:\n{progress_bar}\n\n"
            f"🔥 Калории: {total_cal} / {user['calories_goal']} (осталось {user['calories_goal'] - total_cal})\n"
            f"🥩 Белки: {total_p:.0f} / {user['protein_goal']} (осталось {user['protein_goal'] - total_p:.0f})\n"
            f"🧈 Жиры: {total_f:.0f} / {user['fat_goal']} (осталось {user['fat_goal'] - total_f:.0f})\n"
            f"🍞 Углеводы: {total_c:.0f} / {user['carbs_goal']} (осталось {user['carbs_goal'] - total_c:.0f})",
            reply_markup=main_menu())

# === СТАТИСТИКА ===
async def stats(update, context):
    user_id = str(update.effective_user.id)
    user_result = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not user_result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start", reply_markup=ReplyKeyboardRemove())
        return

    user = user_result.data[0]
    timezone_str = user.get('timezone', 'Europe/Kyiv')
    today = get_user_today(timezone_str)
    now = get_user_now(timezone_str)

    months = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
    weekdays = ['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье']
    date_str = f"{now.day} {months[now.month-1]} ({weekdays[now.weekday()]})"
    time_str = now.strftime("%H:%M")

    meals = supabase.table("meals").select("*").eq("user_id", user_id).eq("date", today).execute()
    if not meals.data:
        await update.message.reply_text(
            f"📊 СТАТИСТИКА\n📅 {date_str}\n🕐 {time_str}\n\n"
            f"Сегодня ты ещё ничего не ел.\n\n🎯 Норма: {user['calories_goal']} ккал",
            reply_markup=main_menu())
        return

    total_cal = sum(m['calories'] for m in meals.data)
    total_p = sum(m['protein'] for m in meals.data)
    total_f = sum(m['fat'] for m in meals.data)
    total_c = sum(m['carbs'] for m in meals.data)
    progress_bar = make_progress_bar(total_cal, user['calories_goal'])
    meals_list = "\n".join([f"• {m['description']} — {m['calories']} ккал" for m in meals.data])

    await update.message.reply_text(
        f"📊 СТАТИСТИКА\n📅 {date_str}\n🕐 {time_str}\n\n{progress_bar}\n\n"
        f"🔥 Калории: {total_cal} / {user['calories_goal']} ккал\n"
        f"🥩 Белки: {total_p:.0f} / {user['protein_goal']} г\n"
        f"🧈 Жиры: {total_f:.0f} / {user['fat_goal']} г\n"
        f"🍞 Углеводы: {total_c:.0f} / {user['carbs_goal']} г\n\n"
        f"🍽️ Приёмы пищи ({len(meals.data)}):\n{meals_list}",
        reply_markup=main_menu())

# === ПРОФИЛЬ ===
async def profile(update, context):
    user_id = str(update.effective_user.id)
    result = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start", reply_markup=ReplyKeyboardRemove())
        return

    user = result.data[0]
    tz_display = user.get('timezone', 'Europe/Kyiv').replace('_', ' ')
    summary_status = "✅ Включён" if user.get('daily_summary', True) else "❌ Выключен"

    await update.message.reply_text(
        f"👤 ТВОЙ ПРОФИЛЬ\n\n"
        f"🏷️ Имя: {user['name']}\n"
        f"🎂 Возраст: {user['age']} лет\n"
        f"⚧ Пол: {user['sex']}\n"
        f"📏 Рост: {user['height']} см\n"
        f"⚖️ Вес: {user['weight']} кг\n"
        f"🎯 Цель: {user['target_weight']} кг\n"
        f"🏃 Активность: {user['activity']}\n"
        f"🌍 Часовой пояс: {tz_display}\n"
        f"🌙 Вечерний отчёт: {summary_status}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 ДНЕВНАЯ НОРМА:\n"
        f"🔥 {user['calories_goal']} ккал\n"
        f"🥩 Б: {user['protein_goal']} г | 🧈 Ж: {user['fat_goal']} г | 🍞 У: {user['carbs_goal']} г",
        reply_markup=main_menu())

# === НАСТРОЙКИ ===
async def settings_view(update, context):
    user_id = str(update.effective_user.id)
    result = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start", reply_markup=ReplyKeyboardRemove())
        return

    user = result.data[0]
    daily_on = user.get('daily_summary', True)
    status = "✅ ВКЛЮЧЁН" if daily_on else "❌ ВЫКЛЮЧЕН"

    await update.message.reply_text(
        f"⚙️ НАСТРОЙКИ\n\n"
        f"🌙 Вечерний отчёт: {status}\n\n"
        f"Каждый день в 23:59 (по твоему часовому поясу) я могу присылать "
        f"итог дня и персональные рекомендации диетолога.",
        reply_markup=settings_menu(daily_on))

async def toggle_summary(update, context, enable):
    user_id = str(update.effective_user.id)
    supabase.table("users").update({"daily_summary": enable}).eq("user_id", user_id).execute()

    # Удаляем или создаём задачу
    job_name = f"daily_summary_{user_id}"
    current_jobs = context.application.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()

    if enable:
        result = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if result.data:
            schedule_daily_summary(context.application, result.data[0])
        msg = "🔔 Вечерний отчёт ВКЛЮЧЁН.\n\nКаждый день в 23:59 ты будешь получать итоги и рекомендации."
    else:
        msg = "🔕 Вечерний отчёт ВЫКЛЮЧЕН.\n\nТы можешь включить его обратно в любой момент."

    await update.message.reply_text(msg, reply_markup=main_menu())

# === СБРОС ===
async def reset_confirm(update, context):
    keyboard = [["✅ Да, сбросить"], ["❌ Отмена"]]
    await update.message.reply_text(
        "⚠️ Ты уверен?\n\nВсе данные и история удалятся безвозвратно.",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))

async def reset_do(update, context):
    user_id = str(update.effective_user.id)
    # Удаляем задачу из планировщика
    job_name = f"daily_summary_{user_id}"
    for job in context.application.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    supabase.table("users").delete().eq("user_id", user_id).execute()
    supabase.table("meals").delete().eq("user_id", user_id).execute()
    await update.message.reply_text(
        "🔄 Профиль удалён.\n\nНапиши /start чтобы создать заново.",
        reply_markup=ReplyKeyboardRemove())

# === ПОМОЩЬ ===
async def help_cmd(update, context):
    await update.message.reply_text(
        "ℹ️ КАК ПОЛЬЗОВАТЬСЯ БОТОМ\n\n"
        "🍽️ Учёт питания:\n"
        "• Отправь фото еды\n"
        "• Или опиши словами\n"
        "ИИ посчитает КБЖУ и запишет в дневник.\n\n"
        "💬 Спросить диетолога:\n"
        "Любые вопросы про питание — что добавить в рацион, "
        "как набрать белок, чем заменить сахар и т.д.\n\n"
        "🌙 Вечерний отчёт:\n"
        "В 23:59 я подведу итог дня и дам рекомендации. "
        "Можно выключить в Настройках.\n\n"
        "📊 Кнопки меню:\n"
        f"• {BTN_STATS} — статистика за сегодня\n"
        f"• {BTN_ASK} — задать вопрос диетологу\n"
        f"• {BTN_PROFILE} — твои данные\n"
        f"• {BTN_SETTINGS} — настройки\n\n"
        "💡 Совет: фотографируй еду сверху для точной оценки порции.",
        reply_markup=main_menu())

# === ВЕЧЕРНИЙ ОТЧЁТ ===
def generate_daily_summary(user, meals):
    if not meals:
        prompt = f"""Ты — диетолог. Пользователь {user['name']} сегодня НЕ ВНОСИЛ приёмы пищи.

Напиши короткое (60-100 слов), дружелюбное напоминание о важности учёта питания и регулярности приёмов пищи. Без морализаторства. Закончи мотивирующей фразой."""
    else:
        meals_text = "\n".join([f"- {m['description']}: {m['calories']} ккал, Б{m['protein']}/Ж{m['fat']}/У{m['carbs']}" for m in meals])
        total_cal = sum(m['calories'] for m in meals)
        total_p = sum(m['protein'] for m in meals)
        total_f = sum(m['fat'] for m in meals)
        total_c = sum(m['carbs'] for m in meals)

        prompt = f"""Ты — сертифицированный диетолог-нутрициолог с 15-летним опытом. Проанализируй день питания пользователя и дай ПРОФЕССИОНАЛЬНЫЕ рекомендации.

📋 ПОЛЬЗОВАТЕЛЬ:
- {user['name']}, {user['age']} лет, {user['sex']}
- Рост {user['height']} см, вес {user['weight']} кг → цель {user['target_weight']} кг
- Активность: {user['activity']}

🎯 ДНЕВНАЯ НОРМА:
- Калории: {user['calories_goal']} ккал
- Белки: {user['protein_goal']} г
- Жиры: {user['fat_goal']} г
- Углеводы: {user['carbs_goal']} г

🍽️ СЪЕДЕНО СЕГОДНЯ:
{meals_text}

📊 ИТОГО:
- Калории: {total_cal} / {user['calories_goal']} ({total_cal - user['calories_goal']:+d})
- Белки: {total_p:.0f} / {user['protein_goal']} ({total_p - user['protein_goal']:+.0f})
- Жиры: {total_f:.0f} / {user['fat_goal']} ({total_f - user['fat_goal']:+.0f})
- Углеводы: {total_c:.0f} / {user['carbs_goal']} ({total_c - user['carbs_goal']:+.0f})

📝 НАПИШИ ОТЧЁТ В ТАКОМ ФОРМАТЕ:

🎯 ОЦЕНКА ДНЯ
[1-2 предложения: насколько хорошо день. Учти соответствие нормам и качество продуктов]

✅ ЧТО БЫЛО ХОРОШО
[2-3 конкретных пункта о том, что пользователь сделал правильно]

⚠️ ЧТО МОЖНО УЛУЧШИТЬ
[2-4 КОНКРЕТНЫХ профессиональных замечания. Указывай ИМЕННО на питательные ошибки: дефицит/избыток нутриентов, плохое распределение БЖУ по приёмам, недостаток клетчатки/витаминов, проблемы с гликемическим индексом, переизбыток быстрых углеводов вечером и т.д. Каждый пункт с объяснением ПОЧЕМУ это важно]

💡 РЕКОМЕНДАЦИИ НА ЗАВТРА
[3-4 конкретных совета с примерами продуктов и блюд. НЕ обобщения — конкретика. Например: «Добавь к завтраку 30г грецких орехов — это +6г омега-3 и устранит дефицит магния»]

🌟 ИНСАЙТ ДНЯ
[Один яркий профессиональный факт или совет, который пользователь возможно не знал, связанный с тем, что он ел сегодня]

ВАЖНО:
- Пиши КАК ЖИВОЙ ДИЕТОЛОГ — тёплый профессионал
- Без воды и общих фраз. Только конкретика.
- Используй данные пользователя (возраст, цель, вес) в рекомендациях
- Без markdown, без звёздочек
- Длина: 250-400 слов"""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
        return None

async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data['user_id']

    user_result = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not user_result.data:
        return

    user = user_result.data[0]
    if not user.get('daily_summary', True):
        return

    timezone_str = user.get('timezone', 'Europe/Kyiv')
    today = get_user_today(timezone_str)
    meals = supabase.table("meals").select("*").eq("user_id", user_id).eq("date", today).execute()

    summary = generate_daily_summary(user, meals.data)
    if not summary:
        return

    total_cal = sum(m['calories'] for m in meals.data) if meals.data else 0
    progress_bar = make_progress_bar(total_cal, user['calories_goal'])

    message = (
        f"🌙 ИТОГ ДНЯ\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"{progress_bar}\n"
        f"🔥 {total_cal} / {user['calories_goal']} ккал\n\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"{summary}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💤 Хорошего сна! Завтра новый день."
    )

    try:
        await context.bot.send_message(chat_id=int(user_id), text=message)
    except Exception as e:
        logger.error(f"Failed to send summary to {user_id}: {e}")

def schedule_daily_summary(application, user):
    user_id = user['user_id']
    timezone_str = user.get('timezone', 'Europe/Kyiv')
    job_name = f"daily_summary_{user_id}"

    # Удаляем старую задачу если была
    current_jobs = application.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()

    try:
        tz = pytz.timezone(timezone_str)
        # 23:59 каждый день в часовом поясе пользователя
        application.job_queue.run_daily(
            send_daily_summary,
            time=dtime(hour=23, minute=59, tzinfo=tz),
            data={'user_id': user_id},
            name=job_name
        )
        logger.info(f"Scheduled daily summary for {user_id} at 23:59 {timezone_str}")
    except Exception as e:
        logger.error(f"Failed to schedule for {user_id}: {e}")

# === ВОССТАНОВЛЕНИЕ ВСЕХ ЗАДАЧ ПОСЛЕ ПЕРЕЗАПУСКА ===
async def restore_all_jobs(application):
    try:
        users = supabase.table("users").select("*").execute()
        for user in users.data:
            if user.get('daily_summary', True):
                schedule_daily_summary(application, user)
        logger.info(f"Restored {len(users.data)} daily summary jobs")
    except Exception as e:
        logger.error(f"Failed to restore jobs: {e}")

async def cancel(update, context):
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# === POST INIT ===
async def post_init(application):
    await restore_all_jobs(application)

# === ЗАПУСК ===
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
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
