#!/usr/bin/env python3
"""
FREELANCE HUNTER v3 — реальні джерела що працюють
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

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
ALLOWED_USER_ID    = int(os.environ.get("ALLOWED_USER_ID", "0"))

# ── Що Claude може зробити ────────────────────────────────────
CAN_DO = [
    "telegram", "discord", "chatbot", "chat bot", "bot",
    "python", "script", "automat",
    "chatgpt", "openai", "claude", "gpt", "llm", "ai",
    "content", "copywrite", "blog", "article", "writ",
    "product description", "social media", "instagram",
    "scraping", "scraper", "crawl", "data extract",
    "google sheets", "excel", "spreadsheet",
    "resume", "cover letter", "proofread", "rewrite", "edit",
    "translat",
    "data entry", "data process",
    "landing page", "html", "simple web",
    "email", "newsletter",
    "summarize", "summary", "report",
    "virtual assistant", "api", "webhook", "zapier", "make.com",
    "prompt", "gpt wrapper", "openai api",
]

CANT_DO = [
    "mobile app", "ios", "android", "flutter", "react native", "swift", "kotlin",
    "blockchain", "smart contract", "solidity", "web3", "nft", "crypto",
    "machine learning", "train model", "deep learning", "neural network",
    "3d", "unity", "unreal", "game dev", "blender",
    "video edit", "motion graphic", "after effects", "premiere",
    "logo", "graphic design", "illustrator", "photoshop",
    "wordpress plugin", "shopify app", "magento",
    "pen test", "cybersecurity", "exploit",
]


@dataclass
class Job:
    title: str
    description: str
    url: str
    source: str
    budget: str = "Not specified"
    uid: str = ""
    found_at: datetime = field(default_factory=datetime.now)
    what: str = ""
    how: str = ""
    complexity: str = "MEDIUM"
    minutes: int = 60
    price: int = 50
    can_auto: bool = True
    reply_en: str = ""
    result: str = ""
    filename: str = "result.txt"
    _file_path: str = ""

    def __post_init__(self):
        self.uid = hashlib.md5((self.url + self.title).encode()).hexdigest()[:10]
        self.description = re.sub(r'<[^>]+>', ' ', self.description)
        self.description = re.sub(r'\s+', ' ', self.description).strip()[:800]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  СКАНЕР — тільки відкриті API що реально працюють
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Scanner:
    def __init__(self):
        self.seen: set = set()
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get(self, url: str, headers: dict = None) -> Optional[dict]:
        try:
            if not self._session or self._session.closed:
                self._session = aiohttp.ClientSession()
            h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
            if headers:
                h.update(headers)
            async with self._session.get(
                url, headers=h, timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    ct = r.headers.get("content-type", "")
                    if "json" in ct:
                        return await r.json()
                    text = await r.text()
                    try:
                        return json.loads(text)
                    except:
                        return {"_raw": text}
                log.debug(f"HTTP {r.status}: {url[:60]}")
        except Exception as e:
            log.debug(f"fetch error {url[:60]}: {e}")
        return None

    def _ok(self, title: str, desc: str) -> bool:
        text = (title + " " + desc).lower()
        for kw in CANT_DO:
            if kw in text:
                return False
        for kw in CAN_DO:
            if kw in text:
                return True
        return False

    def _budget(self, text: str) -> str:
        for p in [r'\$[\d,]+\s*[-–k]+\s*\$?[\d,k]+', r'\$[\d,k]+\+?', r'£[\d,]+', r'€[\d,]+']:
            m = re.search(p, text, re.I)
            if m:
                return m.group(0).strip()
        return "Not specified"

    # ── 1. RemoteOK — найбільша база remote jobs ──────────────
    async def _remoteok(self) -> list[Job]:
        data = await self._get("https://remoteok.com/api", {"Accept": "application/json"})
        jobs = []
        if not isinstance(data, list):
            return jobs
        for item in data[1:40]:  # перший елемент — legal notice
            if not isinstance(item, dict):
                continue
            title = item.get("position", "")
            desc  = item.get("description", "")
            url   = item.get("url", "")
            if not title or not url:
                continue
            tags = " ".join(item.get("tags", []))
            salary = item.get("salary", "") or ""
            budget = self._budget(str(salary)) if salary else "Not specified"
            if self._ok(title, desc + " " + tags):
                jobs.append(Job(
                    title=title, description=desc[:600],
                    url=url, source="RemoteOK",
                    budget=budget,
                ))
        log.info(f"RemoteOK: {len(jobs)} підходящих")
        return jobs

    # ── 2. Arbeitnow — безкоштовне API без ключа ─────────────
    async def _arbeitnow(self) -> list[Job]:
        data = await self._get("https://www.arbeitnow.com/api/job-board-api")
        jobs = []
        if not isinstance(data, dict):
            return jobs
        for item in data.get("data", [])[:30]:
            title = item.get("title", "")
            desc  = item.get("description", "")
            url   = item.get("url", "")
            if not title or not url:
                continue
            if self._ok(title, desc):
                jobs.append(Job(
                    title=title, description=desc[:600],
                    url=url, source="Arbeitnow",
                ))
        log.info(f"Arbeitnow: {len(jobs)} підходящих")
        return jobs

    # ── 3. Himalayas — tech jobs API ──────────────────────────
    async def _himalayas(self) -> list[Job]:
        urls = [
            "https://himalayas.app/jobs/api?q=chatgpt&limit=20",
            "https://himalayas.app/jobs/api?q=telegram+bot&limit=20",
            "https://himalayas.app/jobs/api?q=python+automation&limit=20",
            "https://himalayas.app/jobs/api?q=ai+assistant&limit=20",
        ]
        jobs = []
        for url in urls:
            data = await self._get(url)
            if not isinstance(data, dict):
                await asyncio.sleep(1)
                continue
            for item in data.get("jobs", []):
                title = item.get("title", "")
                desc  = item.get("description", "")
                url2  = item.get("applicationLink", item.get("url", ""))
                if not title or not url2:
                    continue
                salary = item.get("salary", "") or ""
                if self._ok(title, desc):
                    jobs.append(Job(
                        title=title, description=desc[:600],
                        url=url2, source="Himalayas",
                        budget=str(salary) if salary else "Not specified",
                    ))
            await asyncio.sleep(1)
        log.info(f"Himalayas: {len(jobs)} підходящих")
        return jobs

    # ── 4. FindWork — dev jobs ────────────────────────────────
    async def _findwork(self) -> list[Job]:
        searches = ["chatgpt", "telegram bot", "python script", "automation"]
        jobs = []
        for q in searches:
            data = await self._get(f"https://findwork.dev/api/jobs/?search={q}&remote=true")
            if not isinstance(data, dict):
                await asyncio.sleep(1)
                continue
            for item in data.get("results", [])[:10]:
                title = item.get("role", "")
                desc  = item.get("text", "")
                url   = item.get("url", "")
                if not title or not url:
                    continue
                if self._ok(title, desc):
                    jobs.append(Job(
                        title=title, description=desc[:600],
                        url=url, source="FindWork",
                    ))
            await asyncio.sleep(1)
        log.info(f"FindWork: {len(jobs)} підходящих")
        return jobs

    # ── 5. JobIceCream — remote jobs ─────────────────────────
    async def _jobicecream(self) -> list[Job]:
        data = await self._get("https://jobicecream.com/api/jobs?category=software-dev&remote=true")
        jobs = []
        if not isinstance(data, dict):
            return jobs
        for item in data.get("jobs", data.get("data", []))[:30]:
            title = item.get("title", item.get("position", ""))
            desc  = item.get("description", item.get("body", ""))
            url   = item.get("url", item.get("link", ""))
            if not title or not url:
                continue
            if self._ok(title, desc):
                jobs.append(Job(
                    title=title, description=str(desc)[:600],
                    url=url, source="JobIceCream",
                ))
        log.info(f"JobIceCream: {len(jobs)} підходящих")
        return jobs

    # ── 6. We Work Remotely RSS (реально працює) ─────────────
    async def _weworkremotely(self) -> list[Job]:
        import feedparser
        feeds = [
            "https://weworkremotely.com/categories/remote-programming-jobs.rss",
            "https://weworkremotely.com/categories/remote-copywriting-jobs.rss",
            "https://weworkremotely.com/remote-jobs.rss",
        ]
        jobs = []
        for feed_url in feeds:
            try:
                if not self._session or self._session.closed:
                    self._session = aiohttp.ClientSession()
                async with self._session.get(
                    feed_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=12)
                ) as r:
                    if r.status != 200:
                        continue
                    text = await r.text()
                feed = feedparser.parse(text)
                for e in feed.entries[:15]:
                    title = e.get("title", "")
                    desc  = e.get("summary", "")
                    url   = e.get("link", "")
                    if not title or not url:
                        continue
                    if self._ok(title, desc):
                        jobs.append(Job(
                            title=title,
                            description=re.sub(r'<[^>]+>', ' ', desc)[:600],
                            url=url, source="WeWorkRemotely",
                        ))
            except Exception as ex:
                log.debug(f"WWR feed error: {ex}")
            await asyncio.sleep(1)
        log.info(f"WeWorkRemotely: {len(jobs)} підходящих")
        return jobs

    # ── 7. Freelancer публічне API (без ключа, обмежено) ─────
    async def _freelancer_api(self) -> list[Job]:
        queries = ["telegram bot", "chatgpt automation", "python script", "content writing ai"]
        jobs = []
        for q in queries:
            data = await self._get(
                f"https://www.freelancer.com/api/projects/0.1/projects/active/"
                f"?query={q.replace(' ', '+')}&limit=10&job_details=true"
            )
            if not isinstance(data, dict):
                await asyncio.sleep(2)
                continue
            result = data.get("result", {})
            projects = result.get("projects", []) if isinstance(result, dict) else []
            for item in projects:
                title = item.get("title", "")
                desc  = item.get("preview_description", "")
                pid   = item.get("id", "")
                url   = f"https://www.freelancer.com/projects/{pid}" if pid else ""
                budget = item.get("budget", {})
                bmin  = budget.get("minimum", "") if isinstance(budget, dict) else ""
                bmax  = budget.get("maximum", "") if isinstance(budget, dict) else ""
                bstr  = f"${bmin}-${bmax}" if bmin and bmax else "Not specified"
                if not title or not url:
                    continue
                if self._ok(title, desc):
                    jobs.append(Job(
                        title=title, description=desc[:600],
                        url=url, source="Freelancer",
                        budget=bstr,
                    ))
            await asyncio.sleep(2)
        log.info(f"Freelancer API: {len(jobs)} підходящих")
        return jobs

    # ── Головний скан ─────────────────────────────────────────
    async def scan(self) -> list[Job]:
        all_jobs: list[Job] = []

        sources = [
            self._remoteok(),
            self._weworkremotely(),
            self._freelancer_api(),
            self._arbeitnow(),
            self._himalayas(),
            self._findwork(),
        ]

        results = await asyncio.gather(*sources, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                all_jobs.extend(r)

        # Фільтруємо тільки нові
        new_jobs = []
        for j in all_jobs:
            if j.uid not in self.seen:
                self.seen.add(j.uid)
                new_jobs.append(j)

        log.info(f"Всього нових підходящих: {len(new_jobs)}")
        return new_jobs


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ВИКОНАВЕЦЬ
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
        raw = self._ask(
            f"""You are an AI freelance executor. Analyze this job. Reply ONLY with JSON, no markdown.

Title: {job.title}
Description: {job.description[:400]}
Budget: {job.budget}

JSON:
{{
  "what": "What is needed (3-5 words in Ukrainian)",
  "how": "How we will do it (3-5 words in Ukrainian)",
  "complexity": "SIMPLE or MEDIUM or COMPLEX",
  "minutes": 45,
  "price": 60,
  "can_auto": true,
  "reply_en": "Full professional reply to client in English. Say you're an AI specialist, can deliver, mention price and timeline. 3-4 natural sentences.",
  "filename": "result.py or result.txt or result.md"
}}

can_auto=true if this is text/content/script/resume/translation Claude can do without client's private data.""",
            max_tokens=600,
        )
        try:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                d = json.loads(m.group(0))
                job.what      = d.get("what", job.title[:40])
                job.how       = d.get("how", "Claude AI")
                job.complexity = d.get("complexity", "MEDIUM")
                job.minutes   = int(d.get("minutes", 60))
                job.price     = int(d.get("price", 50))
                job.can_auto  = bool(d.get("can_auto", True))
                job.reply_en  = d.get("reply_en", "Hi! I can help with this project.")
                job.filename  = d.get("filename", "result.txt")
        except Exception as e:
            log.error(f"analyze parse: {e}")
        return job

    def execute(self, job: Job) -> Job:
        result = self._ask(
            f"""You are a top AI freelance executor. Complete this job FULLY and professionally.

Title: {job.title}
Description: {job.description}

RULES:
- Complete it fully, not partially
- If code — write complete working code with comments
- If text/content — write the complete final text
- If missing details — make the best version yourself
- Do NOT ask for clarifications — just execute
- Result must be ready to send to client WITHOUT changes""",
            max_tokens=3000,
        )
        job.result = result
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


def _card(j: Job) -> str:
    t = f"{j.minutes} хв" if j.minutes < 60 else f"{j.minutes//60}г {j.minutes%60}хв"
    d = "Бот виконає сам" if j.can_auto else "Потрібна твоя участь"
    return (
        f"НОВЕ ЗАМОВЛЕННЯ\n\n"
        f"Платформа: {j.source}\n\n"
        f"{j.title[:100]}\n\n"
        f"Що: {j.what}\n"
        f"Як: {j.how}\n\n"
        f"Складність: {j.complexity}\n"
        f"Час: {t}\n"
        f"Бюджет: {j.budget}\n"
        f"Твоя ціна: ${j.price}\n\n"
        f"Доставка: {d}"
    )


def _kb(j: Job) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton("Відповідь клієнту", callback_data=f"reply:{j.uid}"),
        InlineKeyboardButton("Деталі", callback_data=f"detail:{j.uid}"),
    ]]
    if j.can_auto and j.result:
        rows.append([InlineKeyboardButton("Готовий файл", callback_data=f"file:{j.uid}")])
    else:
        rows.append([InlineKeyboardButton("Промпт для Claude", callback_data=f"prompt:{j.uid}")])
    rows.append([
        InlineKeyboardButton("Відкрити", url=j.url),
        InlineKeyboardButton("Пропустити", callback_data=f"skip:{j.uid}"),
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
        if kb:
            kw["reply_markup"] = kb
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            await u.effective_message.reply_text(chunk, **kw)

    async def _push(self, app: Application, j: Job):
        _jobs[j.uid] = j
        try:
            await app.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=_card(j),
                reply_markup=_kb(j),
                disable_web_page_preview=True,
            )
            self.sent += 1
        except Exception as e:
            log.error(f"push: {e}")

    async def start(self, u: Update, _):
        if not self._ok(u): return
        await u.effective_message.reply_text(
            "FREELANCE HUNTER v3\n\n"
            "Сканую RemoteOK, WeWorkRemotely, Freelancer API, Arbeitnow, Himalayas, FindWork\n\n"
            "Кожні 15 хв знаходжу замовлення, виконую через Claude, надсилаю тобі.\n\n"
            "/scan - шукати зараз\n"
            "/status - статистика\n"
            "/pause - зупинити\n"
            "/resume - відновити"
        )

    async def scan(self, u: Update, _):
        if not self._ok(u): return
        msg = await u.effective_message.reply_text("Сканую платформи... зачекай 1-2 хвилини")
        jobs = await self.scanner.scan()
        self.scans += 1
        if not jobs:
            await msg.edit_text(
                "Нових замовлень не знайдено.\n\n"
                "Причина: всі знайдені вакансії вже були показані раніше.\n"
                "Спробую знову через 15 хв — нові замовлення з'являться."
            )
            return
        await msg.edit_text(f"Знайдено {len(jobs)}. Виконую через Claude...")
        done = 0
        for job in jobs[:5]:
            job = self.executor.run(job)
            _jobs[job.uid] = job
            await u.effective_message.reply_text(
                _card(job), reply_markup=_kb(job), disable_web_page_preview=True
            )
            done += 1
            await asyncio.sleep(2)
        await u.effective_message.reply_text(f"Готово! {done} замовлень надіслано.")

    async def status(self, u: Update, _):
        if not self._ok(u): return
        await u.effective_message.reply_text(
            f"Статус: {'ПАУЗА' if self.paused else 'АКТИВНИЙ'}\n"
            f"Сканів: {self.scans}\n"
            f"Надіслано: {self.sent}\n"
            f"В пам'яті: {len(_jobs)}\n"
            f"Джерела: RemoteOK, WeWorkRemotely, Freelancer, Arbeitnow, Himalayas, FindWork\n"
            f"Наступний скан: ~15 хв"
        )

    async def pause(self, u: Update, _):
        if not self._ok(u): return
        self.paused = True
        await u.effective_message.reply_text("Зупинено. /resume щоб відновити.")

    async def resume(self, u: Update, _):
        if not self._ok(u): return
        self.paused = False
        await u.effective_message.reply_text("Відновлено!")

    async def text(self, u: Update, _):
        if not self._ok(u): return
        await u.effective_message.reply_text("Використовуй /scan або чекай — бот сам надішле замовлення.")

    async def callback(self, u: Update, _):
        q = u.callback_query
        await q.answer()
        if ":" not in q.data:
            return
        action, uid = q.data.split(":", 1)
        j = _jobs.get(uid)

        if action == "skip":
            await q.message.reply_text("Пропущено.")
            return
        if not j:
            await q.message.reply_text("Не знайдено. Запусти /scan знову.")
            return

        if action == "reply":
            await q.message.reply_text(
                f"КОПІЮЙ І ВІДПРАВ КЛІЄНТУ:\n\n{j.reply_en}\n\n"
                f"Відкрий замовлення: {j.url}",
                disable_web_page_preview=True,
            )

        elif action == "detail":
            await q.message.reply_text(
                f"{j.title}\n\n{j.description[:800]}\n\n"
                f"Бюджет: {j.budget}\n"
                f"Пропонуй: ${j.price}\n"
                f"Час: {j.minutes} хв\n"
                f"Посилання: {j.url}",
                disable_web_page_preview=True,
            )

        elif action == "file":
            if not j.result:
                await q.message.reply_text("Виконую...")
                j = self.executor.execute(j)
                _jobs[uid] = j
            await q.message.reply_text(
                f"ГОТОВИЙ РЕЗУЛЬТАТ — СКИНЬ КЛІЄНТУ\n\nВідкрий замовлення: {j.url}",
                disable_web_page_preview=True,
            )
            if j._file_path and os.path.exists(j._file_path):
                with open(j._file_path, "rb") as f:
                    await q.message.reply_document(
                        document=InputFile(f, filename=j.filename),
                        caption=f"{j.what} — готово до відправки",
                    )
            else:
                await q.message.reply_text(j.result[:4000])

        elif action == "prompt":
            prompt = (
                f"Виконай це фріланс замовлення повністю і якісно.\n\n"
                f"Назва: {j.title}\n\nОпис: {j.description}\n\n"
                f"Зроби повний результат готовий до відправки клієнту без змін."
            )
            await q.message.reply_text(
                f"ПРОМПТ — ВСТАВТЕ В claude.ai:\n\n{prompt}\n\n"
                f"Посилання: {j.url}",
                disable_web_page_preview=True,
            )

    async def _loop(self, app: Application):
        await asyncio.sleep(15)
        while True:
            if not self.paused and ALLOWED_USER_ID:
                try:
                    jobs = await self.scanner.scan()
                    self.scans += 1
                    for job in jobs[:5]:
                        job = self.executor.run(job)
                        await self._push(app, job)
                        await asyncio.sleep(3)
                except Exception as e:
                    log.error(f"loop: {e}")
            await asyncio.sleep(900)

    def run(self):
        if not TELEGRAM_BOT_TOKEN:
            print("Встав TELEGRAM_BOT_TOKEN в Railway Variables!")
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
            log.info("Запущено! Сканую RemoteOK, WWR, Freelancer, Arbeitnow, Himalayas, FindWork")

        app.post_init = on_start
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    Bot().run()
