import asyncio
import logging
import re
from dataclasses import dataclass
from enum import IntEnum

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from config import ADMIN_IDS, ADMIN_LOG_CHAT_ID, BOT_TOKEN, GUARANTOR_ID, GUARANTOR_LABEL as CONFIG_GUARANTOR_LABEL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

router = Router()

# Гарант / аккаунт, на который передаётся NFT
GUARANTOR = GUARANTOR_ID
GUARANTOR_LABEL = CONFIG_GUARANTOR_LABEL

# Роль аккаунта (показывается в /rights)
ROLE_LABEL = "work"


@dataclass
class OfferDraft:
    recipient_id: int
    recipient_name: str
    link: str = ""
    slug: str = ""
    amount: str = ""

    @property
    def display(self) -> str:
        pieces = [p for p in (self.link, self.slug) if p]
        return "\n".join(pieces) if pieces else "(без ссылки)"


class OfferFlow(StatesGroup):
    waiting_recipient = State()
    waiting_gift = State()
    waiting_amount = State()


class Decision(IntEnum):
    ACCEPTED = 1
    REJECTED = 2


SLAG_RE = r"t\.me/nft/([A-Za-z0-9_\-]+)"


def cb(decision: Decision, offer_id: int) -> str:
    return f"{int(decision)}:{offer_id}"


def parse_cb(data: str) -> tuple[Decision, int]:
    d, oid = data.split(":", 1)
    return Decision(int(d)), int(oid)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def decision_kb(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardBuilder().button(
        text="✅ Принять", callback_data=cb(Decision.ACCEPTED, offer_id)
    ).button(
        text="❌ Отклонить", callback_data=cb(Decision.REJECTED, offer_id)
    ).as_markup()


async def notify_admins(bot: Bot, text: str):
    for uid in ADMIN_IDS:
        try:
            await bot.send_message(uid, text)
        except Exception as exc:
            logger.warning("не смог уведомить админа %s: %s", uid, exc)
    if ADMIN_LOG_CHAT_ID and ADMIN_LOG_CHAT_ID not in ADMIN_IDS:
        try:
            await bot.send_message(ADMIN_LOG_CHAT_ID, text)
        except Exception as exc:
            logger.warning("логочат недоступен: %s", exc)


@router.message(Command("start"))
async def cmd_start(message: Message):
    if is_admin(message.from_user.id):
        return await message.answer(
            "Оффер-бот — админ/гарант\n\n"
            "/offer — предложить выкуп подарка\n"
            "/rights — проверить права\n"
            "/recipients — список получателей\n"
            "/set_target — сменить аккаунт гаранта"
        )
    await message.answer(
        "Оффер-бот\n\n"
        "/offer — предложить выкуп подарка\n"
        "/rights — проверить, выданы ли боту все права"
    )


@router.message(Command("rights"))
async def cmd_rights(message: Message):
    # Честная проверка настроек + напоминание. API не даёт боту узнать реальные
    # права в бизнес-чате, поэтому проверяем конфиг и подсказываем.
    if not BOT_TOKEN:
        return await message.answer("⚠️ BOT_TOKEN не задан.")
    if not ADMIN_IDS:
        return await message.answer("⚠️ ADMIN_IDS не задан.")
    lines = [
        "Бот подключён. Роль аккаунта: " + ROLE_LABEL,
        "",
        "Права:",
        "✅ Отвечать на сообщения (отправка офферов)",
        "✅ Видеть подарки и звёзды (лог поступления подарка)",
        "",
        "Убедись, что всё это выдано в настройках:",
        "Настройки → Telegram для бизнеса → Чат-боты.",
        "Автоматически бот проверить выдачу прав в бизнес-чате не может.",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("recipients"))
async def cmd_recipients(message: Message):
    if not is_admin(message.from_user.id):
        return
    rows = db.get_recipients()
    if not rows:
        return await message.answer("Получателей пока нет. Пусть клиенты нажмут /start боту.")
    text = "\n".join(f"{name}: <code>{uid}</code>" for uid, name in rows)
    await message.answer("Получатели:\n" + text)


@router.message(Command("set_target"))
async def cmd_set_target(message: Message, command: CommandObject):
    global GUARANTOR, GUARANTOR_LABEL
    if not is_admin(message.from_user.id):
        return
    args = (command.args or "").strip().split()
    if not args:
        return await message.answer("Формат: /set_target &lt;ID&gt; [метку]")
    GUARANTOR = args[0]
    GUARANTOR_LABEL = " ".join(args[1:]) or args[0]
    await message.answer(f"Аккаунт гаранта: {GUARANTOR} ({GUARANTOR_LABEL}).")


@router.message(Command("offer"))
async def cmd_offer(message: Message, state: FSMContext):
    await state.set_state(OfferFlow.waiting_recipient)
    await message.answer(
        "Оффер на выкуп. Шаг 1/4 — введи получателя (продавца):\n"
        "его @username (например, @walt) или числовой ID."
    )


@router.message(OfferFlow.waiting_recipient)
async def on_recipient(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        return await message.answer("Введи @username или ID получателя.")
    recipient = text if text.startswith("@") else text
    await state.update_data(draft=OfferDraft(recipient_id=recipient, recipient_name=recipient))
    await state.set_state(OfferFlow.waiting_gift)
    await message.answer(
        f"Вы отправили {recipient}. Получатель: {recipient}\n\n"
        "Шаг 2/4 — пришли подарок: ссылку https://t.me/nft/..., "
        "слаг или название текстом."
    )


@router.message(OfferFlow.waiting_gift)
async def on_gift(message: Message, state: FSMContext):
    text = (message.text or message.caption or "").strip()
    if not text:
        return await message.answer("Пришли ссылку, слаг или название gift.")
    data = await state.get_data()
    draft: OfferDraft = data["draft"]
    m = re.search(SLAG_RE, text)
    draft.slug = m.group(1) if m else text
    draft.link = text
    await state.update_data(draft=draft)
    await state.set_state(OfferFlow.waiting_amount)
    await message.answer(f"{draft.slug}\n\nШаг 3/4 — сумма (число):")


@router.message(OfferFlow.waiting_amount)
async def on_amount(message: Message, state: FSMContext, bot: Bot):
    amount = (message.text or "").strip()
    if not amount:
        return await message.answer("Введи сумму числом.")
    data = await state.get_data()
    draft: OfferDraft = data["draft"]
    draft.amount = amount

    offer_id = db.add_offer(
        recipient_id=draft.recipient_id,
        link=draft.link,
        slug=draft.slug,
        amount=draft.amount,
    )

    sent = False
    try:
        await bot.send_message(
            draft.recipient_id,
            f"{draft.display}\n💰 {draft.amount} звёзд\n\nПринять или отклонить?",
            reply_markup=decision_kb(offer_id),
        )
        sent = True
    except Exception as exc:
        logger.error("оффер %s не доставлен: %s", draft.recipient_id, exc)

    await state.clear()
    status = "отправлен продавцу ✅" if sent else "НЕ отправлен ❌ (получатель не начал диалог с ботом?)"
    await message.answer(f"Оффер #{offer_id} {status} → {draft.recipient_name}.\nСумма: {draft.amount}.")

    await notify_admins(
        bot,
        f"🧾 Новый оффер #{offer_id}:\n{draft.recipient_name}\n{draft.display}\nСумма: {draft.amount}",
    )


@router.callback_query(F.data.regexp(r"^[12]:\d+$"))
async def on_decision(callback: CallbackQuery, bot: Bot):
    decision, offer_id = parse_cb(callback.data)
    user = callback.from_user
    db.record_resolution(offer_id, user.id, user.username, decision.name)

    if decision == Decision.ACCEPTED:
        await callback.message.edit_text(
            "✅ Принято. Передай NFT гаранту на профиль <code>8090009094</code>.",
            reply_markup=None,
        )
        extra = (
            f"Передай NFT гаранту: ID {GUARANTOR} ({GUARANTOR_LABEL}).\n"
            "Выбери подарок в своём профиле и отправь его этому ID."
        )
    else:
        await callback.message.edit_text("❌ Отклонено.", reply_markup=None)
        extra = "Решение: отклонено."

    await callback.answer("Спасибо!", show_alert=False)

    await notify_admins(
        bot,
        f"🗳 {user.username or user.id} ПРИНЯЛ оффер #{offer_id}.\n"
        f"{GUARANTOR_LABEL}\n{extra}",
    )


async def main():
    db.init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot, handle_signals=False)


if __name__ == "__main__":
    asyncio.run(main())