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

# Инициализация хранилища
storage = MemoryStorage()

# --- [RENDER] Конфигурация из переменных окружения ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERNAMES = os.getenv("ADMIN_USERNAMES", "yesbeers,yyangpython").split(',')
MANAGER_CONTACT = os.getenv("MANAGER_CONTACT", "@managersrich")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@eweton")
REFERRAL_BONUS = float(os.getenv("REFERRAL_BONUS", 0.2))

# [RENDER] Путь к базе данных на персистентном диске Render
DATA_DIR = Path(os.getenv("DATA_DIR", "."))
DATABASE_PATH = DATA_DIR / "shop_bot.db"

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

# --- Инициализация бота и диспетчера ---
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=storage)  # Используем MemoryStorage

# --- Состояния FSM ---
class AdminStates(StatesGroup):
    select_category = State()
    select_item = State()
    enter_new_price = State()
    enter_new_name = State()

# --- Класс для работы с БД ---
class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
                        balance REAL DEFAULT 0, referral_code TEXT UNIQUE, referrer_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                # ... остальной код инициализации БД без изменений ...
                
# Остальной код остается без изменений...
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, name TEXT NOT NULL,
                        price INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (category_id) REFERENCES categories (id)
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS referrals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER,
                        bonus_paid BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                    logger.info(f"Добавлен новый пользователь: {user_id} {username}")
                    if referrer_id:
                        logger.info(f"Пользователь {user_id} пришел по приглашению от {referrer_id}. Начисляем бонус.")
                        self._add_referral_bonus(referrer_id, user_id, conn)
                else:
                    cursor.execute(
                        'UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE user_id = ?',
                        (username, first_name, last_name, user_id)
                    )
                    logger.info(f"Обновлен существующий пользователь: {user_id}")
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя {user_id}: {e}", exc_info=True)

    def _add_referral_bonus(self, referrer_id: int, referred_id: int, conn: sqlite3.Connection):
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (referrer_id,))
            if not cursor.fetchone():
                logger.error(f"Реферер {referrer_id} не найден в базе")
                return
            cursor.execute('SELECT id FROM referrals WHERE referred_id = ?', (referred_id,))
            if cursor.fetchone():
                logger.info(f"Бонус для {referred_id} уже был начислен ранее.")
                return
            cursor.execute('INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)', (referrer_id, referred_id))
            cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (REFERRAL_BONUS, referrer_id))
            logger.info(f"Бонус {REFERRAL_BONUS} руб. начислен пользователю {referrer_id} за приглашение {referred_id}")
        except Exception as e:
            logger.error(f"Ошибка при начислении реферального бонуса: {e}", exc_info=True)
            conn.rollback()

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
            
    def get_users_count(self) -> int:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM users')
                return cursor.fetchone()[0] or 0
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
    
    # [ДОБАВЛЕНО] Другие методы для работы с БД, если они понадобятся
    def get_category_by_name(self, category_name: str) -> tuple:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name FROM categories WHERE name = ?', (category_name,))
            return cursor.fetchone()


db = Database(DATABASE_PATH)

# --- Вспомогательные функции ---
async def check_subscription(user_id: int) -> bool:
    if not REQUIRED_CHANNEL or REQUIRED_CHANNEL == "@": return True
    try:
        chat_member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.warning(f"Не удалось проверить подписку для {user_id} на {REQUIRED_CHANNEL}: {e}. Доступ разрешен.")
        return True

def is_admin(username: str) -> bool:
    if not username: return False
    return username.lstrip('@') in ADMIN_USERNAMES

# --- [ДОБАВЛЕНО] Восстановленные функции клавиатур ---
def get_main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Каталог")],
        [KeyboardButton(text="Реферальная система"), KeyboardButton(text="Баланс")],
        [KeyboardButton(text="Помощь"), KeyboardButton(text="Контакты")]
    ], resize_keyboard=True)

def get_catalog_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="GTA 5 RP"), KeyboardButton(text="Standoff 2")],
        [KeyboardButton(text="Brawl Stars"), KeyboardButton(text="Clash Royale")],
        [KeyboardButton(text="Roblox"), KeyboardButton(text="CS 2")],
        [KeyboardButton(text="Pubg Mobile"), KeyboardButton(text="PUBG (PC/Console)")],
        [KeyboardButton(text="Discord"), KeyboardButton(text="YouTube")],
        [KeyboardButton(text="TikTok"), KeyboardButton(text="Telegram")],
        [KeyboardButton(text="NFT Подарки"), KeyboardButton(text="Назад")]
    ], resize_keyboard=True)

def get_back_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True)

def get_items_keyboard(category_name: str):
    category = db.get_category_by_name(category_name)
    if not category: return get_back_keyboard()
    items = db.get_items_by_category(category[0])
    builder = ReplyKeyboardBuilder()
    for _, item_name, _ in items:
        builder.add(KeyboardButton(text=item_name))
    builder.adjust(2)
    builder.row(KeyboardButton(text="Назад"))
    return builder.as_markup(resize_keyboard=True)

def get_telegram_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="21 звезда"), KeyboardButton(text="50 звезд"), KeyboardButton(text="100 звезд")],
        [KeyboardButton(text="Premium 1 месяц"), KeyboardButton(text="Premium 3 месяца")],
        [KeyboardButton(text="Premium 6 месяцев"), KeyboardButton(text="Premium 12 месяцев")],
        [KeyboardButton(text="Назад")]
    ], resize_keyboard=True)

def get_standoff_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Голда"), KeyboardButton(text="Аккаунт"), KeyboardButton(text="Донат")],
        [KeyboardButton(text="Буст"), KeyboardButton(text="Кланы"), KeyboardButton(text="Софт")],
        [KeyboardButton(text="Назад")]
    ], resize_keyboard=True)
    
# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if not await check_subscription(message.from_user.id):
        kb = InlineKeyboardBuilder()
        kb.add(InlineKeyboardButton(text="Подписаться", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}"))
        kb.add(InlineKeyboardButton(text="Проверить", callback_data="check_sub"))
        await message.answer(
            f"Для использования бота, пожалуйста, подпишитесь на наш канал. После подписки нажмите 'Проверить'.",
            reply_markup=kb.as_markup()
        )
        return

    referrer_id = None
    args = message.text.split()
    if len(args) > 1:
        referral_code = args[1]
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
            result = cursor.fetchone()
            if result and result[0] != message.from_user.id:
                referrer_id = result[0]
    
    db.add_user(
        message.from_user.id, message.from_user.username,
        message.from_user.first_name, message.from_user.last_name or "",
        referrer_id
    )
    await message.answer("Добро пожаловать! Выберите действие:", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "check_sub")
async def handle_check_sub(callback: types.CallbackQuery, state: FSMContext):
    if await check_subscription(callback.from_user.id):
        await callback.answer("Спасибо за подписку!", show_alert=False)
        await callback.message.delete()
        await cmd_start(callback.message, state)
    else:
        await callback.answer("Вы все еще не подписаны. Пожалуйста, подпишитесь и попробуйте снова.", show_alert=True)

@dp.message(Command("info"))
async def cmd_info(message: types.Message):
    if not is_admin(message.from_user.username): return
    await message.answer(f"Пользователей в боте: {db.get_users_count()}")

@dp.message(Command("debug"))
async def cmd_debug(message: types.Message):
    if not is_admin(message.from_user.username): return
    db_exists = DATABASE_PATH.exists()
    db_size = DATABASE_PATH.stat().st_size if db_exists else 0
    debug_info = (
        f"<b>Отладка:</b>\n"
        f"Файл БД: <code>{DATABASE_PATH}</code>\n"
        f"Файл существует: <code>{db_exists}</code>\n"
        f"Размер БД: <code>{db_size}</code> байт\n"
        f"Всего пользователей: <code>{db.get_users_count()}</code>"
    )
    await message.answer(debug_info)

# --- [ДОБАВЛЕНО] Обработчики админ-панели ---
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.username):
        return await message.answer("Нет прав доступа.")
    
    builder = InlineKeyboardBuilder()
    for cat_id, cat_name in db.get_categories():
        builder.button(text=cat_name, callback_data=f"admin_cat_{cat_id}")
    builder.adjust(2)
    await message.answer("Админ-панель. Выберите категорию для редактирования:", reply_markup=builder.as_markup())
    await state.set_state(AdminStates.select_category)

@dp.callback_query(AdminStates.select_category, F.data.startswith("admin_cat_"))
async def admin_select_category(callback: types.CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[2])
    await state.update_data(category_id=category_id)
    
    builder = InlineKeyboardBuilder()
    items = db.get_items_by_category(category_id)
    if not items:
        await callback.answer("В этой категории нет товаров.", show_alert=True)
        return

    for item_id, item_name, item_price in items:
        builder.button(text=f"{item_name} ({item_price} руб.)", callback_data=f"admin_item_{item_id}")
    builder.adjust(1)
    await callback.message.edit_text("Выберите товар для редактирования:", reply_markup=builder.as_markup())
    await state.set_state(AdminStates.select_item)

@dp.callback_query(AdminStates.select_item, F.data.startswith("admin_item_"))
async def admin_select_item(callback: types.CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split("_")[2])
    await state.update_data(item_id=item_id)
    item = db.get_item_by_id(item_id)
    if not item:
        await callback.answer("Товар не найден!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Изменить цену", callback_data="admin_edit_price")
    builder.button(text="Изменить название", callback_data="admin_edit_name")
    builder.button(text="<< Назад", callback_data="admin_back_to_cats")
    await callback.message.edit_text(f"Выбран товар: <b>{item[1]}</b>\nТекущая цена: <b>{item[2]} руб.</b>\n\nЧто вы хотите сделать?", reply_markup=builder.as_markup())

@dp.callback_query(AdminStates.select_item, F.data == "admin_edit_price")
async def admin_prompt_price(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите новую цену для товара (только цифры):")
    await state.set_state(AdminStates.enter_new_price)

@dp.message(AdminStates.enter_new_price)
async def admin_update_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Ошибка. Введите только цифры. Попробуйте еще раз.")
    
    data = await state.get_data()
    item_id = data.get("item_id")
    new_price = int(message.text)
    
    db.update_item_price(item_id, new_price)
    await message.answer(f"Цена товара успешно обновлена на <b>{new_price} руб.</b>")
    await state.clear()
    await cmd_admin(message, state) # Возвращаемся в начало админки

@dp.callback_query(AdminStates.select_item, F.data == "admin_back_to_cats")
async def admin_back_to_categories(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await cmd_admin(callback.message, state)


# --- Обработчики основного меню ---
@dp.message(F.text == "Каталог")
async def show_catalog(message: types.Message):
    await message.answer("Выберите категорию:", reply_markup=get_catalog_keyboard())

@dp.message(F.text == "Баланс")
@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    balance = db.get_user_balance(message.from_user.id)
    referrals_count, total_earned = db.get_referral_stats(message.from_user.id)
    balance_text = (
        f"<b>Ваш баланс:</b> {balance:.2f} руб.\n\n"
        f"<b>Статистика рефералов:</b>\n"
        f"Приглашено: {referrals_count} чел.\n"
        f"Заработано: {total_earned:.2f} руб.\n\n"
        f"Для вывода средств свяжитесь с менеджером: {MANAGER_CONTACT}"
    )
    await message.answer(balance_text, reply_markup=get_main_keyboard())

@dp.message(F.text == "Реферальная система")
async def show_referral(message: types.Message):
    referral_code = db.get_referral_code(message.from_user.id)
    bot_info = await bot.get_me()
    referral_link = f"https://t.me/{bot_info.username}?start={referral_code}"
    _, total_earned = db.get_referral_stats(message.from_user.id)
    
    referral_text = (
        f"<b>Приглашайте друзей и зарабатывайте!</b>\n\n"
        f"Вы получите <b>{REFERRAL_BONUS:.2f} руб.</b> за каждого друга, который запустит бота по вашей ссылке.\n\n"
        f"Ваша персональная ссылка:\n<code>{referral_link}</code>\n\n"
        f"Всего заработано: <b>{total_earned:.2f} руб.</b>"
    )
    await message.answer(referral_text, disable_web_page_preview=True)

@dp.message(F.text == "Помощь")
async def show_help(message: types.Message):
    await message.answer(f"По всем вопросам обращайтесь к менеджеру: {MANAGER_CONTACT}")

@dp.message(F.text == "Контакты")
async def show_contacts(message: types.Message):
    await message.answer(f"Наш менеджер: {MANAGER_CONTACT}\nВремя ответа: 5-15 минут.")

@dp.message(F.text == "Назад")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=get_main_keyboard())


# --- Обработчики категорий и товаров ---
@dp.message(F.text.in_([
    "GTA 5 RP", "Brawl Stars", "Clash Royale", "Roblox", "CS 2", 
    "Pubg Mobile", "PUBG (PC/Console)", "Discord", "YouTube", "TikTok"
]))
async def show_generic_category(message: types.Message):
    # Универсальный обработчик для категорий с товарами из БД
    await message.answer(f"Товары в категории «{message.text}»:", reply_markup=get_items_keyboard(message.text))

@dp.message(F.text == "Standoff 2")
async def show_standoff_category(message: types.Message):
    await message.answer("Товары в категории «Standoff 2»:", reply_markup=get_standoff_keyboard())

@dp.message(F.text == "Telegram")
async def show_telegram_category(message: types.Message):
    await message.answer("Товары в категории «Telegram»:", reply_markup=get_telegram_keyboard())

@dp.message(F.text == "NFT Подарки")
async def show_nft_category(message: types.Message):
    await message.answer(f"Для заказа NFT Подарков и просмотра ассортимента напишите менеджеру: {MANAGER_CONTACT}", reply_markup=get_back_keyboard())

# [ДОБАВЛЕНО] Обработчики для конкретных товаров (пример)
# Для товаров, которых нет в БД или с особой логикой
@dp.message(F.text.in_([
    "21 звезда", "50 звезд", "100 звезд", "Premium 1 месяц", "Premium 3 месяца", 
    "Premium 6 месяцев", "Premium 12 месяцев", "Голда", "Аккаунт", "Донат", "Буст", "Кланы", "Софт"
]))
async def handle_generic_item(message: types.Message):
    item_name = message.text
    # Здесь можно добавить логику цен из словаря или БД, если нужно
    # Для простоты, все отправляем к менеджеру
    order_text = f"Вы выбрали: <b>{item_name}</b>\n\nДля уточнения цены и оформления заказа, пожалуйста, напишите нашему менеджеру: {MANAGER_CONTACT}"
    await message.answer(order_text, reply_markup=get_back_keyboard())

# --- Основная функция запуска ---
async def main():
    logger.info("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())


