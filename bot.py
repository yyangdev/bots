import asyncio
import logging
import sqlite3
import secrets
import os
from pathlib import Path
from datetime import datetime, time, timedelta
from typing import List
import pytz
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
# [RENDER] Импортируем RedisStorage и redis
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio.client import Redis

# --- [RENDER] Конфигурация из переменных окружения ---
# ВАЖНО: Никогда не храните токен в коде!
TOKEN = os.getenv("BOT_TOKEN")
# Преобразуем строку из переменных окружения в список
ADMIN_USERNAMES = os.getenv("ADMIN_USERNAMES", "yesbeers,yyangpython").split(',')
MANAGER_CONTACT = os.getenv("MANAGER_CONTACT", "@managersrich")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@eweton")
REFERRAL_BONUS = float(os.getenv("REFERRAL_BONUS", 0.2))

# [RENDER] Путь к базе данных на персистентном диске Render
# Render монтирует диск в /var/data/, поэтому мы будем хранить БД там.
# Если переменная окружения DATA_DIR не установлена (локальный запуск), используем текущую папку.
DATA_DIR = Path(os.getenv("DATA_DIR", "."))
DATABASE_PATH = DATA_DIR / "shop_bot.db"

# [RENDER] URL для подключения к Redis из переменных окружения
REDIS_URL = os.getenv("REDIS_URL")

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info(f"Путь к базе данных: {DATABASE_PATH}")
logger.info(f"Администраторы: {ADMIN_USERNAMES}")
if not TOKEN:
    logger.critical("Не найден BOT_TOKEN! Завершение работы.")
    exit()
if not REDIS_URL:
    logger.critical("Не найден REDIS_URL! FSM не будет работать корректно. Завершение работы.")
    exit()


# --- Инициализация бота и диспетчера ---
# [RENDER] Используем RedisStorage вместо MemoryStorage
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
storage = RedisStorage(redis=redis_client)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)


# --- Классы и функции (остаются без изменений, кроме пути к БД) ---

class AdminStates(StatesGroup):
    select_category = State()
    select_item = State()
    enter_new_price = State()
    enter_new_name = State()

class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        # [RENDER] Убедимся, что папка для БД существует
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self):
        # check_same_thread=False важно для асинхронного окружения
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        balance REAL DEFAULT 0,
                        referral_code TEXT UNIQUE,
                        referrer_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category_id INTEGER,
                        name TEXT NOT NULL,
                        price INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (category_id) REFERENCES categories (id)
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS referrals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        referrer_id INTEGER,
                        referred_id INTEGER,
                        bonus_paid BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(referred_id)
                    )
                ''')
                
                initial_categories = [
                    "GTA 5 RP", "Standoff 2", "Brawl Stars", "Clash Royale", 
                    "Roblox", "CS 2", "Pubg Mobile", "PUBG (PC/Console)", 
                    "Discord", "YouTube", "TikTok", "Telegram", "NFT Подарки"
                ]
                
                initial_items = {
                    "GTA 5 RP": ["Аккаунты", "Игровая валюта", "Предметы", "Боты для работ"],
                    "Standoff 2": ["Голда", "Аккаунт", "Донат", "Буст", "Кланы", "Софт"],
                    "Brawl Stars": ["Гемы", "Аккаунты", "Brawl Pass", "Буст кубков-рангов"],
                    "Clash Royale": ["Гемы", "Аккаунты", "Pass Royale", "Предметы"],
                    "Roblox": ["Аккаунты", "Робоксы", "Донат", "Premium", "Скины и валюта"],
                    "CS 2": ["Прайм", "Аккаунт", "Буст", "Faceit Premium", "Скины и кейсы"],
                    "Pubg Mobile": ["Аккаунты", "UC", "Донат", "Буст", "Metro Royale"],
                    "PUBG (PC/Console)": ["Аккаунты", "G-Coins", "Предметы", "Twitch Drops"],
                    "Discord": ["Серверы", "Украшения", "Nitro", "Услуги", "Буст сервера"],
                    "YouTube": ["Услуги", "Каналы", "Premium"],
                    "TikTok": ["Аккаунты", "Монеты"],
                    "Telegram": ["21 звезда", "50 звезд", "100 звезд", "Telegram Premium 1 месяц", 
                               "Telegram Premium 3 месяца", "Telegram Premium 6 месяцев", "Telegram Premium 12 месяцев"],
                    "NFT Подарки": ["NFT Подарки"]
                }
                
                for category_name in initial_categories:
                    cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (category_name,))
                
                for category_name, items in initial_items.items():
                    cursor.execute('SELECT id FROM categories WHERE name = ?', (category_name,))
                    category_result = cursor.fetchone()
                    if category_result:
                        category_id = category_result[0]
                        for item_name in items:
                            cursor.execute(
                                'INSERT OR IGNORE INTO items (category_id, name, price) VALUES (?, ?, ?)',
                                (category_id, item_name, 0)
                            )
                conn.commit()
                logger.info("База данных успешно инициализирована или уже существует.")
                
        except Exception as e:
            logger.error(f"Ошибка инициализации базы данных: {e}", exc_info=True)

    def add_user(self, user_id: int, username: str, first_name: str, last_name: str = "", referrer_id: int = None):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
                existing_user = cursor.fetchone()
                
                if not existing_user:
                    referral_code = secrets.token_hex(4).upper()
                    cursor.execute(
                        'INSERT INTO users (user_id, username, first_name, last_name, referral_code, referrer_id) VALUES (?, ?, ?, ?, ?, ?)',
                        (user_id, username, first_name, last_name, referral_code, referrer_id)
                    )
                    conn.commit()
                    logger.info(f"Добавлен новый пользователь: {user_id} {username}")
                    
                    if referrer_id:
                        logger.info(f"Пользователь {user_id} пришел по приглашению от {referrer_id}. Начисляем бонус.")
                        self._add_referral_bonus(referrer_id, user_id, conn) # Передаем соединение
                else:
                    cursor.execute(
                        'UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE user_id = ?',
                        (username, first_name, last_name, user_id)
                    )
                    conn.commit()
                    logger.info(f"Обновлен существующий пользователь: {user_id}")
                    
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя {user_id}: {e}", exc_info=True)

    # [RENDER] Небольшая оптимизация, чтобы не открывать новое соединение внутри другого
    def _add_referral_bonus(self, referrer_id: int, referred_id: int, conn: sqlite3.Connection):
        try:
            cursor = conn.cursor()
            
            cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (referrer_id,))
            referrer_exists = cursor.fetchone()
            
            if not referrer_exists:
                logger.error(f"Реферер {referrer_id} не найден в базе")
                return
                
            cursor.execute('SELECT id FROM referrals WHERE referred_id = ?', (referred_id,))
            existing_referral = cursor.fetchone()
            
            if existing_referral:
                logger.info(f"Бонус для {referred_id} уже был начислен ранее.")
                return
                
            cursor.execute(
                'INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)',
                (referrer_id, referred_id)
            )
            
            cursor.execute(
                'UPDATE users SET balance = balance + ? WHERE user_id = ?',
                (REFERRAL_BONUS, referrer_id)
            )
            
            logger.info(f"Бонус {REFERRAL_BONUS} руб. начислен пользователю {referrer_id} за приглашение {referred_id}")
            # conn.commit() будет вызван в родительской функции add_user
            
        except Exception as e:
            logger.error(f"Ошибка при начислении реферального бонуса: {e}", exc_info=True)
            conn.rollback() # Откатываем изменения в случае ошибки
    
    # ... Остальные методы класса Database остаются без изменений ...
    # (get_user_balance, get_referral_code, get_referral_stats, etc.)
    # Я их удалил для краткости, но в вашем файле они должны остаться.
    def get_user_balance(self, user_id: int) -> float:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0.0

    def get_referral_code(self, user_id: int) -> str:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result else None

    def get_referral_stats(self, user_id: int) -> tuple:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
            total_referrals = cursor.fetchone()[0]
            total_earned = total_referrals * REFERRAL_BONUS
            return total_referrals, total_earned

    def get_all_users(self) -> List[int]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users')
            users = [row[0] for row in cursor.fetchall()]
            logger.info(f"Найдено пользователей в базе: {len(users)}")
            return users

    def get_users_count(self) -> int:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM users')
                result = cursor.fetchone()
                count = result[0] if result else 0
                return count
        except Exception as e:
            logger.error(f"Ошибка получения количества пользователей: {e}")
            return 0

    def get_categories(self) -> List[tuple]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name FROM categories ORDER BY name')
            return cursor.fetchall()

    def get_items_by_category(self, category_id: int) -> List[tuple]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, price FROM items WHERE category_id = ? ORDER BY name', (category_id,))
            return cursor.fetchall()

    def get_category_by_name(self, category_name: str) -> tuple:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name FROM categories WHERE name = ?', (category_name,))
            return cursor.fetchone()

    def get_item_by_id(self, item_id: int) -> tuple:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT i.id, i.name, i.price, c.name FROM items i JOIN categories c ON i.category_id = c.id WHERE i.id = ?', (item_id,))
            return cursor.fetchone()

    def update_item_price(self, item_id: int, new_price: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE items SET price = ? WHERE id = ?', (new_price, item_id))
            conn.commit()

    def update_item_name(self, item_id: int, new_name: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE items SET name = ? WHERE id = ?', (new_name, item_id))
            conn.commit()

# Создаем экземпляр базы данных
db = Database(DATABASE_PATH)

# --- Весь остальной код обработчиков остается без изменений ---
# ... (check_subscription, is_admin, все get_*_keyboard, хендлеры сообщений и команд) ...
# Я также удалил их для краткости, в вашем файле они должны быть.
async def check_subscription(user_id: int) -> bool:
    try:
        # Если канал не указан, считаем, что подписка не нужна
        if not REQUIRED_CHANNEL or REQUIRED_CHANNEL == "@":
            return True
        chat_member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception:
        # Если бот не может проверить (например, не админ в канале), разрешаем доступ
        logger.warning(f"Не удалось проверить подписку для {user_id} на канал {REQUIRED_CHANNEL}. Доступ разрешен.")
        return True

def is_admin(username: str) -> bool:
    if not username:
        return False
    clean_username = username.lstrip('@')
    return clean_username in ADMIN_USERNAMES

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Каталог")],
            [KeyboardButton(text="Реферальная система"), KeyboardButton(text="Баланс")],
            [KeyboardButton(text="Помощь"), KeyboardButton(text="Контакты")]
        ],
        resize_keyboard=True
    )

def get_catalog_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="GTA 5 RP"), KeyboardButton(text="Standoff 2")],
            [KeyboardButton(text="Brawl Stars"), KeyboardButton(text="Clash Royale")],
            [KeyboardButton(text="Roblox"), KeyboardButton(text="CS 2")],
            [KeyboardButton(text="Pubg Mobile"), KeyboardButton(text="PUBG (PC/Console)")],
            [KeyboardButton(text="Discord"), KeyboardButton(text="YouTube")],
            [KeyboardButton(text="TikTok"), KeyboardButton(text="Telegram")],
            [KeyboardButton(text="NFT Подарки"), KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

# ... (и так далее, все ваши функции клавиатур)
def get_back_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True)

def get_telegram_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="21 звезда"), KeyboardButton(text="50 звезд")],
            [KeyboardButton(text="100 звезд")],
            [KeyboardButton(text="Premium 1 месяц"), KeyboardButton(text="Premium 3 месяца")],
            [KeyboardButton(text="Premium 6 месяцев"), KeyboardButton(text="Premium 12 месяцев")],
            [KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

# ... (все хендлеры, я их пропущу)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Проверяем подписку ДО добавления пользователя и начисления бонусов
    if not await check_subscription(message.from_user.id):
        kb = InlineKeyboardBuilder()
        kb.add(InlineKeyboardButton(text="Подписаться", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}"))
        kb.add(InlineKeyboardButton(text="Проверить", callback_data="check_sub"))
        await message.answer(
            f"Для использования бота, пожалуйста, подпишитесь на наш канал. "
            f"После подписки нажмите кнопку 'Проверить'.",
            reply_markup=kb.as_markup()
        )
        return

    referrer_id = None
    args = message.text.split()
    if len(args) > 1:
        referral_code = args[1]
        logger.info(f"Обнаружен реферальный код: {referral_code} от пользователя {message.from_user.id}")
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
            result = cursor.fetchone()
            if result and result[0] != message.from_user.id:
                referrer_id = result[0]
                logger.info(f"Реферал найден: {referrer_id} пригласил {message.from_user.id}")
            else:
                logger.warning(f"Реферальный код {referral_code} не найден или пользователь ссылается на себя.")
    
    db.add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name or "",
        referrer_id
    )
    
    await message.answer("Добро пожаловать! Выберите действие:", reply_markup=get_main_keyboard())


@dp.callback_query(F.data == "check_sub")
async def handle_check_sub(callback: types.CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.message.delete() # Удаляем сообщение с кнопками подписки
        await cmd_start(callback.message) # Запускаем логику /start заново
    else:
        await callback.answer("Вы все еще не подписаны. Пожалуйста, подпишитесь и попробуйте снова.", show_alert=True)


# ... (все остальные хендлеры)
@dp.message(F.text == "Каталог")
async def show_catalog(message: types.Message):
    if not await check_subscription(message.from_user.id):
        await message.answer("Проверьте подписку!", reply_markup=get_main_keyboard())
        return
    await message.answer("Выберите категорию:", reply_markup=get_catalog_keyboard())

# ... и так далее. Оставляем все ваши хендлеры как есть.
# Я их пропустил, чтобы не дублировать 500 строк кода.
# Просто скопируйте их сюда из вашего оригинального файла.
@dp.message(F.text == "Назад")
async def back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_keyboard())

# --- Основная функция запуска ---
async def main():
    logger.info("Бот запускается...")
    # Убедимся, что папка для данных существует, если мы на Render
    if 'RENDER' in os.environ:
        DATA_DIR.mkdir(exist_ok=True)

    users_count = db.get_users_count()
    logger.info(f"Пользователей в базе при запуске: {users_count}")
    
    # Удаляем вебхук, если он был установлен ранее
    await bot.delete_webhook(drop_pending_updates=True)
    # Запускаем поллинг
    await dp.start_polling(bot)


if __name__ == "__main__":
