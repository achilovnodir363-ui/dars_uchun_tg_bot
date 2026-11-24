"""Python Coding Arena — Telegram quiz bot (python-telegram-bot 22.x + PostgreSQL)."""
from __future__ import annotations

import html
import logging
import os
import re
import warnings

from dotenv import load_dotenv

load_dotenv()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.constants import ParseMode  # noqa: E402
from telegram.error import BadRequest, TelegramError  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    Defaults,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBUserWarning  # noqa: E402

import db  # noqa: E402

warnings.filterwarnings("ignore", message=r".*per_message.*", category=PTBUserWarning)
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("arena-bot")

TOKEN = os.getenv("TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

END = ConversationHandler.END
LETTERS = ("a", "b", "c", "d")
LOGIN_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")


# --------------------------------------------------------------------------- #
# Yordamchilar
# --------------------------------------------------------------------------- #
def esc(s) -> str:
    return html.escape(str(s))


def clip(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(r) for r in rows])


def is_admin(update: Update) -> bool:
    u = update.effective_user
    return bool(u and ADMIN_ID and u.id == ADMIN_ID)


async def has_access(update: Update) -> bool:
    if is_admin(update):
        return True
    return await db.get_user_by_tg(update.effective_user.id) is not None


async def show(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Callbackdan kelsa xabarni tahrirlaydi, aks holda yangi xabar yuboradi."""
    q = update.callback_query
    if q:
        try:
            await q.edit_message_text(text, reply_markup=markup)
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
    else:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE, admin: bool = True) -> bool:
    """Callback uchun umumiy tekshiruv (arenada emasmi, admin kerakmi)."""
    q = update.callback_query
    if ctx.user_data.get("quiz"):
        await q.answer("Siz arenadasiz. Chiqish uchun /cancel_arena", show_alert=True)
        return False
    if admin and not is_admin(update):
        await q.answer("Bu bo'lim faqat admin uchun", show_alert=True)
        return False
    await q.answer()
    return True


async def try_delete(update: Update) -> None:
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass


# --------------------------------------------------------------------------- #
# Ekranlar (menyular)
# --------------------------------------------------------------------------- #
async def sc_home(update, ctx):
    if is_admin(update):
        text = "👋 Salom, admin! Bo'limni tanlang:"
        rows = [[b("🛠 Admin panel", "nav:admin")], [b("🏟 Arena", "nav:play_list")]]
    else:
        user = await db.get_user_by_tg(update.effective_user.id)
        if user:
            text = f"👋 Salom, <b>{esc(user.username)}</b>!"
            rows = [[b("🏟 Arena", "nav:play_list")]]
        else:
            text = ("👋 Xush kelibsiz! Botdan foydalanish uchun ro'yxatdan o'ting.\n"
                    "Login va parolni admin beradi.")
            rows = [[b("📝 Ro'yxatdan o'tish", "reg:start")]]
    await show(update, text, InlineKeyboardMarkup(rows))


async def sc_admin(update, ctx):
    await show(update, "🛠 <b>Admin panel</b>", kb(
        [b("🏟 Coding Arena boshqaruvi", "nav:am")],
        [b("👥 Userlar boshqaruvi", "nav:um")],
        [b("🏠 Bosh menyu", "nav:home")],
    ))


async def sc_am(update, ctx):
    await show(update, "🏟 <b>Coding Arena boshqaruvi</b>", kb(
        [b("➕ Arena qo'shish", "conv:arena_add")],
        [b("📋 Arenalar ro'yxati", "nav:al")],
        [b("⬅️ Orqaga", "nav:admin")],
    ))


async def sc_al(update, ctx):
    rows = await db.list_arenas()
    text = ("📋 <b>Arenalar ro'yxati</b>\n🟢 ochiq · 🔴 yopiq (savollar soni qavsda)"
            if rows else "Hozircha arena yo'q.")
    buttons = [[b(f"{'🟢' if a.is_open else '🔴'} {clip(a.title, 40)} ({n})", f"nav:ar:{a.id}")]
               for a, n in rows]
    buttons.append([b("⬅️ Orqaga", "nav:am")])
    await show(update, text, InlineKeyboardMarkup(buttons))


async def sc_ar(update, ctx, aid):
    aid = int(aid)
    arena = await db.get_arena(aid)
    if not arena:
        await show(update, "Arena topilmadi.", kb([b("⬅️ Orqaga", "nav:al")]))
        return
    n = await db.count_questions(aid)
    status = "🟢 Ochiq" if arena.is_open else "🔴 Yopiq"
    text = f"🏟 <b>{esc(arena.title)}</b>\nHolat: {status}\nSavollar: {n} ta"
    toggle = (b("🔒 Yopish", f"act:toggle:{aid}") if arena.is_open
              else b("🔓 Ochish", f"act:toggle:{aid}"))
    await show(update, text, kb(
        [toggle],
        [b("➕ Savol qo'shish", f"conv:q_add:{aid}"), b("📋 Savollar ro'yxati", f"nav:qs:{aid}")],
        [b("🗑 Savol o'chirish", f"nav:qdel:{aid}"), b("🗑 Arenani o'chirish", f"ask:a:{aid}")],
        [b("⬅️ Orqaga", "nav:al")],
    ))


async def sc_qs(update, ctx, aid):
    aid = int(aid)
    arena = await db.get_arena(aid)
    if not arena:
        await show(update, "Arena topilmadi.", kb([b("⬅️ Orqaga", "nav:al")]))
        return
    qs = await db.get_questions(aid)
    if qs:
        body = "\n\n".join(
            f"<b>{i}.</b> {esc(clip(q.text, 150))}\n    ✅ To'g'ri javob: {q.correct_answer.upper()}"
            for i, q in enumerate(qs, 1)
        )
    else:
        body = "Hali savol yo'q."
    text = f"📋 <b>{esc(arena.title)}</b> — savollar ({len(qs)}):\n\n{body}"
    if len(text) > 3900:
        text = text[:3900] + "…"
    await show(update, text, kb([b("⬅️ Orqaga", f"nav:ar:{aid}")]))


async def sc_qdel(update, ctx, aid):
    aid = int(aid)
    qs = await db.get_questions(aid)
    text = "🗑 O'chirmoqchi bo'lgan savolni tanlang:" if qs else "O'chirish uchun savol yo'q."
    buttons = [[b(f"🗑 {i}. {clip(q.text, 35)}", f"ask:q:{q.id}")] for i, q in enumerate(qs, 1)]
    buttons.append([b("⬅️ Orqaga", f"nav:ar:{aid}")])
    await show(update, text, InlineKeyboardMarkup(buttons))


async def sc_um(update, ctx):
    await show(update, "👥 <b>Userlar boshqaruvi</b>", kb(
        [b("📋 Userlar ro'yxati", "nav:ul")],
        [b("➕ Yangi user qo'shish", "conv:u_add")],
        [b("⬅️ Orqaga", "nav:admin")],
    ))


async def sc_ul(update, ctx):
    users = await db.list_users()
    text = ("📋 <b>Userlar ro'yxati</b>\n🔗 — Telegramga ulangan"
            if users else "Hozircha user yo'q.")
    buttons = [[b(f"{'🔗' if u.telegram_id else '👤'} {clip(u.username, 25)} · {clip(u.login, 20)}",
                  f"nav:us:{u.id}")] for u in users]
    buttons.append([b("⬅️ Orqaga", "nav:um")])
    await show(update, text, InlineKeyboardMarkup(buttons))


async def sc_us(update, ctx, uid):
    uid = int(uid)
    u = await db.get_user(uid)
    if not u:
        await show(update, "User topilmadi.", kb([b("⬅️ Orqaga", "nav:ul")]))
        return
    tg = "ulangan 🔗" if u.telegram_id else "ulanmagan"
    text = (f"👤 <b>{esc(u.username)}</b>\nLogin: <code>{esc(u.login)}</code>\n"
            f"Telegram: {tg}")
    rows = [[b("✏️ Tahrirlash", f"nav:ue:{uid}"), b("🗑 O'chirish", f"ask:u:{uid}")]]
    if u.telegram_id:
        rows.append([b("🔓 Telegramni uzish", f"act:unlink:{uid}")])
    rows.append([b("⬅️ Orqaga", "nav:ul")])
    await show(update, text, InlineKeyboardMarkup(rows))


async def sc_ue(update, ctx, uid):
    uid = int(uid)
    await show(update, "✏️ Nimani o'zgartiramiz?", kb(
        [b("Ism", f"conv:u_edit:{uid}:username"), b("Login", f"conv:u_edit:{uid}:login")],
        [b("Parol", f"conv:u_edit:{uid}:password")],
        [b("⬅️ Orqaga", f"nav:us:{uid}")],
    ))


async def sc_play_list(update, ctx):
    if not await has_access(update):
        await show(update, "Avval ro'yxatdan o'ting.", kb([b("🏠 Bosh menyu", "nav:home")]))
        return
    rows = await db.list_arenas()
    text = ("🏟 <b>Coding Arenalar</b>\nKirish uchun arenani tanlang (🟢 ochiq · 🔴 yopiq):"
            if rows else "Hozircha arena yo'q.")
    buttons = [[b(f"{'🟢' if a.is_open else '🔴'} {clip(a.title, 40)}", f"play:{a.id}")] for a, _ in rows]
    buttons.append([b("🏠 Bosh menyu", "nav:home")])
    await show(update, text, InlineKeyboardMarkup(buttons))


SCREENS = {
    "home": sc_home, "admin": sc_admin, "am": sc_am, "al": sc_al, "ar": sc_ar, "qs": sc_qs,
    "qdel": sc_qdel, "um": sc_um, "ul": sc_ul, "us": sc_us, "ue": sc_ue, "play_list": sc_play_list,
}
PUBLIC_SCREENS = {"home", "play_list"}


async def nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    name, *args = q.data.split(":")[1:]
    if name not in SCREENS:
        await q.answer()
        return
    if not await guard(update, ctx, admin=name not in PUBLIC_SCREENS):
        return
    await SCREENS[name](update, ctx, *args)


async def nav_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Suhbat ichida menyu tugmasi bosilsa — suhbatni tugatib, menyuga o'tadi."""
    ctx.user_data.clear()
    await nav(update, ctx)
    return END


# --------------------------------------------------------------------------- #
# /start, /cancel
# --------------------------------------------------------------------------- #
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    log.info("/start: user_id=%s username=%s", u.id, u.username)
    if ctx.user_data.get("quiz"):
        await update.message.reply_text(
            "⚠️ Siz arenadasiz! Chiqish uchun /cancel_arena tugmasini bosing.")
        return
    await sc_home(update, ctx)


async def start_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await sc_home(update, ctx)
    return END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=kb([b("🏠 Bosh menyu", "nav:home")]))
    return END


CONV_FALLBACKS = [
    CommandHandler("cancel", cancel),
    CommandHandler("start", start_end),
    CallbackQueryHandler(nav_end, pattern=r"^nav:"),
]


# --------------------------------------------------------------------------- #
# Tasdiqlash / amallar
# --------------------------------------------------------------------------- #
async def act(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await guard(update, ctx, admin=True):
        return
    kind, what, raw_id = q.data.split(":")
    oid = int(raw_id)

    if kind == "act" and what == "toggle":
        if await db.toggle_arena(oid) is None:
            await show(update, "Arena topilmadi.", kb([b("⬅️ Orqaga", "nav:al")]))
        else:
            await sc_ar(update, ctx, oid)

    elif kind == "act" and what == "unlink":
        await db.unlink_telegram(oid)
        await sc_us(update, ctx, oid)

    elif kind == "ask":
        if what == "a":
            arena = await db.get_arena(oid)
            if not arena:
                return await show(update, "Arena topilmadi.", kb([b("⬅️ Orqaga", "nav:al")]))
            await show(update, f"🗑 <b>{esc(arena.title)}</b> arenasi va uning barcha savollari "
                               f"o'chiriladi. Tasdiqlaysizmi?",
                       kb([b("✅ Ha, o'chirish", f"del:a:{oid}"), b("❌ Yo'q", f"nav:ar:{oid}")]))
        elif what == "q":
            ques = await db.get_question(oid)
            if not ques:
                return await show(update, "Savol topilmadi.", kb([b("⬅️ Orqaga", "nav:al")]))
            await show(update, f"🗑 Savol o'chirilsinmi?\n\n{esc(clip(ques.text, 300))}",
                       kb([b("✅ Ha, o'chirish", f"del:q:{oid}"), b("❌ Yo'q", f"nav:qdel:{ques.arena_id}")]))
        elif what == "u":
            user = await db.get_user(oid)
            if not user:
                return await show(update, "User topilmadi.", kb([b("⬅️ Orqaga", "nav:ul")]))
            await show(update, f"🗑 <b>{esc(user.username)}</b> (<code>{esc(user.login)}</code>) "
                               f"o'chirilsinmi?",
                       kb([b("✅ Ha, o'chirish", f"del:u:{oid}"), b("❌ Yo'q", f"nav:us:{oid}")]))

    elif kind == "del":
        if what == "a":
            await db.delete_arena(oid)
            await sc_al(update, ctx)
        elif what == "q":
            arena_id = await db.delete_question(oid)
            if arena_id is None:
                await show(update, "Savol topilmadi.", kb([b("⬅️ Orqaga", "nav:al")]))
            else:
                await sc_qdel(update, ctx, arena_id)
        elif what == "u":
            await db.delete_user(oid)
            await sc_ul(update, ctx)


# --------------------------------------------------------------------------- #
# Ro'yxatdan o'tish (login/parol)
# --------------------------------------------------------------------------- #
REG_LOGIN, REG_PASS = range(2)


async def reg_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if ctx.user_data.get("quiz"):
        await q.answer("Siz arenadasiz. Chiqish uchun /cancel_arena", show_alert=True)
        return END
    await q.answer()
    if await has_access(update):
        await sc_home(update, ctx)
        return END
    ctx.user_data["reg_attempts"] = 0
    await q.message.reply_text("🔑 Loginingizni kiriting:\n(bekor qilish: /cancel)")
    return REG_LOGIN


async def reg_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["reg_login"] = update.message.text.strip()
    await update.message.reply_text("🔒 Parolingizni kiriting:")
    return REG_PASS


async def reg_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    await try_delete(update)  # parol chatda qolmasin
    login = ctx.user_data.get("reg_login", "")
    user = await db.authenticate(login, password)
    if not user:
        ctx.user_data["reg_attempts"] = ctx.user_data.get("reg_attempts", 0) + 1
        if ctx.user_data["reg_attempts"] >= 5:
            ctx.user_data.clear()
            await update.effective_chat.send_message(
                "⛔ Juda ko'p noto'g'ri urinish. Keyinroq qayta urinib ko'ring (/start).")
            return END
        await update.effective_chat.send_message("❌ Login yoki parol noto'g'ri. Loginni qaytadan kiriting:")
        return REG_LOGIN
    tg_id = update.effective_user.id
    if user.telegram_id not in (None, tg_id):
        ctx.user_data.clear()
        await update.effective_chat.send_message(
            "⛔ Bu akkaunt boshqa Telegramga ulangan. Admin bilan bog'laning.")
        return END
    await db.bind_telegram(user.id, tg_id)
    ctx.user_data.clear()
    await update.effective_chat.send_message(
        f"✅ Muvaffaqiyatli! Xush kelibsiz, <b>{esc(user.username)}</b>.",
        reply_markup=kb([b("🏟 Arena", "nav:play_list")]))
    return END


# --------------------------------------------------------------------------- #
# Admin: arena qo'shish
# --------------------------------------------------------------------------- #
ARENA_NAME = 0


async def arena_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, ctx, admin=True):
        return END
    await update.callback_query.message.reply_text(
        "🏟 Yangi arena nomini yozing:\n(bekor qilish: /cancel)")
    return ARENA_NAME


async def arena_add_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if not (1 <= len(title) <= 100):
        await update.message.reply_text("Nom 1–100 belgi bo'lishi kerak. Qaytadan yozing:")
        return ARENA_NAME
    arena = await db.create_arena(title)
    await update.message.reply_text(
        f"✅ Arena yaratildi: <b>{esc(arena.title)}</b>\nHolati: 🔴 yopiq (savol qo'shgach oching).",
        reply_markup=kb([b("🏟 Arenani ochish", f"nav:ar:{arena.id}")], [b("⬅️ Admin panel", "nav:admin")]))
    return END


# --------------------------------------------------------------------------- #
# Admin: savol qo'shish
# --------------------------------------------------------------------------- #
Q_TEXT, Q_A, Q_B, Q_C, Q_D, Q_CORRECT = range(6)


async def q_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, ctx, admin=True):
        return END
    aid = int(update.callback_query.data.split(":")[2])
    if not await db.get_arena(aid):
        await update.callback_query.message.reply_text("Arena topilmadi.")
        return END
    ctx.user_data["nq"] = {"arena_id": aid}
    await update.callback_query.message.reply_text(
        "❓ Savol matnini yozing:\n(bekor qilish: /cancel)")
    return Q_TEXT


def _limited(maxlen: int):
    def ok(text: str) -> bool:
        return 1 <= len(text.strip()) <= maxlen
    return ok


async def q_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if not _limited(1500)(t):
        await update.message.reply_text("Savol 1–1500 belgi bo'lishi kerak. Qaytadan yozing:")
        return Q_TEXT
    ctx.user_data["nq"]["text"] = t.strip()
    await update.message.reply_text("A variantini yozing:")
    return Q_A


def _option_handler(key: str, next_state: int, next_prompt: str, this_state: int):
    async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        t = update.message.text
        if not _limited(300)(t):
            await update.message.reply_text("Variant 1–300 belgi bo'lishi kerak. Qaytadan yozing:")
            return this_state
        ctx.user_data["nq"][key] = t.strip()
        if next_state == Q_CORRECT:
            await update.message.reply_text(next_prompt, reply_markup=kb(
                [b("A", "qc:a"), b("B", "qc:b"), b("C", "qc:c"), b("D", "qc:d")]))
        else:
            await update.message.reply_text(next_prompt)
        return next_state
    return handler


async def _save_question(update: Update, ctx: ContextTypes.DEFAULT_TYPE, letter: str):
    nq = ctx.user_data.pop("nq", None)
    if not nq:
        return END
    await db.add_question(nq["arena_id"], nq["text"], nq["a"], nq["b"], nq["c"], nq["d"], letter)
    await update.effective_chat.send_message(
        f"✅ Savol qo'shildi. To'g'ri javob: <b>{letter.upper()}</b>",
        reply_markup=kb([b("➕ Yana savol", f"conv:q_add:{nq['arena_id']}")],
                        [b("⬅️ Arena", f"nav:ar:{nq['arena_id']}")]))
    return END


async def q_correct_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        await q.edit_message_reply_markup(None)
    except TelegramError:
        pass
    return await _save_question(update, ctx, q.data.split(":")[1])


async def q_correct_txt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    letter = update.message.text.strip().lower()
    if letter not in LETTERS:
        await update.message.reply_text("Faqat A, B, C yoki D yozing (yoki tugmani bosing):")
        return Q_CORRECT
    return await _save_question(update, ctx, letter)


# --------------------------------------------------------------------------- #
# Admin: yangi user qo'shish
# --------------------------------------------------------------------------- #
U_NAME, U_LOGIN, U_PASS = range(3)


async def u_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, ctx, admin=True):
        return END
    ctx.user_data["nu"] = {}
    await update.callback_query.message.reply_text(
        "👤 Yangi userning ismini (username) yozing:\n(bekor qilish: /cancel)")
    return U_NAME


async def u_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not (2 <= len(t) <= 64):
        await update.message.reply_text("Ism 2–64 belgi bo'lishi kerak. Qaytadan yozing:")
        return U_NAME
    ctx.user_data["nu"]["username"] = t
    await update.message.reply_text("🔑 Login yarating (lotin harf, raqam, _ . -; 3–32 belgi):")
    return U_LOGIN


async def u_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not LOGIN_RE.match(t):
        await update.message.reply_text("Login 3–32 belgi, faqat lotin harf, raqam va _ . - bo'lishi kerak:")
        return U_LOGIN
    if await db.login_exists(t):
        await update.message.reply_text("Bu login band. Boshqa login yozing:")
        return U_LOGIN
    ctx.user_data["nu"]["login"] = t
    await update.message.reply_text("🔒 Parol yarating (4–64 belgi):")
    return U_PASS


async def u_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if not (4 <= len(t) <= 64):
        await update.message.reply_text("Parol 4–64 belgi bo'lishi kerak. Qaytadan yozing:")
        return U_PASS
    nu = ctx.user_data.pop("nu")
    try:
        await db.create_user(nu["username"], nu["login"], t)
    except ValueError:
        await update.message.reply_text("Bu login band bo'lib qoldi. /cancel va qaytadan urinib ko'ring.")
        return END
    await try_delete(update)
    await update.effective_chat.send_message(
        f"✅ User yaratildi.\n\nIsm: <b>{esc(nu['username'])}</b>\n"
        f"Login: <code>{esc(nu['login'])}</code>\nParol: <code>{esc(t)}</code>\n\n"
        f"Shu ma'lumotni userga yuboring.",
        reply_markup=kb([b("📋 Userlar ro'yxati", "nav:ul")], [b("⬅️ Userlar boshqaruvi", "nav:um")]))
    return END


# --------------------------------------------------------------------------- #
# Admin: user tahrirlash
# --------------------------------------------------------------------------- #
U_EDIT_VALUE = 0
FIELD_LABEL = {"username": "yangi ism", "login": "yangi login", "password": "yangi parol"}


async def u_edit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, ctx, admin=True):
        return END
    _, _, uid, field = update.callback_query.data.split(":")
    if not await db.get_user(int(uid)):
        await update.callback_query.message.reply_text("User topilmadi.")
        return END
    ctx.user_data["ue"] = {"id": int(uid), "field": field}
    await update.callback_query.message.reply_text(
        f"✏️ {FIELD_LABEL[field].capitalize()}ni yozing:\n(bekor qilish: /cancel)")
    return U_EDIT_VALUE


async def u_edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ue = ctx.user_data["ue"]
    field, uid = ue["field"], ue["id"]
    t = update.message.text if field == "password" else update.message.text.strip()
    if field == "username" and not (2 <= len(t) <= 64):
        await update.message.reply_text("Ism 2–64 belgi bo'lishi kerak. Qaytadan yozing:")
        return U_EDIT_VALUE
    if field == "login":
        if not LOGIN_RE.match(t):
            await update.message.reply_text("Login 3–32 belgi, faqat lotin harf, raqam va _ . - bo'lishi kerak:")
            return U_EDIT_VALUE
        if await db.login_exists(t, exclude_id=uid):
            await update.message.reply_text("Bu login band. Boshqasini yozing:")
            return U_EDIT_VALUE
    if field == "password" and not (4 <= len(t) <= 64):
        await update.message.reply_text("Parol 4–64 belgi bo'lishi kerak. Qaytadan yozing:")
        return U_EDIT_VALUE
    try:
        ok = await db.update_user(uid, field, t)
    except ValueError:
        await update.message.reply_text("Bu login band. Boshqasini yozing:")
        return U_EDIT_VALUE
    ctx.user_data.pop("ue", None)
    if field == "password":
        await try_delete(update)
        extra = f"\nYangi parol: <code>{esc(t)}</code>"
    else:
        extra = ""
    await update.effective_chat.send_message(
        ("✅ Saqlandi." + extra) if ok else "User topilmadi.",
        reply_markup=kb([b("👤 Userga qaytish", f"nav:us:{uid}")]))
    return END


# --------------------------------------------------------------------------- #
# Arena (quiz) — user/admin uchun
# --------------------------------------------------------------------------- #
QUIZ = 0


def _question_text(quiz: dict) -> str:
    i, n = quiz["i"], len(quiz["questions"])
    q = quiz["questions"][i]
    return (f"❓ <b>Savol {i + 1}/{n}</b>\n\n{esc(q['text'])}\n\n"
            f"<b>A)</b> {esc(q['a'])}\n<b>B)</b> {esc(q['b'])}\n"
            f"<b>C)</b> {esc(q['c'])}\n<b>D)</b> {esc(q['d'])}")


def _answer_kb(qid: int) -> InlineKeyboardMarkup:
    return kb([b(l.upper(), f"ans:{qid}:{l}") for l in LETTERS])


async def play_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if ctx.user_data.get("quiz"):
        await q.answer("Siz allaqachon arenadasiz. Chiqish: /cancel_arena", show_alert=True)
        return QUIZ
    if not await has_access(update):
        await q.answer("Avval ro'yxatdan o'ting", show_alert=True)
        return END
    arena = await db.get_arena(int(q.data.split(":")[1]))
    if not arena:
        await q.answer("Arena topilmadi", show_alert=True)
        return END
    if not arena.is_open:
        await q.answer("Bu arena hozircha yopiq 🔒", show_alert=True)
        return END
    questions = await db.get_questions(arena.id)
    if not questions:
        await q.answer("Bu arenada hali savol yo'q", show_alert=True)
        return END
    await q.answer()
    ctx.user_data.clear()
    ctx.user_data["quiz"] = {
        "title": arena.title, "i": 0, "score": 0,
        "questions": [{"id": x.id, "text": x.text, "a": x.option_a, "b": x.option_b,
                       "c": x.option_c, "d": x.option_d, "correct": x.correct_answer}
                      for x in questions],
    }
    quiz = ctx.user_data["quiz"]
    await q.message.reply_text(
        f"🏟 <b>{esc(arena.title)}</b> arenasiga kirdingiz!\n"
        f"Savollar: {len(questions)} ta. Javob uchun A/B/C/D tugmalarini bosing.\n"
        f"Chiqish uchun /cancel_arena tugmasini bosing.")
    await q.message.reply_text(_question_text(quiz), reply_markup=_answer_kb(quiz["questions"][0]["id"]))
    return QUIZ


async def quiz_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    quiz = ctx.user_data.get("quiz")
    if not quiz:
        await q.answer("Arena tugagan", show_alert=True)
        return END
    _, qid, letter = q.data.split(":")
    cur = quiz["questions"][quiz["i"]]
    if int(qid) != cur["id"]:
        await q.answer("Bu savolga allaqachon javob berdingiz")
        return QUIZ
    await q.answer()
    correct = letter == cur["correct"]
    if correct:
        quiz["score"] += 1
    verdict = "✅ To'g'ri!" if correct else f"❌ Noto'g'ri. To'g'ri javob: <b>{cur['correct'].upper()}</b>"
    try:
        await q.edit_message_text(
            f"{_question_text(quiz)}\n\nSizning javobingiz: <b>{letter.upper()}</b>\n{verdict}")
    except BadRequest:
        pass
    quiz["i"] += 1
    total = len(quiz["questions"])
    if quiz["i"] >= total:
        score, title = quiz["score"], quiz["title"]
        ctx.user_data.pop("quiz", None)
        pct = round(score * 100 / total)
        await q.message.reply_text(
            f"🏁 <b>{esc(title)}</b> tugadi!\nNatija: <b>{score}/{total}</b> ({pct}%)",
            reply_markup=kb([b("🏟 Arenalar", "nav:play_list")], [b("🏠 Bosh menyu", "nav:home")]))
        return END
    await q.message.reply_text(_question_text(quiz), reply_markup=_answer_kb(quiz["questions"][quiz["i"]]["id"]))
    return QUIZ


async def in_arena_warning(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "⚠️ Siz arenadasiz! Javob berish uchun A/B/C/D tugmalaridan foydalaning.\n"
        "Chiqish uchun /cancel_arena tugmasini bosing.")
    return QUIZ


async def cancel_arena(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    quiz = ctx.user_data.pop("quiz", None)
    if quiz:
        answered = quiz["i"]
        await update.message.reply_text(
            f"🚪 Arenadan chiqdingiz.\nJavob berilgan: {answered}/{len(quiz['questions'])}, "
            f"to'g'ri: {quiz['score']}.",
            reply_markup=kb([b("🏟 Arenalar", "nav:play_list")], [b("🏠 Bosh menyu", "nav:home")]))
    else:
        await update.message.reply_text("Siz arenada emassiz.")
    return END


# --------------------------------------------------------------------------- #
# Xatolar
# --------------------------------------------------------------------------- #
async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.exception("Xato:", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await update.effective_chat.send_message("⚠️ Xatolik yuz berdi. /start ni bosib qayta urinib ko'ring.")
        except TelegramError:
            pass


# --------------------------------------------------------------------------- #
# Ishga tushirish
# --------------------------------------------------------------------------- #
async def post_init(app: Application) -> None:
    await db.init_db()
    log.info("DB tayyor. ADMIN_ID=%s", ADMIN_ID)


async def post_shutdown(app: Application) -> None:
    await db.dispose()


TEXT = filters.TEXT & ~filters.COMMAND


def build_app() -> Application:
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Arena (quiz) — birinchi bo'lib, chunki arenada barcha xabarlarni ushlab turishi kerak
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(play_start, pattern=r"^play:\d+$")],
        states={QUIZ: [
            CallbackQueryHandler(quiz_answer, pattern=r"^ans:\d+:[abcd]$"),
            CommandHandler("cancel_arena", cancel_arena),
            MessageHandler(filters.ALL, in_arena_warning),
        ]},
        fallbacks=[CommandHandler("cancel_arena", cancel_arena)],
        allow_reentry=True,
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(reg_start, pattern=r"^reg:start$")],
        states={REG_LOGIN: [MessageHandler(TEXT, reg_login)], REG_PASS: [MessageHandler(TEXT, reg_pass)]},
        fallbacks=CONV_FALLBACKS,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(arena_add_start, pattern=r"^conv:arena_add$")],
        states={ARENA_NAME: [MessageHandler(TEXT, arena_add_name)]},
        fallbacks=CONV_FALLBACKS,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(q_add_start, pattern=r"^conv:q_add:\d+$")],
        states={
            Q_TEXT: [MessageHandler(TEXT, q_text)],
            Q_A: [MessageHandler(TEXT, _option_handler("a", Q_B, "B variantini yozing:", Q_A))],
            Q_B: [MessageHandler(TEXT, _option_handler("b", Q_C, "C variantini yozing:", Q_B))],
            Q_C: [MessageHandler(TEXT, _option_handler("c", Q_D, "D variantini yozing:", Q_C))],
            Q_D: [MessageHandler(TEXT, _option_handler("d", Q_CORRECT, "✅ To'g'ri javobni tanlang:", Q_D))],
            Q_CORRECT: [CallbackQueryHandler(q_correct_btn, pattern=r"^qc:[abcd]$"),
                        MessageHandler(TEXT, q_correct_txt)],
        },
        fallbacks=CONV_FALLBACKS,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(u_add_start, pattern=r"^conv:u_add$")],
        states={U_NAME: [MessageHandler(TEXT, u_name)],
                U_LOGIN: [MessageHandler(TEXT, u_login)],
                U_PASS: [MessageHandler(TEXT, u_pass)]},
        fallbacks=CONV_FALLBACKS,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(u_edit_start, pattern=r"^conv:u_edit:\d+:(username|login|password)$")],
        states={U_EDIT_VALUE: [MessageHandler(TEXT, u_edit_value)]},
        fallbacks=CONV_FALLBACKS,
    ))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel_arena", cancel_arena))
    app.add_handler(CallbackQueryHandler(nav, pattern=r"^nav:"))
    app.add_handler(CallbackQueryHandler(act, pattern=r"^(act|ask|del):"))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    if not TOKEN:
        raise SystemExit("TOKEN topilmadi. .env faylga BotFather tokenini yozing.")
    if not ADMIN_ID:
        raise SystemExit("ADMIN_ID topilmadi. .env faylga o'zingizning Telegram ID ingizni yozing.")
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
