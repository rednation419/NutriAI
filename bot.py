import os
import logging
import json
from datetime import date, datetime
from io import BytesIO
from PIL import Image

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

# === ИНИЦИАЛИЗАЦИЯ ИИ И БАЗЫ ===
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-flash-latest')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# === СОСТОЯНИЯ РЕГИСТРАЦИИ ===
NAME, AGE, SEX, HEIGHT, WEIGHT, TARGET_WEIGHT, ACTIVITY = range(7)

# === РАСЧЁТ КАЛОРИЙ ПО ФОРМУЛЕ МИФФЛИНА-САН ЖЕОРА ===
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

# === КОМАНДА /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    result = supabase.table("users").select("*").eq("user_id", user_id).execute()

    if result.data:
        user = result.data[0]
        await update.message.reply_text(
            f"👋 С возвращением, {user['name']}!\n\n"
            f"📊 Твоя норма: {user['calories_goal']} ккал\n\n"
            f"🍽️ Отправь фото или описание еды — я посчитаю калории.\n\n"
            f"Команды:\n"
            f"/stats — статистика за сегодня\n"
            f"/reset — пересоздать профиль"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Привет! Я NutriAI — твой умный помощник по питанию.\n\n"
        "Я помогу тебе считать калории и БЖУ, анализируя фото и описания твоей еды с помощью ИИ.\n\n"
        "Сначала ответь на несколько вопросов, чтобы я рассчитал твою персональную норму.\n\n"
        "Как тебя зовут?"
    )
    return NAME

# === КОМАНДА /reset ===
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    supabase.table("users").delete().eq("user_id", user_id).execute()
    supabase.table("meals").delete().eq("user_id", user_id).execute()
    await update.message.reply_text(
        "🔄 Профиль удалён. Напиши /start чтобы начать заново.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

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
        "carbs_goal": carbs
    }).execute()

    await update.message.reply_text(
        f"✅ Отлично, {d['name']}! Профиль создан.\n\n"
        f"📊 Твоя дневная норма:\n"
        f"🔥 Калории: {calories} ккал\n"
        f"🥩 Белки: {protein} г\n"
        f"🧈 Жиры: {fat} г\n"
        f"🍞 Углеводы: {carbs} г\n\n"
        f"🍽️ Теперь отправляй фото или описание еды — я посчитаю!\n\n"
        f"Команды:\n/stats — статистика\n/reset — начать заново",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# === АНАЛИЗ ЕДЫ ЧЕРЕЗ GEMINI ===
def analyze_food_with_ai(description=None, image=None, clarifications=None):
    prompt = """Ты — профессиональный диетолог-эксперт с многолетним опытом. Твоя задача — максимально ТОЧНО оценить КБЖУ блюда. Точность важнее скорости.

🔍 ПРАВИЛО АНАЛИЗА:
Прежде чем дать финальную оценку, ВНИМАТЕЛЬНО проверь — есть ли в блюде элементы, которые СУЩЕСТВЕННО влияют на калорийность, но непонятны без уточнения?

⚠️ ОБЯЗАТЕЛЬНО задавай вопросы если видишь:
1. **Жареную еду** — спроси на каком масле жарили (растительное/сливочное/во фритюре) и сколько примерно
2. **Соусы, заправки, подливы непонятного состава** — спроси что это за соус (томатный/сливочный/майонезный/острый и т.д.)
3. **Овощи которые могут быть как сырыми, так и приготовленными** — спроси способ приготовления (варёные/тушёные/жареные/на пару)
4. **Рис, паста, каша необычного цвета** — спроси готовилось ли с маслом, бульоном, томатом, сливками
5. **Мясо/рыбу в панировке** — спроси из чего панировка и как жарилась
6. **Гарниры с заправками** — уточни заправлены ли маслом, соусом
7. **Размер порции** если непонятен — попроси указать примерный вес или сравнить с ладонью/кулаком
8. **Напитки** — спроси добавлялся ли сахар, молоко, сливки

❌ НЕ задавай вопросы про очевидное:
- Про обычный хлеб, простые фрукты целиком, очевидно сырые овощи
- Если пользователь уже сам всё подробно описал
- Если уточнения уже были даны в предыдущих сообщениях

📋 ФОРМАТ ОТВЕТА:

Если нужно уточнение — верни ТОЛЬКО JSON:
{
  "status": "need_info",
  "question": "Сформулируй ВСЕ вопросы одним сообщением, понятным языком, перечисляя их через нумерацию или абзацы. Например:\n\n1. На каком масле жарилась рыба?\n2. Что за красный соус сверху?\n3. Заправлена ли фасоль маслом?"
}

Если информации достаточно (или после получения уточнений) — верни ТОЛЬКО JSON:
{
  "status": "ok",
  "dish": "Название блюда с ключевыми деталями приготовления",
  "weight_g": 350,
  "calories": 580,
  "protein": 28,
  "fat": 22,
  "carbs": 60,
  "comment": "Краткое объяснение из чего складывается калорийность (1-2 предложения)"
}

ВАЖНО:
- Возвращай ТОЛЬКО JSON, без текста до или после
- Не используй markdown-обёртки (```json и ```)
- Будь точным в оценках — учитывай масло при жарке (+100-200 ккал на порцию), соусы (+50-150 ккал), сливки/майонез (+100+ ккал)"""

    try:
        full_prompt = prompt
        if clarifications:
            full_prompt += f"\n\n📌 УТОЧНЕНИЯ ОТ ПОЛЬЗОВАТЕЛЯ:\n{clarifications}\n\nТеперь у тебя есть достаточно информации — дай финальную оценку КБЖУ."

        if image:
            user_msg = description if description else "Проанализируй еду на фото"
            response = model.generate_content([full_prompt, image, user_msg])
        else:
            response = model.generate_content(f"{full_prompt}\n\nОписание еды от пользователя: {description}")

        text = response.text.strip()
        # Убираем markdown если есть
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
        await update.message.reply_text("Сначала зарегистрируйся: /start")
        return

    await update.message.reply_text("🔍 Анализирую фото...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    image = Image.open(BytesIO(bytes(file_bytes)))

    caption = update.message.caption or ""
    result = analyze_food_with_ai(description=caption, image=image)

    # Сохраняем фото в контекст на случай уточнений
    if result.get('status') == 'need_info':
        context.user_data['awaiting_clarification'] = True
        context.user_data['original_description'] = caption
        context.user_data['original_image'] = image
        context.user_data['clarifications'] = ''

    await process_ai_result(update, context, result, user_result.data[0])

# === ОБРАБОТКА ТЕКСТА ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_result = supabase.table("users").select("*").eq("user_id", user_id).execute()

    if not user_result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start")
        return

    text = update.message.text

    # Если ждём ответ на уточнение
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

        # Если ИИ задаёт ещё один вопрос — продолжаем диалог
        if result.get('status') == 'need_info':
            context.user_data['clarifications'] = new_clarifications
        else:
            # Если ответ финальный — очищаем контекст
            context.user_data['awaiting_clarification'] = False
            context.user_data['original_description'] = ''
            context.user_data['original_image'] = None
            context.user_data['clarifications'] = ''
    else:
        # Новый запрос
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
        await update.message.reply_text("❌ Ошибка анализа. Попробуй ещё раз.")
        return

    if result.get('status') == 'need_info':
        await update.message.reply_text(f"❓ {result['question']}")
        return

    if result.get('status') == 'ok':
        user_id = str(update.effective_user.id)
        today = date.today().isoformat()

        supabase.table("meals").insert({
            "user_id": user_id,
            "date": today,
            "description": result.get('dish', 'Блюдо'),
            "calories": result.get('calories', 0),
            "protein": result.get('protein', 0),
            "fat": result.get('fat', 0),
            "carbs": result.get('carbs', 0)
        }).execute()

        # Считаем итоги дня
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
            f"🍞 Углеводы: {total_c:.0f} / {user['carbs_goal']} (осталось {c_left:.0f})"
        )

# === ПРОГРЕСС-БАР ===
def make_progress_bar(current, goal, length=10):
    if goal == 0:
        return ""
    percent = min(current / goal, 1.0)
    filled = int(length * percent)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {int(percent * 100)}%"

# === КОМАНДА /stats ===
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_result = supabase.table("users").select("*").eq("user_id", user_id).execute()

    if not user_result.data:
        await update.message.reply_text("Сначала зарегистрируйся: /start")
        return

    user = user_result.data[0]
    today = date.today().isoformat()
    meals = supabase.table("meals").select("*").eq("user_id", user_id).eq("date", today).execute()

    if not meals.data:
        await update.message.reply_text(
            f"📊 Сегодня ты ещё ничего не ел.\n\n"
            f"Твоя норма: {user['calories_goal']} ккал"
        )
        return

    total_cal = sum(m['calories'] for m in meals.data)
    total_p = sum(m['protein'] for m in meals.data)
    total_f = sum(m['fat'] for m in meals.data)
    total_c = sum(m['carbs'] for m in meals.data)

    progress_bar = make_progress_bar(total_cal, user['calories_goal'])

    meals_list = "\n".join([f"• {m['description']} — {m['calories']} ккал" for m in meals.data])

    await update.message.reply_text(
        f"📊 СТАТИСТИКА ЗА СЕГОДНЯ\n\n"
        f"{progress_bar}\n\n"
        f"🔥 {total_cal} / {user['calories_goal']} ккал\n"
        f"🥩 Б: {total_p:.0f} / {user['protein_goal']} г\n"
        f"🧈 Ж: {total_f:.0f} / {user['fat_goal']} г\n"
        f"🍞 У: {total_c:.0f} / {user['carbs_goal']} г\n\n"
        f"🍽️ Приёмы пищи:\n{meals_list}"
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
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
