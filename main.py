import asyncio
import os
import network
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery,
    BufferedInputFile
)
from dotenv import load_dotenv
import database as db

# Загрузка переменных
load_dotenv()
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

# Сюда вставь токен из BotFather (раздел Payments), если хочешь принимать рубли
# Если хочешь тестить "Звездами", замени RUB на XTR и очисти токен
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN", "")


# Состояния бота
class PhotoProcess(StatesGroup):
    waiting_for_photo = State()
    waiting_for_model = State()
    waiting_for_prompt = State()


# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📸 Начать фотосессию")],
        [KeyboardButton(text="👤 Мой баланс"), KeyboardButton(text="💳 Пополнить")]
    ], resize_keyboard=True)


def get_cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="❌ Отменить")]
    ], resize_keyboard=True)


def get_model_inline():
    buttons = [
        [InlineKeyboardButton(text="🍌 NanoBanana (5 ген.)", callback_data="model_nanabanana")],
        [InlineKeyboardButton(text="🌊 SeaDream (10 ген.)", callback_data="model_seadream")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я твой личный AI-фотограф.\n\n"
        "Отправь мне фото, выбери стиль и получи шедевр!",
        reply_markup=get_main_kb()
    )


@dp.message(F.text == "❌ Отменить")
async def cancel_text_action(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_main_kb())


@dp.message(F.text == "👤 Мой баланс")
async def check_balance(message: types.Message):
    user_id = message.from_user.id
    balance = db.get_balance(user_id)
    await message.answer(f"💰 Ваш баланс: **{balance}** генераций.", parse_mode="Markdown")


@dp.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    balance = db.get_balance(user_id)

    if balance < 5:  # Минимум для самой дешевой нейронки
        return await message.answer(f"❌ Недостаточно генераций (нужно минимум 5). Ваш баланс: {balance}")

    await message.answer("Пришлите фотографию, которую хотите преобразить:", reply_markup=get_cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_photo)


@dp.message(PhotoProcess.waiting_for_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("Отлично! Теперь выбери нейросеть (у них разная стоимость):", reply_markup=get_model_inline())
    await state.set_state(PhotoProcess.waiting_for_model)


@dp.callback_query(F.data.startswith("model_"))
async def process_model_callback(callback: types.CallbackQuery, state: FSMContext):
    model = callback.data.split("_")[1]
    await state.update_data(chosen_model=model)

    await callback.message.edit_text(
        f"✅ Выбрана модель: **{model.upper()}**.\n\nТеперь напиши промпт (желаемый стиль):",
        parse_mode="Markdown"
    )

    # Чтобы кнопка "❌ Отменить" реально была доступна на этапе ввода промпта
    await callback.message.answer("✍️ Введите промпт (описание желаемого стиля):", reply_markup=get_cancel_kb())

    await state.set_state(PhotoProcess.waiting_for_prompt)
    await callback.answer()


@dp.callback_query(F.data == "cancel")
async def cancel_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Действие отменено.", reply_markup=get_main_kb())
    await callback.answer()


@dp.message(PhotoProcess.waiting_for_prompt)
async def process_generation(message: types.Message, state: FSMContext):
    if message.text == "❌ Отменить":
        return await cancel_text_action(message, state)

    user_id = message.from_user.id
    user_data = await state.get_data()

    model = user_data.get("chosen_model")
    prompt = message.text

    # 1) Проверка цен и баланса
    costs = {"nanabanana": 5, "seadream": 10}
    cost = costs.get(model, 5)
    balance = db.get_balance(user_id)

    if balance < cost:
        await state.clear()
        return await message.answer(f"❌ Нужно {cost} ген. Ваш баланс: {balance}", reply_markup=get_main_kb())

    status_msg = await message.answer(
        f"🚀 Модель **{model}** создает шедевр... Пожалуйста, подождите.",
        parse_mode="Markdown"
    )

    # 2) Получаем ссылку на фото из Telegram
    file = await bot.get_file(user_data["photo_id"])
    photo_url = f"https://api.telegram.org/file/bot{os.getenv('BOT_TOKEN')}/{file.file_path}"

    # 3) Вызываем AI (network.py должен вернуть (bytes, ext))
    img_bytes, ext = await network.process_with_ai(photo_url, prompt, model)

    if img_bytes:
        # Списываем баланс только при успешной генерации
        for _ in range(cost):
            db.use_generation(user_id)

        new_balance = db.get_balance(user_id)

        photo_file = BufferedInputFile(img_bytes, filename=f"result.{ext or 'png'}")
        await message.answer_photo(
            photo=photo_file,
            caption=f"✅ Готово!\n\nСтиль: {model}\nПромпт: {prompt}\n💰 Остаток: {new_balance} ген.",
            reply_markup=get_main_kb()
        )
    else:
        await message.answer("❌ Ошибка нейросети. Попробуйте другой промпт или фото. Баланс сохранен.")

    await status_msg.delete()
    await state.clear()


# --- ПЛАТЕЖИ ---

@dp.message(F.text == "💳 Пополнить")
async def buy_process(message: types.Message):
    buy_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 ген. — 149₽", callback_data="pay_10_149")],
        [InlineKeyboardButton(text="25 ген. — 375₽", callback_data="pay_25_375")],
        [InlineKeyboardButton(text="45 ген. — 675₽", callback_data="pay_45_675")],
        [InlineKeyboardButton(text="60 ген. — 900₽", callback_data="pay_60_900")]
    ])
    await message.answer("Выберите пакет генераций:", reply_markup=buy_kb)


@dp.callback_query(F.data.startswith("pay_"))
async def send_invoice(callback: types.CallbackQuery):
    _, count, price = callback.data.split("_")
    count, price = int(count), int(price)

    prices = [LabeledPrice(label=f"{count} генераций", amount=price * 100)]  # В копейках

    await callback.message.answer_invoice(
        title="Пополнение баланса",
        description=f"Пакет на {count} нейро-фотосессий",
        prices=prices,
        provider_token=PAYMENT_TOKEN,
        payload=f"refill_{count}",
        currency="RUB"
    )
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout_process(pre_checkout_q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    count = int(message.successful_payment.invoice_payload.split("_")[1])
    db.add_balance(message.from_user.id, count)
    await message.answer(f"✅ Успешно! Начислено {count} генераций.", reply_markup=get_main_kb())


# --- ЗАПУСК ---
async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
