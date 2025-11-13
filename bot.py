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
from aiogram.fsm.storage.memory import MemoryStorage

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = "8366606577:AAFHCashI_usjf1Xowif_flbF7bWaXWerVU"
ADMIN_USERNAMES = ["yesbeers", "yyangpython"]
MANAGER_CONTACT = "@managersrich"
REQUIRED_CHANNEL = "@eweton"
REFERRAL_BONUS = 0.2

# Абсолютный путь к базе данных
SCRIPT_DIR = Path(__file__).parent.absolute()
DATABASE_PATH = SCRIPT_DIR / "shop_bot.db"

logger.info(f"Путь к базе данных: {DATABASE_PATH}")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class AdminStates(StatesGroup):
    select_category = State()
    select_item = State()
    enter_new_price = State()
    enter_new_name = State()

class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
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
                logger.info("База данных успешно инициализирована")
                
        except Exception as e:
            logger.error(f"Ошибка инициализации базы данных: {e}")

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
                        logger.info(f"Начисляем бонус: {referrer_id} пригласил {user_id}")
                        self._add_referral_bonus(referrer_id, user_id)
                else:
                    cursor.execute(
                        'UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE user_id = ?',
                        (username, first_name, last_name, user_id)
                    )
                    conn.commit()
                    logger.info(f"Обновлен существующий пользователь: {user_id}")
                    
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя {user_id}: {e}")

    def _add_referral_bonus(self, referrer_id: int, referred_id: int):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (referrer_id,))
                referrer_exists = cursor.fetchone()
                
                if not referrer_exists:
                    logger.error(f"Реферер {referrer_id} не найден в базе")
                    return
                    
                cursor.execute('SELECT id FROM referrals WHERE referred_id = ?', (referred_id,))
                existing_referral = cursor.fetchone()
                
                if existing_referral:
                    logger.info(f"Бонус для {referred_id} уже был начислен")
                    return
                    
                cursor.execute(
                    'INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)',
                    (referrer_id, referred_id)
                )
                
                cursor.execute(
                    'UPDATE users SET balance = balance + ? WHERE user_id = ?',
                    (REFERRAL_BONUS, referrer_id)
                )
                
                logger.info(f"Бонус {REFERRAL_BONUS} руб. начислен пользователю {referrer_id} за приглашение {referred_id}")
                conn.commit()
                
        except Exception as e:
            logger.error(f"Ошибка при начислении реферального бонуса: {e}")

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

async def check_subscription(user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception:
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
            [KeyboardButton(text="Pubg Mobile"), KeyboardButton(text="PUBG PC")],
            [KeyboardButton(text="Discord"), KeyboardButton(text="YouTube")],
            [KeyboardButton(text="TikTok"), KeyboardButton(text="Telegram")],
            [KeyboardButton(text="NFT Подарки"), KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

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

def get_nft_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="NFT Подарки")],
            [KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

def get_items_keyboard(category_name: str):
    category = db.get_category_by_name(category_name)
    if not category:
        return get_back_keyboard()
    
    category_id, _ = category
    items = db.get_items_by_category(category_id)
    
    unique_items = {}
    for item_id, item_name, price in items:
        if item_name not in unique_items:
            unique_items[item_name] = price
    
    buttons = []
    row = []
    for item_name in unique_items.keys():
        row.append(KeyboardButton(text=item_name))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([KeyboardButton(text="Назад")])
    
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_uc_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="30 UC"), KeyboardButton(text="60 UC")],
            [KeyboardButton(text="180 UC"), KeyboardButton(text="300 UC")],
            [KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

def get_gcoins_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="100 G-Coins"), KeyboardButton(text="200 G-Coins")],
            [KeyboardButton(text="300 G-Coins")],
            [KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

def get_nitro_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Nitro 3 мес + 2 буста")],
            [KeyboardButton(text="Nitro Basic 1 мес")],
            [KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

def get_standoff_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1 голда"), KeyboardButton(text="Клан")],
            [KeyboardButton(text="Донат 3к голды")],
            [KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

def get_brawl_gems_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="30 гемов"), KeyboardButton(text="80 гемов")],
            [KeyboardButton(text="170 гемов")],
            [KeyboardButton(text="Brawl Pass"), KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

def get_clash_gems_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="80 гемов"), KeyboardButton(text="160 гемов")],
            [KeyboardButton(text="240 гемов")],
            [KeyboardButton(text="Pass Royale"), KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

def get_robux_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="80 робуксов"), KeyboardButton(text="200 робуксов")],
            [KeyboardButton(text="400 робуксов")],
            [KeyboardButton(text="Premium + 450 робуксов"), KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

def get_cs2_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Prime")],
            [KeyboardButton(text="Faceit Plus 1 мес")],
            [KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    referrer_id = None
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]
        logger.info(f"Обнаружен реферальный код: {referral_code} от пользователя {message.from_user.id}")
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
            result = cursor.fetchone()
            if result and result[0] != message.from_user.id:
                referrer_id = result[0]
                logger.info(f"Реферал найден: {referrer_id} пригласил {message.from_user.id}")
            else:
                logger.info("Реферал не найден или пользователь ссылается на себя")
    
    db.add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name or "",
        referrer_id
    )
    
    if not await check_subscription(message.from_user.id):
        await message.answer(f"Подпишитесь на канал {REQUIRED_CHANNEL}\n\nПосле подписки нажмите /start", reply_markup=ReplyKeyboardRemove())
        return
    
    await message.answer("Добро пожаловать! Выберите действие:", reply_markup=get_main_keyboard())

@dp.message(Command("info"))
async def cmd_info(message: types.Message):
    users_count = db.get_users_count()
    await message.answer(f"Пользователей в боте: {users_count}")

@dp.message(Command("debug"))
async def cmd_debug(message: types.Message):
    if not is_admin(message.from_user.username):
        await message.answer("Нет прав доступа.")
        return
        
    users_count = db.get_users_count()
    db_exists = DATABASE_PATH.exists()
    db_size = DATABASE_PATH.stat().st_size if db_exists else 0
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, created_at FROM users WHERE user_id = ?', (message.from_user.id,))
        current_user = cursor.fetchone()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        cursor.execute('SELECT user_id, username FROM users')
        all_users = cursor.fetchall()
    
    debug_info = (
        f"Отладка базы данных:\n"
        f"Файл БД: {DATABASE_PATH}\n"
        f"Файл существует: {db_exists}\n"
        f"Размер БД: {db_size} байт\n"
        f"Таблицы: {[table[0] for table in tables]}\n"
        f"Всего пользователей: {users_count}\n"
        f"Текущий пользователь в БД: {current_user}\n"
        f"Ваш ID: {message.from_user.id}\n"
        f"Все пользователи: {all_users}"
    )
    
    await message.answer(debug_info)

@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    balance = db.get_user_balance(message.from_user.id)
    referrals_count, total_earned = db.get_referral_stats(message.from_user.id)
    balance_text = f"Баланс: {balance:.2f} руб.\nПриглашено: {referrals_count}\nЗаработано: {total_earned:.2f} руб.\n\nДля вывода: {MANAGER_CONTACT}"
    await message.answer(balance_text, reply_markup=get_main_keyboard())

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.username):
        await message.answer("Нет прав доступа.")
        return
    
    keyboard = InlineKeyboardBuilder()
    categories = db.get_categories()
    for category_id, category_name in categories:
        keyboard.add(InlineKeyboardButton(text=category_name, callback_data=f"admin_category_{category_id}"))
    keyboard.adjust(2)
    
    await message.answer("Панель администратора. Выберите категорию:", reply_markup=keyboard.as_markup())
    await state.set_state(AdminStates.select_category)

# ... остальные admin функции остаются без изменений ...

@dp.message(F.text == "Каталог")
async def show_catalog(message: types.Message):
    if not await check_subscription(message.from_user.id):
        await message.answer("Проверьте подписку!", reply_markup=get_main_keyboard())
        return
    await message.answer("Выберите категорию:", reply_markup=get_catalog_keyboard())

@dp.message(F.text == "Telegram")
async def show_telegram_category(message: types.Message):
    await message.answer("Telegram - доступные товары:", reply_markup=get_telegram_keyboard())

@dp.message(F.text == "NFT Подарки")
async def show_nft_category(message: types.Message):
    await message.answer(f"NFT Подарки - для заказа напишите менеджеру в ЛС:{MANAGER_CONTACT}", reply_markup=get_nft_keyboard())

# Обработчики для Telegram товаров
@dp.message(F.text == "21 звезда")
async def handle_21_stars(message: types.Message):
    order_text = f"Заказ: 21 звезда Telegram\nЦена: 40 руб.\n\nДля заказа: {MANAGER_CONTACT}"
    await message.answer(order_text, reply_markup=get_back_keyboard())

@dp.message(F.text == "50 звезд")
async def handle_50_stars(message: types.Message):
    order_text = f"Заказ: 50 звезд Telegram\nЦена: 85 руб.\n\nДля заказа: {MANAGER_CONTACT}"
    await message.answer(order_text, reply_markup=get_back_keyboard())

@dp.message(F.text == "100 звезд")
async def handle_100_stars(message: types.Message):
    order_text = f"Заказ: 100 звезд Telegram\nЦена: 160 руб.\n\nДля заказа: {MANAGER_CONTACT}"
    await message.answer(order_text, reply_markup=get_back_keyboard())

@dp.message(F.text == "Premium 1 месяц")
async def handle_premium_1_month(message: types.Message):
    order_text = f"Заказ: Telegram Premium 1 месяц\nЦена: 360 руб.\n\nДля заказа: {MANAGER_CONTACT}"
    await message.answer(order_text, reply_markup=get_back_keyboard())

@dp.message(F.text == "Premium 3 месяца")
async def handle_premium_3_months(message: types.Message):
    order_text = f"Заказ: Telegram Premium 3 месяца\nЦена: 1250 руб.\n\nДля заказа: {MANAGER_CONTACT}"
    await message.answer(order_text, reply_markup=get_back_keyboard())

@dp.message(F.text == "Premium 6 месяцев")
async def handle_premium_6_months(message: types.Message):
    order_text = f"Заказ: Telegram Premium 6 месяцев\nЦена: 1550 руб.\n\nДля заказа: {MANAGER_CONTACT}"
    await message.answer(order_text, reply_markup=get_back_keyboard())

@dp.message(F.text == "Premium 12 месяцев")
async def handle_premium_12_months(message: types.Message):
    order_text = f"Заказ: Telegram Premium 12 месяцев\nЦена: 2400 руб.\n\nДля заказа: {MANAGER_CONTACT}"
    await message.answer(order_text, reply_markup=get_back_keyboard())

@dp.message(F.text == "NFT Подарки")
async def handle_nft_gifts(message: types.Message):
    order_text = f"Заказ: NFT Подарки\n\nДля заказа и просмотра ассортимента напишите менеджеру в ЛС: {MANAGER_CONTACT}"
    await message.answer(order_text, reply_markup=get_back_keyboard())

# ... остальные обработчики для других категорий остаются без изменений ...

@dp.message(F.text == "Назад")
async def back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_keyboard())

# ... остальные функции для других категорий ...

async def main():
    logger.info("Бот запущен")
    users_count = db.get_users_count()
    logger.info(f"Пользователей в базе при запуске: {users_count}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())