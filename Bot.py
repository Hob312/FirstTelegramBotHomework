import asyncio
import logging
import datetime
import httpx
import ssl as _ssl

from aiogram import Bot, Dispatcher, types, html
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.types import Update
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from os import getenv
import asyncpg
from fastapi import FastAPI, Request

# -------------------------
# Настройки
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = getenv("BOT_TOKEN")
DATABASE_URL = getenv("DATABASE_URL")

def _normalize_base_url(u: str) -> str:
    return u[:-1] if u and u.endswith("/") else u

BASE_URL = getenv("BASE_URL") or getenv("RENDER_EXTERNAL_URL")
BASE_URL = _normalize_base_url(BASE_URL)

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

if not TOKEN:
    logging.error("❌ Не задан BOT_TOKEN")
    raise SystemExit(1)

if not DATABASE_URL:
    logging.error("❌ Не задан DATABASE_URL")
    raise SystemExit(1)

# Если по какой-то причине Render не выставил RENDER_EXTERNAL_URL (редко, но вдруг локально),
# тогда просим указать BASE_URL вручную.
if not BASE_URL:
    logging.error("❌ Не найден ни BASE_URL, ни RENDER_EXTERNAL_URL. Укажи BASE_URL вручную, например https://<your-service>.onrender.com")
    raise SystemExit(1)

# -------------------------
# Bot / Dispatcher / Storage
# -------------------------
bot = None                # создадим в startup
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

pool = None  # будет инициализирован в init_db

# -------------------------
# FSM
# -------------------------
class DzStates(StatesGroup):
    choosing_subject = State()
    writing_homework = State()

ADMINS = [1920672301, 5251769398]

app = FastAPI()

# -------------------------
# Список предметов
# -------------------------
subjects = [
    "Алгебра", "Русский язык", "Геометрия", "История",
    "Английский язык", "Физика", "Спецкурс по физике",
    "Биология", "Химия", "Информатика", "ОБЗР",
    "Физкультура", "Разговор о важном", "Литература",
    "География", "Обществознание", "ВиС", "БПЛА"
]

DZ_VAR1 = [
    ["-", "Физкультура", "Химия", "Информатика", "Информатика", "Физика", "Физика", "Разговор о важном"],
    ["Литература", "ОБЗР", "Алгебра", "Алгебра", "Английский язык", "Английский язык", "Литература"],
    ["Информатика", "Информатика", "История", "История", "Геометрия", "Геометрия", "Физкультура"],
    ["Английский язык", "Геометрия", "Русский язык", "Русский язык", "ВиС", "Биология", "БПЛА"],
    ["Литература", "Алгебра", "Алгебра", "География", "Обществознание", "Спецкурс по физике", "Обществознание"]
]

DZ_VAR2 = [
    ["-", "Физкультура", "Химия", "Английский язык", "Английский язык", "Физика", "Физика", "Разговор о важном"],
    ["Литература", "ОБЗР", "Алгебра", "Алгебра", "Информатика", "Информатика", "Литература"],
    ["-", "Английский язык", "История", "История", "Геометрия", "Геометрия", "Физкультура", "Информатика"],
    ["Информатика", "Геометрия", "Русский язык", "Русский язык", "ВиС", "Биология", "БПЛА"],
    ["Литература", "Алгебра", "Алгебра", "География", "Обществознание", "Спецкурс по физике", "Обществознание"]
]

# -------------------------
# Меню
# -------------------------
def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📅 Дз на сегодня")],
        [KeyboardButton(text="📅 Дз на завтра")],
        [KeyboardButton(text="📖 Полное расписание")],
        [KeyboardButton(text="🔄 Сменить вариант группы")]
    ]
    if user_id in ADMINS:
        buttons.append([KeyboardButton(text="Добавить ДЗ")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# -------------------------
# Инициализация БД
# -------------------------
async def init_db():
    global pool
    # Нормализуем DSN для asyncpg
    dsn = DATABASE_URL.replace("postgres://", "postgresql://")

    # 1) Пытаемся подключиться с проверкой сертификата (рекомендуемый вариант)
    verified_ctx = _ssl.create_default_context()
    try:
        pool = await asyncpg.create_pool(dsn, ssl=verified_ctx)
    except _ssl.SSLCertVerificationError as e:
        logger.warning("SSL verification failed (self-signed cert). Falling back to UNVERIFIED SSL context. "
                       "Это небезопасно в проде — по возможности настроить доверенный сертификат или sslmode=require.")
        # 2) Фоллбэк: отключаем проверку сертификата/host
        unverified_ctx = _ssl.create_default_context()
        unverified_ctx.check_hostname = False
        unverified_ctx.verify_mode = _ssl.CERT_NONE
        pool = await asyncpg.create_pool(dsn, ssl=unverified_ctx)

    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS UserInfo (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE,
            user_name TEXT,
            user_option INT
        )
        """)
        cols = ', '.join([f'"{subj}" TEXT, "{subj}_date" TEXT' for subj in subjects])
        await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS Dz_Table (
            id SERIAL PRIMARY KEY,
            {cols}
        )
        """)
        exists = await conn.fetchval("SELECT COUNT(*) FROM Dz_Table")
        if exists == 0:
            cols_names = ', '.join([f'"{subj}"' for subj in subjects])
            values = ', '.join(["'Ничего'" for _ in subjects])
            await conn.execute(f'INSERT INTO Dz_Table ({cols_names}) VALUES ({values})')

async def init_db_with_retry(retries: int = 5, delay: int = 3):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"DB init attempt {attempt}/{retries} ...")
            await init_db()
            logger.info("DB init OK")
            return
        except Exception as e:
            last_err = e
            logger.error(f"DB init failed: {e!r}. Retry in {delay}s")
            await asyncio.sleep(delay)
    # если так и не поднялись — пробрасываем, чтобы упасть с понятной причиной
    raise last_err

# -------------------------
# Health-check (чтобы не было 404 при keep-alive)
# -------------------------
@app.get("/")
async def root():
    return {"ok": True}

# -------------------------
# Keep-alive
# -------------------------
KEEP_ALIVE_URL = BASE_URL  # ping root health-check

async def keep_awake():
    while True:
        try:
            async with httpx.AsyncClient() as client:
                await client.get(KEEP_ALIVE_URL, timeout=10)
            logger.info("Keep-alive ping выполнен")
        except Exception as e:
            logger.error(f"Ошибка keep-alive: {e}")
        await asyncio.sleep(600)  # 10 минут

# -------------------------
# Webhook endpoint
# -------------------------
@app.post("/webhook")
async def telegram_webhook(request: Request):
    if bot is None:
        logger.error("Bot not initialized yet, received update")
        return {"ok": False}
    try:
        raw = await request.json()
        update = Update.model_validate(raw)  # строгая валидация
        asyncio.create_task(dp.feed_webhook_update(bot, update))
        logger.info("Update OK: %s", raw.get("update_id"))
        return {"ok": True}
    except Exception as e:
        # Чтобы не терять ошибки вообще
        logger.exception(f"Webhook error: {e}")
        return {"ok": False}

# -------------------------
# Startup / Shutdown
# -------------------------
@app.on_event("startup")
async def on_startup():
    global bot
    logger.info("Starting up: init DB, bot, webhook, keep-alive")
    # init db
    await init_db_with_retry()
    # create bot (so its session binds to current loop)
    bot = Bot(token=TOKEN)
    # set webhook
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")
    # start keep-alive background task
    asyncio.create_task(keep_awake())

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down: closing resources")
    if pool:
        await pool.close()
    if bot:
        try:
            await bot.delete_webhook()
        except Exception as e:
            logger.error(f"Error deleting webhook: {e}")
        try:
            await bot.session.close()
        except Exception:
            try:
                await bot.close()
            except Exception:
                pass
    try:
        await storage.close()
    except Exception:
        pass

@dp.message(CommandStart())
async def command_start_handler(message: Message):
    if pool is None:
        raise RuntimeError("Пул базы данных ещё не инициализирован")
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
        "Для этого выбери кнопку \" Сменить вариант группы\"</b>"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu(message.from_user.id))

async def get_user_option(user_id: int):
    if pool is None:
        raise RuntimeError("Пул базы данных ещё не инициализирован")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_option FROM UserInfo WHERE user_id=$1", user_id
        )
        return row["user_option"] if row else None

async def get_homework_for_day(user_id: int, day_index: int):
    if pool is None:
        raise RuntimeError("Пул базы данных ещё не инициализирован")
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
    if pool is None:
        raise RuntimeError("Пул базы данных ещё не инициализирован")
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
    if pool is None:
        raise RuntimeError("Пул базы данных ещё не инициализирован")
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

    elif text == "🔄 Сменить вариант группы":
        await message.answer("<b>Выбери свой вариант группы:</b>", parse_mode="HTML")

        variant1 = ["Зизевский Пётр", "Каримов Артур", "Старостин Матвей", "Чернов Степан", "И т.д."]
        variant2 = ["Лазарев Данила", "Ананьев Григорий", "Гарипов Руслан", "Глотов Всеволод", "И т.д."]

        max_len = max(max(len(name) for name in variant1), max(len(name) for name in variant2)) + 4
        lines = []

        # Заголовки
        header = f"{'Вариант 1:'.ljust(max_len)}Вариант 2:"
        lines.append(header)

        # Сами варианты
        for i in range(max(len(variant1), len(variant2))):
            name1 = variant1[i] if i < len(variant1) else ""
            name2 = variant2[i] if i < len(variant2) else ""
            lines.append(f"{name1.ljust(max_len)}{name2}")

        # Оборачиваем всё в <pre>
        text_variants = "<pre>" + "\n".join(lines) + "</pre>"

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="1"), KeyboardButton(text="2")]],
            resize_keyboard=True
        )

        await message.answer(text_variants, parse_mode="HTML", reply_markup=keyboard)

    elif text in ["1","2"]:
        if pool is None:
            raise RuntimeError("Пул базы данных ещё не инициализирован")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE UserInfo SET user_option=$1 WHERE user_id=$2", int(text), user_id
            )
        await message.answer(f"Ты выбрал вариант {text} ✅", reply_markup=get_main_menu(user_id))


    else:
        await message.answer("❓ Не понял. Используй меню ниже:", reply_markup=get_main_menu(user_id))