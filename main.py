#!/usr/bin/env python3
"""
🎯 FREELANCE HUNTER — один файл, без папок
Просто перетягни на GitHub і деплой на Railway.
"""
import asyncio
import aiohttp
import hashlib
import re
import logging
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
import anthropic

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO, datefmt="%H:%M:%S"
)
log = logging.getLogger("hunter")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🔑 КЛЮЧІ — вставляй в Railway Variables
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
ALLOWED_USER_ID    = int(os.environ.get("ALLOWED_USER_ID", "0"))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ПЛАТФОРМИ ЯКІ СКАНУЄ БОТ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCES = [
    {"name": "Upwork", "emoji": "🔵", "url": "https://www.upwork.com/ab/feed/jobs/rss?q=telegram+bot&sort=recency&paging=0%3B20"},
    {"name": "Upwork", "emoji": "🔵", "url": "https://www.upwork.com/ab/feed/jobs/rss?q=chatgpt+automation&sort=recency&paging=0%3B20"},
    {"name": "Upwork", "emoji": "🔵", "url": "https://www.upwork.com/ab/feed/jobs/rss?q=python+script+simple&sort=recency&paging=0%3B20"},
    {"name": "Upwork", "emoji": "🔵", "url": "https://www.upwork.com/ab/feed/jobs/rss?q=ai+assistant+content&sort=recency&paging=0%3B20"},
    {"name": "Upwork", "emoji": "🔵", "url": "https://www.upwork.com/ab/feed/jobs/rss?q=web+scraping+data&sort=recency&paging=0%3B20"},
    {"name": "Upwork", "emoji": "🔵", "url": "https://www.upwork.com/ab/feed/jobs/rss?q=content+writing+blog&sort=recency&paging=0%3B20"},
    {"name": "Freelancer", "emoji": "🟢", "url": "https://www.freelancer.com/rss/jobs/telegram-bot.xml"},
    {"name": "Freelancer", "emoji": "🟢", "url": "https://www.freelancer.com/rss/jobs/chatgpt.xml"},
    {"name": "Freelancer", "emoji": "🟢", "url": "https://www.freelancer.com/rss/jobs/python.xml"},
    {"name": "Freelancer", "emoji": "🟢", "url": "https://www.freelancer.com/rss/jobs/content-writing.xml"},
    {"name": "PeoplePerHour", "emoji": "🟡", "url": "https://www.peopleperhour.com/rss/jobs?q=chatgpt+automation"},
    {"name": "Guru", "emoji": "🟠", "url": "https://www.guru.com/jobs/search/index.aspx?output=rss&keyword=telegram+bot+chatgpt"},
    {"name": "Guru", "emoji": "🟠", "url": "https://www.guru.com/jobs/search/index.aspx?output=rss&keyword=python+automation"},
]

CAN_DO = [
    "telegram bot", "discord bot", "chatbot", "chat bot",
    "python script", "automation script", "automate",
    "chatgpt", "openai", "claude", "gpt", "llm", "ai assistant",
    "content writ", "copywriting", "blog post", "article",
    "product description", "social media", "instagram",
    "web scraping", "data scraping", "data extraction", "crawler",
    "google sheets", "excel", "spreadsheet",
    "resume", "cover letter", "proofreading", "rewrite",
    "translation", "translate",
    "data entry", "data processing",
    "landing page", "html", "simple website",
    "email template", "newsletter",
    "summarize", "summary", "report",
    "virtual assistant", "api integration", "webhook",
]

CANT_DO = [
    "mobile app", "ios", "android", "flutter", "react native",
    "blockchain", "smart contract", "solidity", "web3", "nft mint",
    "machine learning", "train model", "deep learning", "neural network",
    "3d model", "unity", "unreal", "game dev",
    "video edit", "motion graphic", "after effects",
    "logo design", "graphic design",
    "wordpress plugin", "shopify app",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ДАНІ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@dataclass
class Job:
    title: str
    description: str
    url: str
    source: str
    source_emoji: str
    budget: str = "Не вказано"
    uid: str = ""
    found_at: datetime = field(default_factory=datetime.now)
    # Після аналізу
    what: str = ""
    how: str = ""
    complexity: str = "MEDIUM"
    minutes: int = 60
    price: int = 50
    can_auto: bool = True
    reply_en: str = ""
    result: str = ""
    filename: str = "result.txt"

    def __post_init__(self):
        self.uid = hashlib.md5(self.url.encode()).hexdigest()[:10]
        self.description = re.sub(r'<[^>]+>', ' ', self.description)
        self.description = re.sub(r'\s+', ' ', self.description).strip()[:600]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  СКАНЕР
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Scanner:
    def __init__(self):
        self.seen: set = set()
        self._session = None

    async def _fetch(self, url: str) -> Optional[str]:
        try:
            if not self._session or self._session.closed:
                self._session = aiohttp.ClientSession(headers={
                    "User-Agent": "Mozilla/5.0 (compatible; RSS/1.0)",
                    "Accept": "application/rss+xml,text/xml,*/*",
                })
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status == 200:
                    return await r.text()
        except Exception as e:
            log.debug(f"fetch {url[:50]}: {e}")
        return None

    @staticmethod
    def _budget(text: str) -> str:
        for p in [r'\$[\d,]+\s*[-–]\s*\$[\d,]+', r'\$[\d,]+\+?', r'£[\d,]+', r'€[\d,]+', r'[\d,]+\s*USD']:
            m = re.search(p, text, re.I)
            if m:
                return m.group(0).strip()
        return "Не вказано"

    def _ok(self, job: Job) -> bool:
        text = (job.title + " " + job.description).lower()
        for kw in CANT_DO:
            if kw in text:
                return False
        for kw in CAN_DO:
            if kw in text:
                return True
        return False

    async def scan(self) -> list[Job]:
        import feedparser
        result = []
        for src in SOURCES:
            xml = await self._fetch(src["url"])
            if not xml:
                await asyncio.sleep(1)
                continue
            try:
                feed = feedparser.parse(xml)
                for e in feed.entries[:20]:
                    title = e.get("title", "").strip()
                    desc  = e.get("summary", e.get("description", "")).strip()
                    url   = e.get("link", "")
                    if not title or not url:
                        continue
                    job = Job(
                        title=title, description=desc, url=url,
                        budget=self._budget(title + " " + desc),
                        source=src["name"], source_emoji=src["emoji"],
                    )
                    if job.uid not in self.seen and self._ok(job):
                        self.seen.add(job.uid)
                        result.append(job)
            except Exception as ex:
                log.debug(f"parse: {ex}")
            await asyncio.sleep(1.2)
        log.info(f"Скан: {len(result)} нових підходящих")
        return result

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ВИКОНАВЕЦЬ — Claude аналізує і робить роботу
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Executor:
    def __init__(self, api_key: str):
        self.claude = anthropic.Anthropic(api_key=api_key)

    def _ask(self, prompt: str, max_tokens=2000) -> str:
        try:
            r = self.claude.messages.create(
                model="claude-opus-4-5",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            return r.content[0].text.strip()
        except Exception as e:
            log.error(f"claude: {e}")
            return ""

    def analyze(self, job: Job) -> Job:
        raw = self._ask(f"""Ти AI фріланс виконавець. Проаналізуй замовлення. Відповідь ТІЛЬКИ JSON без markdown.

Назва: {job.title}
Опис: {job.description}
Бюджет: {job.budget}

JSON:
{{
  "what": "Що потрібно (3-5 слів українською)",
  "how": "Як зробимо (3-5 слів)",
  "complexity": "SIMPLE або MEDIUM або COMPLEX",
  "minutes": 45,
  "price": 60,
  "can_auto": true,
  "reply_en": "Повна відповідь клієнту англійською. Скажи що ти AI фахівець, можеш виконати, назви ціну і терміни. 3-4 речення природньо.",
  "filename": "result.py або result.txt або result.md"
}}

can_auto=true якщо це текст/контент/скрипт/резюме/переклад що Claude може зробити без даних клієнта.""",
            max_tokens=700)
        try:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                d = json.loads(m.group(0))
                job.what     = d.get("what", job.title[:40])
                job.how      = d.get("how", "Claude AI")
                job.complexity = d.get("complexity", "MEDIUM")
                job.minutes  = int(d.get("minutes", 60))
                job.price    = int(d.get("price", 50))
                job.can_auto = bool(d.get("can_auto", True))
                job.reply_en = d.get("reply_en", "Hi! I can help with this project.")
                job.filename = d.get("filename", "result.txt")
        except Exception as e:
            log.error(f"analyze parse: {e}")
        return job

    def execute(self, job: Job) -> Job:
        result = self._ask(f"""Ти топовий AI фріланс виконавець. Виконай замовлення ПОВНІСТЮ і якісно.

Назва: {job.title}
Опис: {job.description}

ПРАВИЛА:
- Виконай повністю, не частково
- Якщо код — напиши повний робочий код з коментарями
- Якщо текст — напиши повний фінальний текст
- Якщо бракує деталей — зроби найкращий варіант самостійно
- НЕ питай уточнень — просто виконуй
- Результат має бути готовим до відправки клієнту БЕЗ змін""",
            max_tokens=3000)
        job.result = result

        # Зберігаємо файл
        safe = re.sub(r'[^\w\-.]', '_', job.filename)
        path = f"/tmp/{job.uid}_{safe}"
        with open(path, "w", encoding="utf-8") as f:
            f.write(result)
        job._file_path = path
        return job

    def run(self, job: Job) -> Job:
        job = self.analyze(job)
        if job.can_auto:
            job = self.execute(job)
        return job

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM БОТ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_jobs: dict[str, Job] = {}

def _cx(c): return {"SIMPLE":"🟢","MEDIUM":"🟡","COMPLEX":"🔴"}.get(c,"🟡")

def _card(j: Job) -> str:
    t = f"{j.minutes} хв" if j.minutes < 60 else f"{j.minutes//60}г {j.minutes%60}хв"
    d = "✅ Бот виконає САМ" if j.can_auto else "👆 Потрібна твоя участь"
    return (
        f"🎯 *НОВЕ ЗАМОВЛЕННЯ*\n"
        f"{j.source_emoji} *{j.source}*\n\n"
        f"📋 *{j.title[:80]}*\n\n"
        f"💡 *Що:* {j.what}\n"
        f"🔧 *Як:* {j.how}\n\n"
        f"{_cx(j.complexity)} Складність: *{j.complexity}*\n"
        f"⏱ Час: *{t}*\n"
        f"💰 Бюджет: *{j.budget}*\n"
        f"💵 Твоя ціна: *${j.price}*\n\n"
        f"📦 {d}\n"
    )

def _kb(j: Job) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton("✉️ Відповідь клієнту", callback_data=f"reply:{j.uid}"),
        InlineKeyboardButton("📋 Деталі", callback_data=f"detail:{j.uid}"),
    ]]
    if j.can_auto and j.result:
        rows.append([InlineKeyboardButton("📁 Готовий файл", callback_data=f"file:{j.uid}")])
    else:
        rows.append([InlineKeyboardButton("🤖 Промпт для Claude", callback_data=f"prompt:{j.uid}")])
    rows.append([
        InlineKeyboardButton("🔗 Відкрити", url=j.url),
        InlineKeyboardButton("⏭ Пропустити", callback_data=f"skip:{j.uid}"),
    ])
    return InlineKeyboardMarkup(rows)


class Bot:
    def __init__(self):
        self.scanner  = Scanner()
        self.executor = Executor(api_key=ANTHROPIC_API_KEY)
        self.paused   = False
        self.scans    = 0
        self.sent     = 0

    def _ok(self, u: Update) -> bool:
        return ALLOWED_USER_ID == 0 or u.effective_user.id == ALLOWED_USER_ID

    async def _send(self, u: Update, text: str, kb=None):
        kw = {"parse_mode": ParseMode.MARKDOWN, "disable_web_page_preview": True}
        if kb: kw["reply_markup"] = kb
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            await u.effective_message.reply_text(chunk, **kw)

    async def _push_job(self, app: Application, j: Job):
        _jobs[j.uid] = j
        try:
            await app.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=_card(j),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_kb(j),
                disable_web_page_preview=True,
            )
            self.sent += 1
        except Exception as e:
            log.error(f"push: {e}")

    # ── Команди ──────────────────────────────────────────────

    async def start(self, u: Update, _):
        if not self._ok(u): return
        await self._send(u, (
            "🎯 *FREELANCE HUNTER*\n"
            "*Що робить бот:*\n"
            "• Кожні 15 хв сканує Upwork, Freelancer, Guru\n"
            "• Фільтрує тільки AI-виконувані замовлення\n"
            "• Виконує замовлення через Claude одразу\n"
            "• Надсилає готовий файл + відповідь клієнту\n\n"
            "*Твоя участь:*\n"
            "1️⃣ Скопіював відповідь → відправив клієнту\n"
            "2️⃣ Отримав файл → скинув клієнту\n"
            "3️⃣ Забрав гроші ✅\n\n"
            "/scan — шукати прямо зараз\n"
            "/status — статистика\n"
            "/pause — зупинити\n"
            "/resume — відновити"
        ))

    async def scan(self, u: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._ok(u): return
        msg = await u.effective_message.reply_text(
            "🔍 *Сканую платформи...*\n_Зачекай 1-2 хвилини_",
            parse_mode=ParseMode.MARKDOWN
        )
        jobs = await self.scanner.scan()
        self.scans += 1
        if not jobs:
            await msg.edit_text("😴 Нових замовлень не знайдено. Спробую через 15 хв.")
            return
        await msg.edit_text(f"⚙️ Знайдено {len(jobs)}. Виконую через Claude...")
        done = 0
        for job in jobs[:5]:
            job = self.executor.run(job)
            _jobs[job.uid] = job
            text = _card(job)
            kb = _kb(job)
            await u.effective_message.reply_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb, disable_web_page_preview=True
            )
            done += 1
            await asyncio.sleep(2)
        await u.effective_message.reply_text(f"✅ Готово! {done} замовлень з результатами.")

    async def status(self, u: Update, _):
        if not self._ok(u): return
        st = "⏸ ПАУЗА" if self.paused else "🟢 АКТИВНИЙ"
        await self._send(u, (
            f"📊 *Статус*\n"
            f"Стан: *{st}*\n"
            f"🔍 Сканів: *{self.scans}*\n"
            f"📨 Надіслано: *{self.sent}*\n"
            f"💾 В пам'яті: *{len(_jobs)}*\n"
            f"_Наступний скан: ~15 хв_"
        ))

    async def pause(self, u: Update, _):
        if not self._ok(u): return
        self.paused = True
        await u.effective_message.reply_text("⏸ Зупинено. /resume щоб відновити.")

    async def resume(self, u: Update, _):
        if not self._ok(u): return
        self.paused = False
        await u.effective_message.reply_text("▶️ Відновлено!")

    async def text(self, u: Update, _):
        if not self._ok(u): return
        await u.effective_message.reply_text("Використовуй /scan або чекай — бот сам надішле замовлення 🤖")

    # ── Кнопки ───────────────────────────────────────────────

    async def callback(self, u: Update, _):
        q = u.callback_query
        await q.answer()
        parts = q.data.split(":", 1)
        if len(parts) != 2:
            return
        action, uid = parts
        j = _jobs.get(uid)

        if action == "skip":
            await q.message.reply_text("⏭ Пропущено.")
            return
        if not j:
            await q.message.reply_text("❌ Не знайдено. Запусти /scan знову.")
            return

        if action == "reply":
            await q.message.reply_text(
                f"✉️ *КОПІЮЙ І ВІДПРАВ КЛІЄНТУ:*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{j.reply_en}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🔗 [Відкрити замовлення]({j.url})",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )

        elif action == "detail":
            await q.message.reply_text(
                f"📋 *ДЕТАЛІ:*\n\n"
                f"*{j.title}*\n\n"
                f"{j.description[:800]}\n\n"
                f"💰 Бюджет: *{j.budget}*\n"
                f"💵 Пропонуй: *${j.price}*\n"
                f"🔗 [Відкрити]({j.url})",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )

        elif action == "file":
            if not j.result:
                await q.message.reply_text("⏳ Виконую...")
                j = self.executor.execute(j)
                _jobs[uid] = j

            path = getattr(j, '_file_path', None)
            await q.message.reply_text(
                f"📁 *ГОТОВИЙ РЕЗУЛЬТАТ — СКИНЬ КЛІЄНТУ:*\n"
                f"🔗 [Відкрити замовлення]({j.url})",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    await q.message.reply_document(
                        document=InputFile(f, filename=j.filename),
                        caption=f"✅ {j.what} — готово до відправки клієнту",
                    )
            else:
                await q.message.reply_text(
                    f"```\n{j.result[:3800]}\n```",
                    parse_mode=ParseMode.MARKDOWN,
                )

        elif action == "prompt":
            prompt = (
                f"Виконай це фріланс замовлення повністю і якісно.\n\n"
                f"Назва: {j.title}\n\nОпис: {j.description}\n\n"
                f"Зроби повний результат готовий до відправки клієнту."
            )
            await q.message.reply_text(
                f"🤖 *ПРОМПТ — ВСТАВТЕ В claude.ai:*\n\n```\n{prompt}\n```\n\n"
                f"🔗 [Відкрити замовлення]({j.url})",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )

    # ── Фоновий цикл ─────────────────────────────────────────

    async def _loop(self, app: Application):
        await asyncio.sleep(10)
        while True:
            if not self.paused and ALLOWED_USER_ID:
                try:
                    jobs = await self.scanner.scan()
                    self.scans += 1
                    for job in jobs[:5]:
                        job = self.executor.run(job)
                        await self._push_job(app, job)
                        await asyncio.sleep(3)
                except Exception as e:
                    log.error(f"loop: {e}")
            await asyncio.sleep(900)

    def run(self):
        if not TELEGRAM_BOT_TOKEN:
            print("❌ Встав TELEGRAM_BOT_TOKEN в Railway Variables!")
            return
        if not ANTHROPIC_API_KEY:
            print("❌ Встав ANTHROPIC_API_KEY в Railway Variables!")
            return

        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start",  self.start))
        app.add_handler(CommandHandler("help",   self.start))
        app.add_handler(CommandHandler("scan",   self.scan))
        app.add_handler(CommandHandler("status", self.status))
        app.add_handler(CommandHandler("pause",  self.pause))
        app.add_handler(CommandHandler("resume", self.resume))
        app.add_handler(CallbackQueryHandler(self.callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text))

        async def on_start(a):
            asyncio.create_task(self._loop(a))
            log.info("✅ Запущено!")

        app.post_init = on_start
        log.info("🚀 Старт...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    Bot().run()
