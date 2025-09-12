import asyncio  # Чтобы использовать async def и await, нужно чтобы код не продолжался пока не выполнится условие await, чтобы бот был многозадачным
import sys  # Для перенаправления сообщений от logging в терминал
import logging  # Для вывода сообщений о работе программы
import sqlite3  # База данных (таблица) в которой мы храним данные о пользователях и т.д.
import os
import datetime
import locale

from aiogram import Bot, Dispatcher, html, types  # Бот, HTML - разные шрифты в ТГ, Dispatcher - дирижёр, который принимает все события и направляет их в правильные функции
from os import getenv  # Чтобы безопасно хранить переменную TOKEN, задаётся через Powershell
from aiogram.filters import CommandStart, Command  # По сути готовая команда старта
from aiogram.types import Message  # По сути готовый объект с инфой о пользователе (ID, First_name, text и т.д.)
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# Настройка локали для дат
try:
    locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")  # Linux / Mac
except locale.Error:
    locale.setlocale(locale.LC_TIME, "Russian_Russia")  # Windows


class DzStates(StatesGroup):
    choosing_subject = State()
    writing_homework = State()


admin_1 = 1920672301  # Админ
admin_2 = 5251769398  # Админ
ADMINS = [admin_1, admin_2]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "UserInfo.db")
conn = sqlite3.connect(db_path)

TOKEN = getenv("BOT_TOKEN")  # Подключаем бота и проверка на наличие токена в Powershell
if not TOKEN:
    print("Не найден токен бота! Установите BOT_TOKEN в переменных окружения.")

bot = Bot(token=str(TOKEN))
dp = Dispatcher()  # Подключение "дирижёра"
cursor = conn.cursor()  # Нужно для запросов к таблице

# Создание таблиц
cursor.execute("""
    CREATE TABLE IF NOT EXISTS UserInfo (
        id INTEGER PRIMARY KEY,
        user_id INTEGER UNIQUE,
        user_name TEXT,
        user_option INT
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS Dz_Table (
        id INTEGER PRIMARY KEY,
        Алгебра TEXT,
        "Русский язык" TEXT,
        Геометрия TEXT,
        История TEXT,
        "Английский язык" TEXT,
        Физика TEXT,
        "Спецкурс по физике" TEXT,
        Биология TEXT,
        Химия TEXT,
        Информатика TEXT,
        ОБЗР TEXT,
        Физкулькута TEXT,
        "Разговор о важном" TEXT,
        Литература TEXT,
        География TEXT,
        Обществознание TEXT,
        ВиС TEXT
    )
""")
conn.commit()

subjects = [
    "Алгебра", "Русский язык", "Геометрия", "История",
    "Английский язык", "Физика", "Спецкурс по физике",
    "Биология", "Химия", "Информатика", "ОБЗР",
    "Физкулькута", "Разговор о важном", "Литература",
    "География", "Обществознание", "ВиС"
]

# Получаем список существующих колонок
cursor.execute("PRAGMA table_info(Dz_Table)")
existing_columns = [col[1] for col in cursor.fetchall()]

for subj in subjects:
    col_name = f"{subj}_date"
    if col_name not in existing_columns:
        cursor.execute(f"ALTER TABLE Dz_Table ADD COLUMN '{col_name}' TEXT")
conn.commit()


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

cursor.execute("""
    INSERT OR IGNORE INTO Dz_Table (
        id, Алгебра, "Русский язык", Геометрия, История, "Английский язык",
        Физика, "Спецкурс по физике", Биология, Химия, Информатика, ОБЗР,
        Физкулькута, "Разговор о важном", Литература, География,
        Обществознание, ВиС
    )
    VALUES (
        1, 'Ничего', 'Ничего', 'Ничего', 'Ничего', 'Ничего',
        'Ничего', 'Ничего', 'Ничего', 'Ничего', 'Ничего', 'Ничего',
        'Ничего', 'Ничего', 'Ничего', 'Ничего',
        'Ничего', 'Ничего'
    )
""")
conn.commit()

def get_full_schedule(user_id: int) -> str:
    cursor.execute("SELECT user_option FROM UserInfo WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return "❌ Сначала выбери вариант с помощью кнопки '🔄 Сменить вариант'"

    user_option = row[0]
    DZ = DZ_VAR1 if user_option == 1 else DZ_VAR2

    cursor.execute("SELECT * FROM Dz_Table WHERE id = 1")
    row = cursor.fetchone()
    if not row:
        return "❌ Домашка не найдена."

    col_names = [desc[0] for desc in cursor.description]
    homework_data = dict(zip(col_names, row))

    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]
    result = ""

    for i, day in enumerate(days):
        subjects = DZ[i]
        result += f"<b><u>{day} — Вариант {user_option}</u></b>\n\n"
        for j, subj in enumerate(subjects, start=1):
            if subj == "-":
                result += f"<b>{j}. ❌ Нет урока</b>\n"
            else:
                hw = homework_data.get(subj, "Ничего")
                date = homework_data.get(f"{subj}_date", "")
                result += f"<b>{j}. {html.quote(subj)} — {html.quote(hw)}</b>"
                if date:
                    result += f" [{date}]"
                result += "\n"
        result += "\n"

    return result


def get_homework_for_day(user_id: int, day_index: int) -> str:
    cursor.execute("SELECT user_option FROM UserInfo WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return "❌ Сначала выбери вариант с помощью кнопки '🔄 Сменить вариант'"

    user_option = row[0]
    DZ = DZ_VAR1 if user_option == 1 else DZ_VAR2

    cursor.execute("SELECT * FROM Dz_Table WHERE id = 1")
    row = cursor.fetchone()
    if not row:
        return "❌ Домашка не найдена."

    col_names = [desc[0] for desc in cursor.description]
    homework_data = dict(zip(col_names, row))

    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]
    subjects = DZ[day_index]
    schedule_text = f"<b><u>{days[day_index]} — Вариант {user_option}</u></b>\n\n"

    for i, subj in enumerate(subjects, start=1):
        if subj == "-":
            schedule_text += f"<b>{i}. ❌ Нет урока</b>\n"
        else:
            hw = homework_data.get(subj, "Ничего")
            date = homework_data.get(f"{subj}_date", "")
            schedule_text += f"<b>{i}. {html.quote(subj)} — {html.quote(hw)}</b>"
            if date:
                schedule_text += f" [{date}]"
            schedule_text += "\n"

    return schedule_text


def get_user_info(user: types.User | None):
    """Возвращает безопасный id и имя пользователя"""
    if user is None:
        return None, "Неизвестный"
    return user.id, user.first_name or "Неизвестный"


@dp.message(CommandStart())
async def command_start_handler(message: Message):
    cursor.execute(
        "INSERT OR IGNORE INTO UserInfo (user_id, user_name) VALUES (?, ?)",
        (message.from_user.id, message.from_user.first_name)
    )
    conn.commit()

    text = (
        "<b><u>Привет! 👋</u></b>\n"
        "<b>Это новая версия бота с расписанием дз\n"
        "Чтобы начать пользоваться ботом, нужно выбрать свой вариант группы\n"
        "Для этого выбери кнопку \"🔄 Сменить вариант\"</b>"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu(message.from_user.id))


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

    # Кнопка отмены для админов
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

    cursor.execute("PRAGMA table_info(Dz_Table)")
    valid_subjects = [col[1] for col in cursor.fetchall() if col[1] != "id"]
    if subject not in valid_subjects:
        await message.answer("⚠ Такого предмета нет. Выбери из списка.")
        return

    await state.update_data(subject=subject)
    await state.set_state(DzStates.writing_homework)
    await message.answer(
        f"✏ Запиши новое ДЗ по предмету: <b>{subject}</b>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(DzStates.writing_homework)
async def add_dz_save(message: Message, state: FSMContext):
    hw_text = message.text.strip()
    data = await state.get_data()
    subject = data.get("subject")

    cursor.execute(f'UPDATE Dz_Table SET "{subject}" = ? WHERE id = 1', (hw_text,))

    today = datetime.datetime.today()
    date_str = today.strftime("%A, %d %B")
    date_str = date_str[0].upper() + date_str[1:]
    cursor.execute(f'UPDATE Dz_Table SET "{subject}_date" = ? WHERE id = 1', (date_str,))

    conn.commit()

    await message.answer(
        f"✅ ДЗ по <b>{subject}</b> обновлено:\n<b>{hw_text}</b> [{date_str}]",
        parse_mode="HTML",
        reply_markup=get_main_menu(message.from_user.id)
    )
    await state.clear()


@dp.message()
async def handle_buttons(message: Message):
    user_id = message.from_user.id
    text = message.text

    # Дз на сегодня
    if text == "📅 Дз на сегодня":
        current_day = datetime.datetime.today().weekday()
        dz = get_homework_for_day(user_id, current_day)
        await message.answer(dz, parse_mode="HTML", reply_markup=get_main_menu(user_id))

    # Дз на завтра
    elif text == "📅 Дз на завтра":
        current_day = datetime.datetime.today().weekday()
        next_day = 0 if current_day >= 4 else current_day + 1
        dz = get_homework_for_day(user_id, next_day)
        await message.answer(dz, parse_mode="HTML", reply_markup=get_main_menu(user_id))

    # Сменить вариант
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

    # Полное расписание
    elif text == "📖 Полное расписание":
        full_schedule = get_full_schedule(user_id)
        await message.answer(full_schedule, parse_mode="HTML", reply_markup=get_main_menu(user_id))

    # Выбор варианта
    elif text in ["1", "2"]:
        cursor.execute("UPDATE UserInfo SET user_option = ? WHERE user_id = ?", (int(text), user_id))
        conn.commit()
        await message.answer(f"Ты выбрал вариант {text} ✅", reply_markup=get_main_menu(user_id))

    else:
        await message.answer("❓ Не понял. Выбирай через меню ниже:", reply_markup=get_main_menu(user_id))


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
