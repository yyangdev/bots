import asyncio
import logging
import secrets
import os
import json
import asyncpg
from pathlib import Path
from datetime import datetime, time as dt_time, timedelta
from typing import List
import pytz
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.redis import RedisStorage
import redis.asyncio as redis

# ==================== ⚙️ КОНФИГУРАЦИЯ ====================
TOKEN = os.getenv('BOT_TOKEN', '8366606577:AAFHCashI_usjf1Xowif_flbF7bWaXWerVU')
ADMIN_USERNAMES = ["yesbeers"]  # 🛡️ Только один администратор
MANAGER_CONTACT = "@managersrich"
REQUIRED_CHANNEL = "@eweton"
REFERRAL_BONUS = 0.5  # 💰 0.5 руб за каждого приглашенного
BROADCAST_TIME = dt_time(13, 0)  # 🕐 Время рассылки: 13:00

# Настройки базы данных
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:pass@localhost/shop_bot')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')

# ==================== 📊 НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== 🤖 ИНИЦИАЛИЗАЦИЯ БОТА ====================
bot = Bot(token=TOKEN)

# Инициализация Redis для FSM
try:
    redis_client = redis.from_url(REDIS_URL)
    storage = RedisStorage(redis=redis_client)
    logger.info("✅ Redis storage инициализирован")
except Exception as e:
    logger.warning(f"❌ Redis недоступен, используем MemoryStorage: {e}")
    from aiogram.fsm.storage.memory import MemoryStorage
    storage = MemoryStorage()

dp = Dispatcher(storage=storage)

# ==================== 🏪 СОСТОЯНИЯ АДМИНИСТРАТОРА ====================
class AdminStates(StatesGroup):
    select_category = State()
    select_item = State()
    enter_new_price = State()
    enter_new_name = State()

# ==================== 🗃️ КЛАСС БАЗЫ ДАННЫХ POSTGRESQL ====================
class Database:
    def __init__(self):
        self.connection_pool = None
        self.init_complete = False

    async def init_db(self):
        """Инициализация подключения к базе данных"""
        try:
            self.connection_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
            logger.info("✅ Подключение к PostgreSQL установлено")
            
            await self._create_tables()
            await self._seed_initial_data()
            self.init_complete = True
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации базы данных: {e}")
            raise

    async def _create_tables(self):
        """Создание таблиц в базе данных"""
        async with self.connection_pool.acquire() as conn:
            # 👥 Таблица пользователей
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    balance REAL DEFAULT 0,
                    referral_code TEXT UNIQUE,
                    referrer_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 📂 Таблица категорий
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 🎁 Таблица товаров
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS items (
                    id SERIAL PRIMARY KEY,
                    category_id INTEGER,
                    name TEXT NOT NULL,
                    price REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (category_id) REFERENCES categories (id)
                )
            ''')
            
            # 🤝 Таблица рефералов
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id BIGINT,
                    referred_id BIGINT,
                    bonus_paid BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(referred_id)
                )
            ''')
            
            logger.info("✅ Таблицы созданы/проверены")

    async def _seed_initial_data(self):
        """Заполнение начальными данными"""
        async with self.connection_pool.acquire() as conn:
            # 🎮 Начальные категории
            initial_categories = [
                "GTA 5 RP", "Standoff 2", "Brawl Stars", "Clash Royale", 
                "Roblox", "CS 2", "Pubg Mobile", "PUBG (PC/Console)", 
                "Discord", "YouTube", "TikTok", "Telegram", "NFT Подарки"
            ]
            
            # 📦 Начальные товары с ценами
            initial_items = {
                "Standoff 2": [
                    ("1 голда", 0.7),
                    ("100 голды", 70),
                    ("1000 голды", 700),
                    ("3000 голды (донат)", 2600),
                    ("Клан", 170),
                ],
                "Brawl Stars": [
                    ("30 гемов", 190),
                    ("80 гемов", 440),
                    ("170 гемов", 790),
                    ("Brawl Pass", 300),
                ],
                "Clash Royale": [
                    ("80 гемов", 90),
                    ("160 гемов", 185),
                    ("240 гемов", 270),
                    ("Pass Royale", 400),
                ],
                "Pubg Mobile": [
                    ("30 UC", 85),
                    ("60 UC", 100),
                    ("180 UC", 275),
                    ("300 UC", 480),
                ],
                "PUBG (PC/Console)": [
                    ("100 G-Coins", 150),
                    ("200 G-Coins", 250),
                    ("300 G-Coins", 350),
                ],
                "Discord": [
                    ("Nitro Full 3 месяца + 2 буста", 70),
                    ("Nitro Basic (1 месяц)", 190),
                ],
                "Roblox": [
                    ("80 робуксов", 130),
                    ("200 робуксов", 300),
                    ("400 робуксов", 500),
                    ("Roblox Premium + 450 робуксов", 550),
                ],
                "CS 2": [
                    ("Prime", 1480),
                    ("Faceit Plus (1 месяц)", 500),
                ],
                "Telegram": [
                    ("21 звезда", 40),
                    ("50 звезд", 85),
                    ("100 звезд", 160),
                    ("Premium 1 месяц", 360),
                    ("Premium 3 месяца", 1250),
                    ("Premium 6 месяцев", 1550),
                    ("Premium 12 месяцев", 2400),
                ],
            }
            
            # 📥 Заполняем категории
            for category_name in initial_categories:
                await conn.execute(
                    'INSERT INTO categories (name) VALUES ($1) ON CONFLICT (name) DO NOTHING',
                    category_name
                )
            
            # 📦 Заполняем товары с ценами
            for category_name, items in initial_items.items():
                category_id = await conn.fetchval(
                    'SELECT id FROM categories WHERE name = $1', 
                    category_name
                )
                if category_id:
                    for item_name, price in items:
                        await conn.execute(
                            '''INSERT INTO items (category_id, name, price) 
                               VALUES ($1, $2, $3) 
                               ON CONFLICT DO NOTHING''',
                            category_id, item_name, price
                        )
            
            logger.info("✅ Начальные данные загружены")

    async def add_user(self, user_id: int, username: str, first_name: str, last_name: str = "", referrer_id: int = None):
        """Добавление пользователя в базу"""
        try:
            async with self.connection_pool.acquire() as conn:
                # Проверяем существование пользователя
                existing_user = await conn.fetchval(
                    'SELECT user_id FROM users WHERE user_id = $1', 
                    user_id
                )
                
                if not existing_user:
                    referral_code = secrets.token_hex(4).upper()
                    await conn.execute(
                        '''INSERT INTO users (user_id, username, first_name, last_name, referral_code, referrer_id) 
                           VALUES ($1, $2, $3, $4, $5, $6)''',
                        user_id, username, first_name, last_name, referral_code, referrer_id
                    )
                    logger.info(f"✅ Добавлен новый пользователь: {user_id} (@{username})")
                    
                    # Начисляем бонус рефереру
                    if referrer_id:
                        await self._add_referral_bonus(referrer_id, user_id)
                else:
                    # Обновляем данные существующего пользователя
                    await conn.execute(
                        'UPDATE users SET username = $1, first_name = $2, last_name = $3 WHERE user_id = $4',
                        username, first_name, last_name, user_id
                    )
                    logger.info(f"🔄 Обновлен пользователь: {user_id}")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка добавления пользователя {user_id}: {e}")

    async def _add_referral_bonus(self, referrer_id: int, referred_id: int):
        """Начисление реферального бонуса"""
        try:
            async with self.connection_pool.acquire() as conn:
                # Проверяем существование реферера
                referrer_exists = await conn.fetchval(
                    'SELECT user_id FROM users WHERE user_id = $1', 
                    referrer_id
                )
                
                if not referrer_exists:
                    logger.error(f"❌ Реферер {referrer_id} не найден")
                    return
                
                # Проверяем, не начислялся ли уже бонус
                existing_referral = await conn.fetchval(
                    'SELECT id FROM referrals WHERE referred_id = $1', 
                    referred_id
                )
                
                if existing_referral:
                    logger.info(f"ℹ️ Бонус для {referred_id} уже начислен")
                    return
                
                # Добавляем запись о реферале и начисляем бонус
                await conn.execute(
                    'INSERT INTO referrals (referrer_id, referred_id) VALUES ($1, $2)',
                    referrer_id, referred_id
                )
                
                await conn.execute(
                    'UPDATE users SET balance = balance + $1 WHERE user_id = $2',
                    REFERRAL_BONUS, referrer_id
                )
                
                logger.info(f"💰 Бонус {REFERRAL_BONUS}₽ начислен пользователю {referrer_id}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка начисления бонуса: {e}")

    async def get_user_balance(self, user_id: int) -> float:
        """Получение баланса пользователя"""
        async with self.connection_pool.acquire() as conn:
            balance = await conn.fetchval(
                'SELECT balance FROM users WHERE user_id = $1', 
                user_id
            )
            return balance or 0.0

    async def get_referral_code(self, user_id: int) -> str:
        """Получение реферального кода"""
        async with self.connection_pool.acquire() as conn:
            return await conn.fetchval(
                'SELECT referral_code FROM users WHERE user_id = $1', 
                user_id
            )

    async def get_referral_stats(self, user_id: int) -> tuple:
        """Получение статистики рефералов"""
        async with self.connection_pool.acquire() as conn:
            total_referrals = await conn.fetchval(
                'SELECT COUNT(*) FROM referrals WHERE referrer_id = $1', 
                user_id
            )
            total_earned = total_referrals * REFERRAL_BONUS
            return total_referrals or 0, total_earned or 0.0

    async def get_all_users(self) -> List[int]:
        """Получение всех пользователей"""
        async with self.connection_pool.acquire() as conn:
            rows = await conn.fetch('SELECT user_id FROM users')
            users = [row['user_id'] for row in rows]
            logger.info(f"📊 Найдено пользователей: {len(users)}")
            return users

    async def get_users_count(self) -> int:
        """Получение количества пользователей"""
        try:
            async with self.connection_pool.acquire() as conn:
                count = await conn.fetchval('SELECT COUNT(*) FROM users')
                return count or 0
        except Exception as e:
            logger.error(f"❌ Ошибка получения количества пользователей: {e}")
            return 0

    async def get_categories(self) -> List[tuple]:
        """Получение всех категорий"""
        async with self.connection_pool.acquire() as conn:
            rows = await conn.fetch('SELECT id, name FROM categories ORDER BY name')
            return [(row['id'], row['name']) for row in rows]

    async def get_items_by_category(self, category_id: int) -> List[tuple]:
        """Получение товаров по категории"""
        async with self.connection_pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT id, name, price FROM items WHERE category_id = $1 ORDER BY name',
                category_id
            )
            return [(row['id'], row['name'], row['price']) for row in rows]

    async def backup_database(self):
        """Создание резервной копии данных"""
        try:
            backup_data = {
                'timestamp': datetime.now().isoformat(),
                'users_count': await self.get_users_count(),
                'backup_type': 'automatic'
            }
            
            # Сохраняем в файл (можно адаптировать для облачного хранилища)
            backup_dir = Path("backups")
            backup_dir.mkdir(exist_ok=True)
            
            backup_file = backup_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ Резервная копия создана: {backup_file}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания резервной копии: {e}")
            return False

# ==================== 🗃️ ЭКЗЕМПЛЯР БАЗЫ ДАННЫХ ====================
db = Database()

# ==================== 🔐 ФУНКЦИИ ПРОВЕРКИ ====================
async def check_subscription(user_id: int) -> bool:
    """Проверка подписки на канал"""
    try:
        chat_member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception:
        return True

def is_admin(username: str) -> bool:
    """Проверка прав администратора"""
    if not username:
        return False
    clean_username = username.lstrip('@')
    return clean_username in ADMIN_USERNAMES

# ==================== ⌨️ КЛАВИАТУРЫ ====================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Каталог")],
            [KeyboardButton(text="💰 Реферальная система"), KeyboardButton(text="💳 Баланс")],
            [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="📞 Контакты")]
        ],
        resize_keyboard=True
    )

def get_catalog_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎮 GTA 5 RP"), KeyboardButton(text="🔫 Standoff 2")],
            [KeyboardButton(text="👊 Brawl Stars"), KeyboardButton(text="👑 Clash Royale")],
            [KeyboardButton(text="🧩 Roblox"), KeyboardButton(text="🔫 CS 2")],
            [KeyboardButton(text="📱 Pubg Mobile"), KeyboardButton(text="🎯 PUBG (PC/Console)")],
            [KeyboardButton(text="💬 Discord"), KeyboardButton(text="📺 YouTube")],
            [KeyboardButton(text="📱 TikTok"), KeyboardButton(text="✈️ Telegram")],
            [KeyboardButton(text="🎁 NFT Подарки"), KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_back_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад")]], 
        resize_keyboard=True
    )

def get_standoff_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💎 1 голда"), KeyboardButton(text="💎 100 голды")],
            [KeyboardButton(text="💎 1000 голды"), KeyboardButton(text="💎 3000 голды (донат)")],
            [KeyboardButton(text="🏰 Клан")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_brawl_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💎 30 гемов"), KeyboardButton(text="💎 80 гемов")],
            [KeyboardButton(text="💎 170 гемов"), KeyboardButton(text="🎫 Brawl Pass")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_clash_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💎 80 гемов CR"), KeyboardButton(text="💎 160 гемов CR")],
            [KeyboardButton(text="💎 240 гемов CR"), KeyboardButton(text="🎫 Pass Royale")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_pubgm_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🪙 30 UC"), KeyboardButton(text="🪙 60 UC")],
            [KeyboardButton(text="🪙 180 UC"), KeyboardButton(text="🪙 300 UC")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_pubg_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🪙 100 G-Coins"), KeyboardButton(text="🪙 200 G-Coins")],
            [KeyboardButton(text="🪙 300 G-Coins")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_discord_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Nitro Full 3 месяца")],
            [KeyboardButton(text="⭐ Nitro Basic 1 месяц")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_roblox_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 80 робуксов"), KeyboardButton(text="💰 200 робуксов")],
            [KeyboardButton(text="💰 400 робуксов"), KeyboardButton(text="⭐ Premium + 450")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_cs2_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎮 CS2 Prime")],
            [KeyboardButton(text="⚡ Faceit Plus")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_telegram_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⭐ 21 звезда"), KeyboardButton(text="⭐⭐ 50 звезд")],
            [KeyboardButton(text="⭐⭐⭐ 100 звезд")],
            [KeyboardButton(text="👑 Premium 1 месяц"), KeyboardButton(text="👑👑 Premium 3 месяца")],
            [KeyboardButton(text="👑👑👑 Premium 6 месяцев"), KeyboardButton(text="👑👑👑👑 Premium 12 месяцев")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

# ==================== 🎯 ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    referrer_id = None
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]
        logger.info(f"🔍 Реферальный код: {referral_code} от {message.from_user.id}")
        
        async with db.connection_pool.acquire() as conn:
            result = await conn.fetchval(
                'SELECT user_id FROM users WHERE referral_code = $1', 
                referral_code
            )
            if result and result != message.from_user.id:
                referrer_id = result
                logger.info(f"✅ Реферал найден: {referrer_id} пригласил {message.from_user.id}")
    
    await db.add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name or "",
        referrer_id
    )
    
    if not await check_subscription(message.from_user.id):
        await message.answer(
            f"📢 Для использования бота подпишитесь на канал {REQUIRED_CHANNEL}\n\n"
            f"После подписки нажмите /start",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    
    welcome_text = """🚀 Хочешь прокачать своего персонажа или аккаунт? Тогда тебе к нам! 🚀

Наш бот – это твой личный магазин игровых ценностей, где ты можешь приобрести:

💰 Игровую валюту: Быстро пополняй свой баланс в любимых играх и покупай всё, что захочешь!
🎮 Игровые аккаунты: Получи готовый аккаунт с нужным прогрессом и персонажами.
💎 Редкие предметы и скины: Сделай своего персонажа уникальным!
🔑 Ключи активации: Открывай новые игры и дополнения по лучшим ценам.

Почему стоит выбрать нас?
✅ Безопасность: Все сделки проходят через защищенные каналы.
✅ Скорость: Мгновенная доставка твоих покупок.
✅ Выгодные цены: Лучшие предложения на рынке игровых товаров.
✅ Широкий ассортимент: Найди всё, что нужно для комфортной игры.

Не упусти свой шанс стать лучшим в любимой игре! ✨"""
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(Command("info"))
async def cmd_info(message: types.Message):
    """Информация о боте"""
    users_count = await db.get_users_count()
    await message.answer(f"👥 Пользователей в боте: {users_count}")

@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    """Проверка баланса"""
    balance = await db.get_user_balance(message.from_user.id)
    referrals_count, total_earned = await db.get_referral_stats(message.from_user.id)
    
    balance_text = f"""
💰 Ваш баланс:

💵 Баланс: {balance:.2f} руб.
👥 Приглашено друзей: {referrals_count}
🎁 Заработано: {total_earned:.2f} руб.

💌 Для вывода: {MANAGER_CONTACT}
    """
    await message.answer(balance_text, reply_markup=get_main_keyboard())

@dp.message(Command("backup"))
async def cmd_backup(message: types.Message):
    """Создание резервной копии (для админа)"""
    if not is_admin(message.from_user.username):
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    await message.answer("🔄 Создаем резервную копию...")
    if await db.backup_database():
        await message.answer("✅ Резервная копия создана успешно")
    else:
        await message.answer("❌ Ошибка создания резервной копии")

# ==================== 🛒 ОБРАБОТЧИКИ КАТАЛОГА ====================
@dp.message(F.text == "🛒 Каталог")
async def show_catalog(message: types.Message):
    """Показать каталог"""
    if not await check_subscription(message.from_user.id):
        await message.answer("❌ Проверьте подписку!", reply_markup=get_main_keyboard())
        return
    
    catalog_text = """🎮 Выберите категорию:

У нас есть товары для:
• Игр (GTA, Standoff, Brawl Stars и др.)
• Социальных сетей (Telegram, Discord)
• Уникальных NFT подарков"""
    await message.answer(catalog_text, reply_markup=get_catalog_keyboard())

# STANDOFF 2
@dp.message(F.text == "🔫 Standoff 2")
async def show_standoff(message: types.Message):
    text = """🔫 Standoff 2 - товары:

💎 Голда:
• 1 голда - 0.7₽
• 100 голды - 70₽
• 1000 голды - 700₽
• 3000 голды (донат) - 2600₽

🏰 Клан - 170₽"""
    await message.answer(text, reply_markup=get_standoff_keyboard())

# Обработчики Standoff 2
@dp.message(F.text.in_(["💎 1 голда", "💎 100 голды", "💎 1000 голды", "💎 3000 голды (донат)", "🏰 Клан"]))
async def handle_standoff_item(message: types.Message):
    item_map = {
        "💎 1 голда": ("1 голда", 0.7),
        "💎 100 голды": ("100 голды", 70),
        "💎 1000 голды": ("1000 голды", 700),
        "💎 3000 голды (донат)": ("3000 голды (донат)", 2600),
        "🏰 Клан": ("Клан", 170)
    }
    
    item_name, price = item_map.get(message.text, ("", 0))
    
    order_text = f"""🛒 Заказ: {item_name} - Standoff 2

💰 Цена: {price}₽
⚡ Мгновенная доставка

💬 Для заказа: {MANAGER_CONTACT}"""
    await message.answer(order_text, reply_markup=get_back_keyboard())

# BRAWL STARS
@dp.message(F.text == "👊 Brawl Stars")
async def show_brawl(message: types.Message):
    text = """👊 Brawl Stars - товары:

💎 Гемы:
• 30 гемов - 190₽
• 80 гемов - 440₽
• 170 гемов - 790₽

🎫 Brawl Pass - 300₽"""
    await message.answer(text, reply_markup=get_brawl_keyboard())

# Обработчики Brawl Stars
@dp.message(F.text.in_(["💎 30 гемов", "💎 80 гемов", "💎 170 гемов", "🎫 Brawl Pass"]))
async def handle_brawl_item(message: types.Message):
    item_map = {
        "💎 30 гемов": ("30 гемов", 190),
        "💎 80 гемов": ("80 гемов", 440),
        "💎 170 гемов": ("170 гемов", 790),
        "🎫 Brawl Pass": ("Brawl Pass", 300)
    }
    
    item_name, price = item_map.get(message.text, ("", 0))
    
    order_text = f"""🛒 Заказ: {item_name} - Brawl Stars

💰 Цена: {price}₽
⚡ Мгновенная доставка

💬 Для заказа: {MANAGER_CONTACT}"""
    await message.answer(order_text, reply_markup=get_back_keyboard())

# CLASH ROYALE
@dp.message(F.text == "👑 Clash Royale")
async def show_clash(message: types.Message):
    text = """👑 Clash Royale - товары:

💎 Гемы:
• 80 гемов - 90₽
• 160 гемов - 185₽
• 240 гемов - 270₽

🎫 Pass Royale - 400₽"""
    await message.answer(text, reply_markup=get_clash_keyboard())

# Обработчики Clash Royale
@dp.message(F.text.in_(["💎 80 гемов CR", "💎 160 гемов CR", "💎 240 гемов CR", "🎫 Pass Royale"]))
async def handle_clash_item(message: types.Message):
    item_map = {
        "💎 80 гемов CR": ("80 гемов", 90),
        "💎 160 гемов CR": ("160 гемов", 185),
        "💎 240 гемов CR": ("240 гемов", 270),
        "🎫 Pass Royale": ("Pass Royale", 400)
    }
    
    item_name, price = item_map.get(message.text, ("", 0))
    
    order_text = f"""🛒 Заказ: {item_name} - Clash Royale

💰 Цена: {price}₽
⚡ Мгновенная доставка

💬 Для заказа: {MANAGER_CONTACT}"""
    await message.answer(order_text, reply_markup=get_back_keyboard())

# PUBG MOBILE
@dp.message(F.text == "📱 Pubg Mobile")
async def show_pubgm(message: types.Message):
    text = """📱 Pubg Mobile - товары:

🪙 UC:
• 30 UC - 85₽
• 60 UC - 100₽
• 180 UC - 275₽
• 300 UC - 480₽"""
    await message.answer(text, reply_markup=get_pubgm_keyboard())

# Обработчики Pubg Mobile
@dp.message(F.text.in_(["🪙 30 UC", "🪙 60 UC", "🪙 180 UC", "🪙 300 UC"]))
async def handle_pubgm_item(message: types.Message):
    item_map = {
        "🪙 30 UC": ("30 UC", 85),
        "🪙 60 UC": ("60 UC", 100),
        "🪙 180 UC": ("180 UC", 275),
        "🪙 300 UC": ("300 UC", 480)
    }
    
    item_name, price = item_map.get(message.text, ("", 0))
    
    order_text = f"""🛒 Заказ: {item_name} - Pubg Mobile

💰 Цена: {price}₽
⚡ Мгновенная доставка

💬 Для заказа: {MANAGER_CONTACT}"""
    await message.answer(order_text, reply_markup=get_back_keyboard())

# PUBG PC/Console
@dp.message(F.text == "🎯 PUBG (PC/Console)")
async def show_pubg(message: types.Message):
    text = """🎯 PUBG (PC/Console) - товары:

🪙 G-Coins:
• 100 G-Coins - 150₽
• 200 G-Coins - 250₽
• 300 G-Coins - 350₽"""
    await message.answer(text, reply_markup=get_pubg_keyboard())

# Обработчики PUBG
@dp.message(F.text.in_(["🪙 100 G-Coins", "🪙 200 G-Coins", "🪙 300 G-Coins"]))
async def handle_pubg_item(message: types.Message):
    item_map = {
        "🪙 100 G-Coins": ("100 G-Coins", 150),
        "🪙 200 G-Coins": ("200 G-Coins", 250),
        "🪙 300 G-Coins": ("300 G-Coins", 350)
    }
    
    item_name, price = item_map.get(message.text, ("", 0))
    
    order_text = f"""🛒 Заказ: {item_name} - PUBG

💰 Цена: {price}₽
⚡ Мгновенная доставка

💬 Для заказа: {MANAGER_CONTACT}"""
    await message.answer(order_text, reply_markup=get_back_keyboard())

# DISCORD
@dp.message(F.text == "💬 Discord")
async def show_discord(message: types.Message):
    text = """💬 Discord - товары:

🚀 Nitro Full 3 месяца + 2 буста - 70₽
⭐ Nitro Basic (1 месяц) - 190₽"""
    await message.answer(text, reply_markup=get_discord_keyboard())

# Обработчики Discord
@dp.message(F.text.in_(["🚀 Nitro Full 3 месяца", "⭐ Nitro Basic 1 месяц"]))
async def handle_discord_item(message: types.Message):
    item_map = {
        "🚀 Nitro Full 3 месяца": ("Nitro Full 3 месяца + 2 буста", 70),
        "⭐ Nitro Basic 1 месяц": ("Nitro Basic (1 месяц)", 190)
    }
    
    item_name, price = item_map.get(message.text, ("", 0))
    
    order_text = f"""🛒 Заказ: {item_name} - Discord

💰 Цена: {price}₽
⚡ Мгновенная доставка

💬 Для заказа: {MANAGER_CONTACT}"""
    await message.answer(order_text, reply_markup=get_back_keyboard())

# ROBLOX
@dp.message(F.text == "🧩 Roblox")
async def show_roblox(message: types.Message):
    text = """🧩 Roblox - товары:

💰 Робуксы:
• 80 робуксов - 130₽
• 200 робуксов - 300₽
• 400 робуксов - 500₽

⭐ Roblox Premium + 450 робуксов - 550₽

📌 Приват сервер (5 дней) - 0.55₽ за 1 робукс"""
    await message.answer(text, reply_markup=get_roblox_keyboard())

# Обработчики Roblox
@dp.message(F.text.in_(["💰 80 робуксов", "💰 200 робуксов", "💰 400 робуксов", "⭐ Premium + 450"]))
async def handle_roblox_item(message: types.Message):
    item_map = {
        "💰 80 робуксов": ("80 робуксов", 130),
        "💰 200 робуксов": ("200 робуксов", 300),
        "💰 400 робуксов": ("400 робуксов", 500),
        "⭐ Premium + 450": ("Roblox Premium + 450 робуксов", 550)
    }
    
    item_name, price = item_map.get(message.text, ("", 0))
    
    order_text = f"""🛒 Заказ: {item_name} - Roblox

💰 Цена: {price}₽
⚡ Мгновенная доставка

💬 Для заказа: {MANAGER_CONTACT}"""
    await message.answer(order_text, reply_markup=get_back_keyboard())

# CS 2
@dp.message(F.text == "🔫 CS 2")
async def show_cs2(message: types.Message):
    text = """🔫 CS 2 - товары:

🎮 Prime - 1480₽
⚡ Faceit Plus (1 месяц) - 500₽"""
    await message.answer(text, reply_markup=get_cs2_keyboard())

# Обработчики CS 2
@dp.message(F.text.in_(["🎮 CS2 Prime", "⚡ Faceit Plus"]))
async def handle_cs2_item(message: types.Message):
    item_map = {
        "🎮 CS2 Prime": ("Prime", 1480),
        "⚡ Faceit Plus": ("Faceit Plus (1 месяц)", 500)
    }
    
    item_name, price = item_map.get(message.text, ("", 0))
    
    order_text = f"""🛒 Заказ: {item_name} - CS 2

💰 Цена: {price}₽
⚡ Мгновенная доставка

💬 Для заказа: {MANAGER_CONTACT}"""
    await message.answer(order_text, reply_markup=get_back_keyboard())

# TELEGRAM
@dp.message(F.text == "✈️ Telegram")
async def show_telegram_category(message: types.Message):
    telegram_text = """✈️ Telegram - товары:

⭐ Звезды:
• 21 звезда - 40₽
• 50 звезд - 85₽  
• 100 звезд - 160₽

👑 Premium подписки:
• 1 месяц - 360₽
• 3 месяца - 1250₽
• 6 месяцев - 1550₽
• 12 месяцев - 2400₽"""
    await message.answer(telegram_text, reply_markup=get_telegram_keyboard())

# Обработчики Telegram товаров
@dp.message(F.text.in_(["⭐ 21 звезда", "⭐⭐ 50 звезд", "⭐⭐⭐ 100 звезд", 
                       "👑 Premium 1 месяц", "👑👑 Premium 3 месяца", 
                       "👑👑👑 Premium 6 месяцев", "👑👑👑👑 Premium 12 месяцев"]))
async def handle_telegram_item(message: types.Message):
    item_map = {
        "⭐ 21 звезда": ("21 звезда", 40),
        "⭐⭐ 50 звезд": ("50 звезд", 85),
        "⭐⭐⭐ 100 звезд": ("100 звезд", 160),
        "👑 Premium 1 месяц": ("Telegram Premium 1 месяц", 360),
        "👑👑 Premium 3 месяца": ("Telegram Premium 3 месяца", 1250),
        "👑👑👑 Premium 6 месяцев": ("Telegram Premium 6 месяцев", 1550),
        "👑👑👑👑 Premium 12 месяцев": ("Telegram Premium 12 месяцев", 2400)
    }
    
    item_name, price = item_map.get(message.text, ("", 0))
    
    order_text = f"""🛒 Заказ: {item_name}

💰 Цена: {price}₽
⚡ Мгновенная доставка

💬 Для заказа: {MANAGER_CONTACT}"""
    await message.answer(order_text, reply_markup=get_back_keyboard())

# Остальные категории
@dp.message(F.text == "🎮 GTA 5 RP")
async def show_gta(message: types.Message):
    text = f"""🎮 GTA 5 RP

Доступны аккаунты и игровая валюта.

💬 Для заказа напишите менеджеру: {MANAGER_CONTACT}"""
    await message.answer(text, reply_markup=get_back_keyboard())

@dp.message(F.text == "📺 YouTube")
async def show_youtube(message: types.Message):
    text = f"""📺 YouTube

Услуги, каналы, Premium подписки.

💬 Для заказа напишите менеджеру: {MANAGER_CONTACT}"""
    await message.answer(text, reply_markup=get_back_keyboard())

@dp.message(F.text == "📱 TikTok")
async def show_tiktok(message: types.Message):
    text = f"""📱 TikTok

Аккаунты и монеты для TikTok.

💬 Для заказа напишите менеджеру: {MANAGER_CONTACT}"""
    await message.answer(text, reply_markup=get_back_keyboard())

@dp.message(F.text == "🎁 NFT Подарки")
async def show_nft_category(message: types.Message):
    nft_text = f"""🎁 NFT Подарки

Уникальные цифровые подарки для ваших друзей!

🎨 Для заказа и просмотра ассортимента
💬 напишите менеджеру: {MANAGER_CONTACT}

📸 Вам отправят фото и видео доступных NFT"""
    await message.answer(nft_text, reply_markup=get_back_keyboard())

# ==================== 💳 БАЛАНС ====================
@dp.message(F.text == "💳 Баланс")
async def show_balance(message: types.Message):
    balance = await db.get_user_balance(message.from_user.id)
    referrals_count, total_earned = await db.get_referral_stats(message.from_user.id)
    
    balance_text = f"""💰 Ваш баланс:

💵 Баланс: {balance:.2f} руб.
👥 Приглашено друзей: {referrals_count}
🎁 Заработано: {total_earned:.2f} руб.

💌 Для вывода: {MANAGER_CONTACT}"""
    await message.answer(balance_text, reply_markup=get_main_keyboard())

# ==================== 💰 РЕФЕРАЛЬНАЯ СИСТЕМА ====================
@dp.message(F.text == "💰 Реферальная система")
async def show_referral(message: types.Message):
    referral_code = await db.get_referral_code(message.from_user.id)
    bot_username = (await bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    referrals_count, total_earned = await db.get_referral_stats(message.from_user.id)
    
    referral_text = f"""💎 Реферальная система

🔗 Ваша реферальная ссылка:
`{referral_link}`

📊 Статистика:
• 👥 Приглашено: {referrals_count}
• 💵 Заработано: {total_earned:.2f} руб.
• 🎁 Бонус за друга: {REFERRAL_BONUS} руб.

💌 Приглашайте друзей и получайте бонусы!"""
    await message.answer(referral_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

# ==================== 📞 ИНФОРМАЦИЯ ====================
@dp.message(F.text == "ℹ️ Помощь")
async def show_help(message: types.Message):
    help_text = f"""❓ Помощь по боту

🛒 Каталог - товары по играм и соцсетям
💰 Реферальная система - приглашайте друзей
💳 Баланс - ваш баланс и статистика
📞 Контакты - связь с менеджером

⚡ Быстрая доставка
🔒 Безопасные платежи
💬 Поддержка 24/7

💌 По всем вопросам: {MANAGER_CONTACT}"""
    await message.answer(help_text, reply_markup=get_main_keyboard())

@dp.message(F.text == "📞 Контакты")
async def show_contacts(message: types.Message):
    contacts_text = f"""📞 Контакты

💬 Менеджер: {MANAGER_CONTACT}
⏰ Время ответа: 5-15 минут
🕐 Работаем: круглосуточно

💌 Пишите по любым вопросам!"""
    await message.answer(contacts_text, reply_markup=get_main_keyboard())

# ==================== 🔙 НАЗАД ====================
@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: types.Message):
    await message.answer("🔙 Главное меню:", reply_markup=get_main_keyboard())

# ==================== 📢 РАССЫЛКА ====================
async def daily_broadcast():
    """Ежедневная рассылка в 13:00"""
    while True:
        now = datetime.now(pytz.timezone('Europe/Moscow'))
        target_time = now.replace(hour=13, minute=0, second=0, microsecond=0)
        
        if now >= target_time:
            target_time += timedelta(days=1)
        
        wait_seconds = (target_time - now).total_seconds()
        logger.info(f"⏰ Следующая рассылка через {wait_seconds/3600:.1f} часов")
        
        await asyncio.sleep(wait_seconds)
        
        # Выполняем рассылку
        user_ids = await db.get_all_users()
        logger.info(f"📢 Начинаем рассылку для {len(user_ids)} пользователей")
        
        success = 0
        errors = 0
        
        broadcast_text = """Привет! Ждем твоих покупок 🛒

Здесь ты найдешь:
• 🎮 Игровые аккаунты: От прокачанных персонажей до редких скинов – найди то, что тебе нужно!
• 💰 Игровая валюта: Ускорь свой прогресс и получи преимущество над соперниками.
• 🚀 Моментальная доставка: Получи свой заказ мгновенно после оплаты.
• 🛡️ Безопасность: Мы гарантируем надежность и безопасность всех сделок.

💎 Актуальные предложения:
• Standoff 2: голда от 0.7₽
• Brawl Stars: гемы и Brawl Pass
• Telegram: звезды и Premium
• Discord: Nitro от 70₽

🎁 Не упусти выгодные предложения!"""
        
        for user_id in user_ids:
            try:
                await bot.send_message(user_id, broadcast_text)
                success += 1
                await asyncio.sleep(0.1)  # Задержка между сообщениями
            except Exception as e:
                errors += 1
                logger.error(f"❌ Ошибка рассылки для {user_id}: {e}")
        
        logger.info(f"✅ Рассылка завершена. Успешно: {success}, Ошибок: {errors}")

# ==================== 🔄 АВТОМАТИЧЕСКОЕ РЕЗЕРВНОЕ КОПИРОВАНИЕ ====================
async def auto_backup():
    """Автоматическое резервное копирование каждые 24 часа"""
    while True:
        await asyncio.sleep(24 * 60 * 60)  # 24 часа
        logger.info("🔄 Запуск автоматического резервного копирования...")
        await db.backup_database()

# ==================== 🚀 ЗАПУСК БОТА ====================
async def main():
    logger.info("🚀 Запуск бота RichMarket...")
    
    # Инициализация базы данных
    try:
        await db.init_db()
        logger.info("✅ База данных готова к работе")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка инициализации БД: {e}")
        return
    
    users_count = await db.get_users_count()
    logger.info(f"👥 Пользователей в базе: {users_count}")
    
    # Запускаем фоновые задачи
    asyncio.create_task(daily_broadcast())
    asyncio.create_task(auto_backup())
    
    # Удаляем вебхук и запускаем поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
