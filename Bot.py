import asyncio
import logging
import sys
import os
import datetime

from aiogram import Bot, Dispatcher, types, html
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from os import getenv
import asyncpg
from fastapi import FastAPI, Request

# -------------------------
# Настройки бота и базы
# -------------------------

TOKEN = getenv("BOT_TOKEN")
DATABASE_URL = getenv("DATABASE_URL")  # Установить в Render

if not TOKEN or not DATABASE_URL:
    print("❌ Не найден BOT_TOKEN или DATABASE_URL в переменных окружения")
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()
pool = None  # будет инициализирован позже

# -------------------------
# Состояния FSM
# -------------------------
class DzStates(StatesGroup):
    choosing_subject = State()
    writing_homework = State()

# -------------------------
# Админы
# -------------------------
ADMINS = [1920672301, 5251769398]

# -------------------------
# Предметы и варианты
# -------------------------
subjects = [
    "Алгебра", "Русский язык", "Геометрия", "История",
    "Английский язык", "Физика", "Спецкурс по физике",
    "Биология", "Химия", "Информатика", "ОБЗР",
    "Физкулькута", "Разговор о важном", "Литература",
    "География", "Обществознание", "ВиС", "БПЛА"
]

DZ_VAR1 = [
    ["Разговор о важном", "Физкулькута", "Химия", "Информатика", "Информатика", "Физика", "Физика"],
    ["Литература", "Литература", "Алгебра", "Алгебра", "Английский язык", "Английский язык", "ОБЗР"],
    ["Информатика", "Информатика", "История", "История", "Геометрия", "Геометрия", "Физкулькута"],
    ["Английский язык", "Геометрия", "Русский язык", "Русский язык", "ВиС", "Биология", "БПЛА"],
    ["Литература", "Алгебра", "Алгебра", "География", "Обществознание", "Обществознание", "Спецкурс по физике"]
]

DZ_VAR2 = [
    ["Разговор о важном", "Физкулькута", "Химия", "Английский язык", "Английский язык", "Физика", "Физика"],
    ["Литература", "Литература", "Алгебра", "Алгебра", "Информатика", "Информатика", "ОБЗР"],
    ["-", "Английский язык", "История", "История", "Геометрия", "Геометрия", "Физкулькута", "Информатика"],
    ["Информатика", "Геометрия", "Русский язык", "Русский язык", "ВиС", "Биология", "БПЛА"],
    ["Литература", "Алгебра", "Алгебра", "География", "Обществознание", "Обществознание", "Спецкурс по физике"]
]

# -------------------------
# Меню
# -------------------------
def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📅 Дз на сегодня")],
        [KeyboardButton(text="📅 Дз на завтра")],
        [KeyboardButton(text="📖 Полное расписание")],
        [KeyboardButton(text="🔄 Сменить вариант")]
    ]
    if user_id in ADMINS:
        buttons.append([KeyboardButton(text="Добавить ДЗ")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# -------------------------
# Подключение к базе
# -------------------------
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        # Таблицы
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS UserInfo (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE,
            user_name TEXT,
            user_option INT
        )
        """)
        # Таблица ДЗ
        cols = ', '.join([f'"{subj}" TEXT, "{subj}_date" TEXT' for subj in subjects])
        await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS Dz_Table (
            id SERIAL PRIMARY KEY,
            {cols}
        )
        """)
        # Добавляем одну строку, если нет
        exists = await conn.fetchval("SELECT COUNT(*) FROM Dz_Table")
        if exists == 0:
            cols_names = ', '.join([f'"{subj}"' for subj in subjects])
            values = ', '.join(["'Ничего'" for _ in subjects])
            await conn.execute(f'INSERT INTO Dz_Table ({cols_names}) VALUES ({values})')

# -------------------------
# FastAPI сервер для webhook
# -------------------------
app = FastAPI()
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"https://firsttelegrambothomework.onrender.com{WEBHOOK_PATH}"

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}

async def on_startup():
    await init_db()
    await bot.set_webhook(WEBHOOK_URL)
    print("Webhook установлен:", WEBHOOK_URL)

# -------------------------
# Хелперы
# -------------------------
@dp.message(CommandStart())
async def command_start_handler(message: Message):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO UserInfo (user_id, user_name) VALUES ($1, $2) "
            "ON CONFLICT (user_id) DO NOTHING",
            message.from_user.id, message.from_user.first_name
        )

    text = (
        "<b><u>Привет! 👋</u></b>\n"
        "<b>Это новая версия бота с расписанием дз.\n"
        "Чтобы начать пользоваться ботом, нужно выбрать свой вариант группы.\n"
        "Для этого выбери кнопку \"🔄 Сменить вариант\"</b>"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu(message.from_user.id))

async def get_user_option(user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_option FROM UserInfo WHERE user_id=$1", user_id)
        return row["user_option"] if row else None

async def get_homework_for_day(user_id: int, day_index: int):
    user_option = await get_user_option(user_id)
    if not user_option:
        return "❌ Сначала выбери вариант через кнопку '🔄 Сменить вариант'"
    DZ = DZ_VAR1 if user_option == 1 else DZ_VAR2
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM Dz_Table WHERE id=1")
    result = f"<b><u>{['Понедельник','Вторник','Среда','Четверг','Пятница'][day_index]} — Вариант {user_option}</u></b>\n\n"
    for i, subj in enumerate(DZ[day_index], start=1):
        if subj == "-":
            result += f"<b>{i}. ❌ Нет урока</b>\n"
        else:
            hw = row[subj]
            date = row[f"{subj}_date"]
            result += f"<b>{i}. {html.quote(subj)} — {html.quote(hw)}</b>"
            if date:
                result += f" [{date}]"
            result += "\n"
    return result

async def get_full_schedule(user_id: int):
    user_option = await get_user_option(user_id)
    if not user_option:
        return "❌ Сначала выбери вариант через кнопку '🔄 Сменить вариант'"
    DZ = DZ_VAR1 if user_option == 1 else DZ_VAR2
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM Dz_Table WHERE id=1")
    result = ""
    days = ["Понедельник","Вторник","Среда","Четверг","Пятница"]
    for i, day in enumerate(days):
        subjects_day = DZ[i]
        result += f"<b><u>{day} — Вариант {user_option}</u></b>\n\n"
        for j, subj in enumerate(subjects_day, start=1):
            if subj == "-":
                result += f"<b>{j}. ❌ Нет урока</b>\n"
            else:
                hw = row[subj]
                date = row[f"{subj}_date"]
                result += f"<b>{j}. {html.quote(subj)} — {html.quote(hw)}</b>"
                if date:
                    result += f" [{date}]"
                result += "\n"
        result += "\n"
    return result

# -------------------------
# Добавление ДЗ
# -------------------------
@dp.message(lambda m: m.text == "Добавить ДЗ")
async def add_dz_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ У тебя нет прав добавлять дз.")
        return

    keyboard_rows = []
    row = []
    for i, subj in enumerate(subjects, start=1):
        row.append(KeyboardButton(text=subj))
        if i % 2 == 0:
            keyboard_rows.append(row)
            row = []
    if row:
        keyboard_rows.append(row)
    keyboard_rows.append([KeyboardButton(text="Отмена")])
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard_rows, resize_keyboard=True)
    await state.set_state(DzStates.choosing_subject)
    await message.answer("📚 Выбери предмет:", reply_markup=keyboard)

@dp.message(DzStates.choosing_subject)
async def add_dz_subject(message: Message, state: FSMContext):
    if message.text.strip() == "Отмена":
        await state.clear()
        await message.answer("❌ Добавление ДЗ отменено.", reply_markup=get_main_menu(message.from_user.id))
        return
    subject = message.text.strip()
    if subject not in subjects:
        await message.answer("⚠ Такого предмета нет. Выбери из списка.")
        return
    await state.update_data(subject=subject)
    await state.set_state(DzStates.writing_homework)
    await message.answer(f"✏ Запиши новое ДЗ по предмету: <b>{subject}</b>",
                         parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

@dp.message(DzStates.writing_homework)
async def add_dz_save(message: Message, state: FSMContext):
    hw_text = message.text.strip()
    data = await state.get_data()
    subject = data.get("subject")
    today = datetime.datetime.today()
    RUS_DAYS = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
    RUS_MONTHS = ["Января","Февраля","Марта","Апреля","Мая","Июня",
                  "Июля","Августа","Сентября","Октября","Ноября","Декабря"]
    date_str = f"{RUS_DAYS[today.weekday()]}, {today.day} {RUS_MONTHS[today.month-1]}"
    async with pool.acquire() as conn:
        await conn.execute(f'UPDATE Dz_Table SET "{subject}"=$1, "{subject}_date"=$2 WHERE id=1',
                           hw_text, date_str)
    await message.answer(f"✅ ДЗ по <b>{subject}</b> обновлено:\n<b>{hw_text}</b> [{date_str}]",
                         parse_mode="HTML", reply_markup=get_main_menu(message.from_user.id))
    await state.clear()

# -------------------------
# Основные кнопки
# -------------------------
@dp.message()
async def handle_buttons(message: Message):
    user_id = message.from_user.id
    text = message.text

    if text == "📅 Дз на сегодня":
        current_day = datetime.datetime.today().weekday()
        if current_day > 4: current_day = 0
        dz = await get_homework_for_day(user_id, current_day)
        await message.answer(dz, parse_mode="HTML", reply_markup=get_main_menu(user_id))

    elif text == "📅 Дз на завтра":
        current_day = datetime.datetime.today().weekday()
        next_day = 0 if current_day >= 4 else current_day + 1
        dz = await get_homework_for_day(user_id, next_day)
        await message.answer(dz, parse_mode="HTML", reply_markup=get_main_menu(user_id))

    elif text == "📖 Полное расписание":
        full_schedule = await get_full_schedule(user_id)
        await message.answer(full_schedule, parse_mode="HTML", reply_markup=get_main_menu(user_id))

    elif text == "🔄 Сменить вариант":
        await message.answer("<b>Выбери свой вариант:</b>", parse_mode="HTML")

        variant1 = ["Зизевский Пётр", "Каримов Артур", "Старостин Матвей", "Чернов Степан", "И т.д."]
        variant2 = ["Лазарев Данила", "Ананьев Григорий", "Гарипов Руслан", "Глотов Всеволод", "И т.д."]

        max_len = max(max(len(name) for name in variant1), max(len(name) for name in variant2)) + 4
        lines = []
        for i in range(max(len(variant1), len(variant2))):
            name1 = variant1[i] if i < len(variant1) else ""
            name2 = variant2[i] if i < len(variant2) else ""
            lines.append(f"{name1.ljust(max_len)}{name2}")

        text_variants = "<pre>Вариант 1:".ljust(max_len) + "Вариант 2:\n"
        text_variants += "\n".join(lines)
        text_variants += "</pre>"

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="1"), KeyboardButton(text="2")]],
            resize_keyboard=True
        )

        await message.answer(text_variants, parse_mode="HTML", reply_markup=keyboard)

    elif text in ["1","2"]:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE UserInfo SET user_option=$1 WHERE user_id=$2", int(text), user_id)
        await message.answer(f"Ты выбрал вариант {text} ✅", reply_markup=get_main_menu(user_id))

    else:
        await message.answer("❓ Не понял. Используй меню ниже:", reply_markup=get_main_menu(user_id))

# -------------------------
# Старт
# -------------------------
if __name__ == "__main__":
    import uvicorn
    # Сначала инициализируем базу и ставим webhook
    asyncio.run(on_startup())
    # Запускаем FastAPI
    uvicorn.run(app, host="0.0.0.0", port=10000)