import os
import logging
import asyncio
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import database as db

router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))


class BroadcastStates(StatesGroup):
    waiting_for_content = State()
    confirm = State()


@router.message(Command("broadcast"))
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    await state.set_state(BroadcastStates.waiting_for_content)
    await message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Отправьте сообщение для рассылки:\n"
        "— Текст\n"
        "— Фото с подписью\n"
        "— Видео с подписью\n\n"
        "Для отмены: /cancel_broadcast",
        parse_mode="HTML"
    )


@router.message(Command("cancel_broadcast"))
async def broadcast_cancel(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("❌ Рассылка отменена.")


@router.message(BroadcastStates.waiting_for_content)
async def broadcast_get_content(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    content_data = {}

    if message.photo:
        content_data["type"] = "photo"
        content_data["file_id"] = message.photo[-1].file_id
        content_data["caption"] = message.caption or ""
    elif message.video:
        content_data["type"] = "video"
        content_data["file_id"] = message.video.file_id
        content_data["caption"] = message.caption or ""
    elif message.text:
        content_data["type"] = "text"
        content_data["text"] = message.text
    else:
        await message.answer("⚠️ Неподдерживаемый формат. Отправьте текст, фото или видео.")
        return

    await state.update_data(content=content_data)
    await state.set_state(BroadcastStates.confirm)

    preview = content_data.get("text") or content_data.get("caption") or "[медиа без подписи]"
    total_users = await db.get_users_count()

    await message.answer(
        f"📋 <b>Превью рассылки:</b>\n\n"
        f"{preview[:200]}\n\n"
        f"👥 Получателей: <b>{total_users}</b>\n\n"
        f"Отправить? Напишите <b>ДА</b> или /cancel_broadcast",
        parse_mode="HTML"
    )


@router.message(BroadcastStates.confirm)
async def broadcast_confirm(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if message.text and message.text.upper() != "ДА":
        await state.clear()
        await message.answer("❌ Рассылка отменена.")
        return

    data = await state.get_data()
    content = data.get("content")
    await state.clear()

    if not content:
        await message.answer("⚠️ Нет данных для рассылки.")
        return

    await message.answer("🚀 Рассылка запущена...")

    user_ids = await db.get_all_user_ids()
    sent = 0
    failed = 0

    for user_id in user_ids:
        try:
            if content["type"] == "text":
                await message.bot.send_message(
                    chat_id=user_id,
                    text=content["text"],
                    parse_mode="HTML"
                )
            elif content["type"] == "photo":
                await message.bot.send_photo(
                    chat_id=user_id,
                    photo=content["file_id"],
                    caption=content.get("caption"),
                    parse_mode="HTML"
                )
            elif content["type"] == "video":
                await message.bot.send_video(
                    chat_id=user_id,
                    video=content["file_id"],
                    caption=content.get("caption"),
                    parse_mode="HTML"
                )
            sent += 1
        except Exception as e:
            failed += 1
            logging.warning(f"⚠️ Не доставлено {user_id}: {e}")

        await asyncio.sleep(0.05)

    await message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📨 Доставлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>",
        parse_mode="HTML"
    )