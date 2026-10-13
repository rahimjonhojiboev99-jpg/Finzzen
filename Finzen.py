import os
import asyncio
import logging
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
import aiosqlite
from aiohttp import web

# Токен берется из переменных окружения Render или вставляется напрямую
TOKEN = os.getenv("8936818322:AAHH-kXtO4wZOgBeSN9YyqkVGBnpnTn-aFw")
DB_NAME = "finzen.db"

# --- БЛОК РАБОТЫ С БАЗОЙ ДАННЫХ ---

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def add_transaction(user_id: int, amount: float, category: str, trans_type: str = "expense"):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO transactions (user_id, amount, category, type) VALUES (?, ?, ?, ?)",
            (user_id, amount, category, trans_type)
        )
        await db.commit()

async def get_monthly_stats(user_id: int):
    now = datetime.now()
    start_of_month = f"{now.year}-{now.month:02d}-01 00:00:00"

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT category, SUM(amount) 
            FROM transactions 
            WHERE user_id = ? AND type = 'expense' AND created_at >= ?
            GROUP BY category
        """, (user_id, start_of_month)) as cursor:
            expenses = await cursor.fetchall()

        async with db.execute("""
            SELECT SUM(amount) 
            FROM transactions 
            WHERE user_id = ? AND type = 'income' AND created_at >= ?
        """, (user_id, start_of_month)) as cursor:
            income_res = await cursor.fetchone()
            total_income = income_res[0] if income_res[0] is not None else 0.0

    total_expense = sum(item[1] for item in expenses)
    return total_income, total_expense, expenses

async def clear_user_stats(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
        await db.commit()

# --- БЛОК TELEGRAM БОТА ---

bot = Bot(token=TOKEN)
dp = Dispatcher()

EXPENSE_CATEGORIES = [
    "🍔 Еда", "🚕 Транспорт", "🏠 ЖКХ/Дом",
    "🎉 Развлечения", "🛒 Покупки", "💊 Здоровье", "📦 Другое"
]

def get_main_keyboard():
    kb = [
        [InlineKeyboardButton(text="📊 Статистика за месяц", callback_data="stats")],
        [InlineKeyboardButton(text="🗑 Сбросить статистику", callback_data="confirm_reset")],
        [InlineKeyboardButton(text="🧘‍♂️ Инструкция (Дзен)", callback_data="help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_confirm_reset_keyboard():
    kb = [
        [
            InlineKeyboardButton(text="✅ Да, очистить", callback_data="do_reset"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reset")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_categories_keyboard(amount: float):
    buttons = []
    for cat in EXPENSE_CATEGORIES:
        buttons.append([InlineKeyboardButton(text=cat, callback_data=f"add_exp:{amount}:{cat}")])
    buttons.append([InlineKeyboardButton(text="💰 Это ДОХОД", callback_data=f"add_inc:{amount}:Доход")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"Привет, {message.from_user.first_name}! 🧘‍♂️💰\n\n"
        "Добро пожаловать в **FinZen** — твой персональный финансовый дзен.\n\n"
        "**Как вести учет:**\n"
        "Отправь сумму и краткое описание в чат:\n"
        "• `50 кофе` или просто `50`\n"
        "• `3000 зарплата`\n\n"
        "Я помогу разложить все по категориям!",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(Command("stats"))
@dp.callback_query(F.data == "stats")
async def show_stats(event: Message | CallbackQuery):
    user_id = event.from_user.id
    total_income, total_expense, expenses = await get_monthly_stats(user_id)
    balance = total_income - total_expense

    text = "📊 **Финансовая статистика FinZen за месяц:**\n\n"
    text += f"🟢 **Доходы:** {total_income:,.2f} сомонӣ\n"
    text += f"🔴 **Расходы:** {total_expense:,.2f} сомонӣ\n"
    text += f"💳 **Баланс:** {balance:,.2f} сомонӣ\n\n"

    if expenses:
        text += "**Детализация расходов:**\n"
        for category, amount in expenses:
            percent = (amount / total_expense * 100) if total_expense > 0 else 0
            text += f"• {category}: {amount:,.2f} сомонӣ ({percent:.1f}%)\n"
    else:
        text += "_Расходов в этом месяце пока не зафиксировано._"

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")
        await event.answer()
    else:
        await event.answer(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

@dp.callback_query(F.data == "confirm_reset")
async def ask_confirm_reset(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚠️ **Вы уверены, что хотите полностью сбросить вашу статистику?**\n\n"
        "Все сохраненные доходы и расходы будут удалены безвозвратно.",
        reply_markup=get_confirm_reset_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "do_reset")
async def process_reset(callback: CallbackQuery):
    await clear_user_stats(callback.from_user.id)
    await callback.message.edit_text(
        "🗑 **Статистика успешно очищена!**\n\nВы можете начать учет заново.",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer("Данные удалены")

@dp.callback_query(F.data == "cancel_reset")
async def cancel_reset(callback: CallbackQuery):
    await callback.message.edit_text(
        "Очистка отменена.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    await callback.message.edit_text(
        "🧘‍♂️ **Концепция FinZen:**\n\n"
        "1. Записывай транзакции сразу после покупки.\n"
        "2. Формат: отправь число (например `20`) и выбери категорию.\n"
        "3. В конце месяца анализируй баланс по кнопке **Статистика**.",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("Отменено.")

@dp.message(F.text)
async def process_amount_input(message: Message):
    match = re.match(r"^(\d+(?:[\.,]\d+)?)\s*(.*)", message.text.strip())
    
    if not match:
        await message.answer(
            "Введите сумму числом (например, `50` или `25.50 обед`).",
            parse_mode="Markdown"
        )
        return

    amount_str = match.group(1).replace(",", ".")
    amount = float(amount_str)
    note = match.group(2).strip()

    caption = f"Сумма: **{amount:,.2f} сомонӣ**"
    if note:
        caption += f"\nЗаметка: _{note}_"
    caption += "\n\nВыберите категорию:"

    await message.answer(
        caption,
        reply_markup=get_categories_keyboard(amount),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("add_exp:"))
async def save_expense(callback: CallbackQuery):
    _, amount_str, category = callback.data.split(":", 2)
    amount = float(amount_str)
    
    await add_transaction(callback.from_user.id, amount, category, trans_type="expense")
    
    await callback.message.edit_text(
        f"✅ Сохранено: **-{amount:,.2f} сомонӣ** в категорию **{category}**",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("add_inc:"))
async def save_income(callback: CallbackQuery):
    _, amount_str, category = callback.data.split(":", 2)
    amount = float(amount_str)
    
    await add_transaction(callback.from_user.id, amount, category, trans_type="income")
    
    await callback.message.edit_text(
        f"🎉 Сохранено: **+{amount:,.2f} сомонӣ** в **Доходы**",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

# --- ВЕБ-СЕРВЕР ДЛЯ РАБОТЫ НА RENDER (FREE WEB SERVICE) ---

async def handle_ping(request):
    return web.Response(text="FinZen Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- ЗАПУСК ---

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем фейковый веб-сервер, чтобы Render не закрывал процесс
    await start_web_server()
    
    print("\n--- FinZen Bot успешно запущен на Render (Web Service)! ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
  
