#!/usr/bin/env python3
"""
FREELANCE HUNTER v7 — Professional AI Freelance Agency
Знаходить завдання → виконує на рівні топ-фрілансера → готово до здачі
"""
import asyncio, aiohttp, hashlib, re, logging, json, os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import anthropic

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO, datefmt="%H:%M:%S")
log = logging.getLogger("bot")

TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
UID     = int(os.environ.get("ALLOWED_USER_ID", "0"))


def clean(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'please mention the word.*', '', text, flags=re.I | re.DOTALL)
    text = re.sub(r'tag [A-Za-z0-9+/=]{10,}', '', text)
    text = re.sub(r'#[A-Za-z0-9]{15,}', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()[:800]


def budget_str(bmin, bmax) -> str:
    if bmin and bmax:
        return f"${int(bmin)}–${int(bmax)}"
    if bmin:
        return f"${int(bmin)}+"
    return "Not specified"


@dataclass
class Task:
    title: str
    desc: str
    url: str
    source: str
    budget: str = "Not specified"
    uid: str = ""
    # Після аналізу
    title_ua: str = ""
    what_ua: str = ""
    how_ua: str = ""
    time_ua: str = "1-2 год"
    price: int = 50
    reply_en: str = ""
    delivery_type: str = "file"   # "file" або "prompt"
    result: str = ""
    filename: str = "result.txt"
    file_path: str = ""
    prompt_for_user: str = ""

    def __post_init__(self):
        self.uid = hashlib.md5((self.url + self.title).encode()).hexdigest()[:10]
        self.desc = clean(self.desc)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# СКАНЕР
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Scanner:
    def __init__(self):
        self.seen: set = set()
        self._sess = None

    async def _get(self, url: str, as_text=False):
        try:
            if not self._sess or self._sess.closed:
                self._sess = aiohttp.ClientSession(headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "application/json, text/xml, */*",
                })
            async with self._sess.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    if as_text:
                        return await r.text()
                    try:
                        return await r.json(content_type=None)
                    except:
                        return await r.text()
        except Exception as e:
            log.debug(f"fetch: {e}")
        return None

    async def _freelancer(self) -> list[Task]:
        queries = [
            "chatgpt", "telegram bot", "python script", "content writing",
            "blog article", "copywriting", "web scraping", "data entry",
            "translation", "resume", "proofreading", "ai assistant",
            "automation", "google sheets", "email writing", "social media",
            "product description", "chatbot", "landing page", "research",
            "rewriting", "ghostwriting", "summarize", "data analysis",
        ]
        tasks = []
        for q in queries:
            data = await self._get(
                f"https://www.freelancer.com/api/projects/0.1/projects/active/"
                f"?query={q.replace(' ', '+')}&limit=20&job_details=true"
            )
            if isinstance(data, dict):
                for p in data.get("result", {}).get("projects", []):
                    title = p.get("title", "").strip()
                    desc  = p.get("preview_description", "").strip()
                    pid   = p.get("id")
                    if not title or not pid:
                        continue
                    b = p.get("budget", {})
                    tasks.append(Task(
                        title=title, desc=desc,
                        url=f"https://www.freelancer.com/projects/{pid}",
                        source="Freelancer",
                        budget=budget_str(b.get("minimum"), b.get("maximum")),
                    ))
            await asyncio.sleep(1)
        log.info(f"Freelancer: {len(tasks)}")
        return tasks

    async def _guru(self) -> list[Task]:
        import feedparser
        queries = [
            "chatgpt", "telegram+bot", "python+script", "content+writing",
            "blog+post", "translation", "resume", "data+entry",
            "automation", "copywriting", "web+scraping", "ai+assistant",
        ]
        tasks = []
        for q in queries:
            text = await self._get(
                f"https://www.guru.com/jobs/search/index.aspx?output=rss&keyword={q}",
                as_text=True
            )
            if not text:
                continue
            for e in feedparser.parse(text).entries[:10]:
                title = e.get("title", "").strip()
                desc  = e.get("summary", "").strip()
                url   = e.get("link", "")
                if title and url:
                    tasks.append(Task(
                        title=title, desc=desc,
                        url=url, source="Guru",
                    ))
            await asyncio.sleep(0.8)
        log.info(f"Guru: {len(tasks)}")
        return tasks

    async def _pph(self) -> list[Task]:
        import feedparser
        queries = [
            "chatgpt", "telegram+bot", "python", "content+writing",
            "blog", "translation", "resume", "copywriting", "automation",
        ]
        tasks = []
        for q in queries:
            text = await self._get(
                f"https://www.peopleperhour.com/rss/jobs?q={q}",
                as_text=True
            )
            if not text:
                continue
            for e in feedparser.parse(text).entries[:10]:
                title = e.get("title", "").strip()
                desc  = e.get("summary", "").strip()
                url   = e.get("link", "")
                if title and url:
                    tasks.append(Task(
                        title=title, desc=desc,
                        url=url, source="PeoplePerHour",
                    ))
            await asyncio.sleep(0.8)
        log.info(f"PeoplePerHour: {len(tasks)}")
        return tasks

    async def scan(self) -> list[Task]:
        results = await asyncio.gather(
            self._freelancer(), self._guru(), self._pph(),
            return_exceptions=True
        )
        all_tasks = []
        for r in results:
            if isinstance(r, list):
                all_tasks.extend(r)
        new = [t for t in all_tasks if t.uid not in self.seen]
        for t in new:
            self.seen.add(t.uid)
        log.info(f"Нових: {len(new)}")
        return new


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLAUDE — СУДДЯ + ВИКОНАВЕЦЬ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

JUDGE = """You are a senior AI freelance agency manager. Analyze this freelance task.

TASK:
Title: {title}
Description: {desc}
Budget: {budget}
Platform: {source}

Decide if this can be completed with Claude AI in 1-3 prompts WITHOUT access to client's private systems.

ACCEPT (can_do=true):
- Writing: articles, blog posts, product descriptions, emails, social media, newsletters
- Documents: resumes, cover letters, business proposals, reports, grant proposals
- Code: Python scripts, automation, Telegram/Discord bots, web scrapers, Google Sheets scripts
- Translation, proofreading, rewriting, editing
- Research reports, data analysis (based on public info)
- Simple HTML/CSS landing pages
- Prompt engineering, ChatGPT workflows
- ANY creative or text-based deliverable

REJECT (can_do=false):
- Full-time job position (mentions salary, benefits, years of experience required)
- Needs client's private database/API/account access to function
- Mobile app from scratch (iOS/Android)
- Complex ML model training
- Video/audio editing
- Logo/brand graphic design

DELIVERY TYPE:
- "file" = Claude delivers the complete result directly (text, code, documents)
- "prompt" = task needs 2-3 steps with user input, provide detailed prompt guide

Reply ONLY with valid JSON, no markdown:
{{
  "can_do": true,
  "title_ua": "Short task name in Ukrainian",
  "what_ua": "What exactly needs to be done (1 sentence in Ukrainian)",
  "how_ua": "How Claude will do it (1 sentence in Ukrainian)",
  "time_ua": "30 min / 1 hour / 2 hours",
  "price": 75,
  "delivery_type": "file",
  "filename": "result.py",
  "reply_en": "Professional bid reply to client. 3-4 sentences. Confident, specific, mention relevant experience and exact deliverable. Include timeline and invite them to discuss details.",
  "reject_reason": ""
}}"""


EXECUTE = """You are an elite AI freelance specialist. Execute this task at the highest professional level.

CLIENT'S TASK:
Title: {title}
Full Description: {desc}
Platform: {source}

EXECUTION STANDARDS:
1. Deliver a COMPLETE, READY-TO-USE result — not a template, not a draft
2. Match the language of the task title/description exactly
3. No placeholders like [INSERT HERE] or [YOUR NAME] — make intelligent assumptions
4. Professional quality that exceeds client expectations
5. If it's code: fully working, commented, with usage instructions
6. If it's text: publication-ready, proper formatting for the platform
7. If it's a document: complete, professional structure, real content
8. Add value beyond what was asked — include extras the client will appreciate

DO NOT:
- Ask for clarification
- Leave blank sections
- Use asterisks for bold (**text**) — use plain text formatting
- Write meta-commentary about your process
- Include instructions to the user in the deliverable itself

Deliver the final result now:"""


PROMPT_GUIDE = """You are an elite AI freelance specialist. This task requires multiple steps with client input.

TASK:
Title: {title}
Description: {desc}

Create a complete PROMPT GUIDE that the freelancer can use to execute this step by step.

Format it as a clear numbered guide in the task's language:
1. What to ask the client first (if needed)
2. Step-by-step Claude prompts to complete the work
3. How to review and deliver the final result

Make it so detailed that anyone can follow it and deliver professional results.
Write in the same language as the task."""


class Executor:
    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=API_KEY)

    def _ask(self, prompt: str, max_tokens=4000) -> str:
        try:
            r = self.claude.messages.create(
                model="claude-opus-4-5",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            return r.content[0].text.strip()
        except Exception as e:
            log.error(f"Claude: {e}")
            return ""

    def judge(self, task: Task) -> Optional[Task]:
        raw = self._ask(
            JUDGE.format(
                title=task.title,
                desc=task.desc[:600],
                budget=task.budget,
                source=task.source,
            ),
            max_tokens=600,
        )
        try:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                return None
            d = json.loads(m.group(0))
            if not d.get("can_do", False):
                log.info(f"SKIP: {task.title[:60]} — {d.get('reject_reason', '')}")
                return None
            task.title_ua      = d.get("title_ua", task.title[:60])
            task.what_ua       = d.get("what_ua", "")
            task.how_ua        = d.get("how_ua", "")
            task.time_ua       = d.get("time_ua", "1-2 год")
            task.price         = int(d.get("price", 60))
            task.delivery_type = d.get("delivery_type", "file")
            task.filename      = d.get("filename", "result.txt")
            task.reply_en      = d.get("reply_en", "")
            log.info(f"ACCEPT [{task.delivery_type}]: {task.title_ua}")
            return task
        except Exception as e:
            log.error(f"judge: {e} | raw: {raw[:200]}")
            return None

    def execute(self, task: Task) -> Task:
        if task.delivery_type == "prompt":
            # Для складніших завдань — детальний гайд з промптами
            result = self._ask(
                PROMPT_GUIDE.format(title=task.title, desc=task.desc),
                max_tokens=2000,
            )
            task.prompt_for_user = result
            task.result = result
        else:
            # Виконуємо повністю
            result = self._ask(
                EXECUTE.format(
                    title=task.title,
                    desc=task.desc,
                    source=task.source,
                ),
                max_tokens=4000,
            )
            task.result = result

        # Зберігаємо файл
        safe = re.sub(r'[^\w\-.]', '_', task.filename)
        path = f"/tmp/{task.uid}_{safe}"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(task.result)
            task.file_path = path
        except Exception as e:
            log.error(f"save: {e}")
        return task

    def process(self, task: Task) -> Optional[Task]:
        task = self.judge(task)
        if not task:
            return None
        return self.execute(task)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM БОТ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DB: dict[str, Task] = {}


def card(t: Task) -> str:
    icon = "Файл готовий" if t.delivery_type == "file" else "Покроковий промпт"
    return (
        f"НОВЕ ЗАВДАННЯ — {t.source}\n\n"
        f"{t.title_ua}\n\n"
        f"Що: {t.what_ua}\n"
        f"Як: {t.how_ua}\n\n"
        f"Час виконання: {t.time_ua}\n"
        f"Бюджет клієнта: {t.budget}\n"
        f"Запропонуй: ${t.price}\n\n"
        f"Результат: {icon}"
    )


def kb(t: Task) -> InlineKeyboardMarkup:
    file_btn = "Отримати файл" if t.delivery_type == "file" else "Отримати промпт"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Відповідь клієнту", callback_data=f"r:{t.uid}"),
            InlineKeyboardButton("Деталі завдання",   callback_data=f"d:{t.uid}"),
        ],
        [
            InlineKeyboardButton(file_btn, callback_data=f"f:{t.uid}"),
        ],
        [
            InlineKeyboardButton("Відкрити на платформі", url=t.url),
            InlineKeyboardButton("Пропустити",            callback_data=f"s:{t.uid}"),
        ],
    ])


class Bot:
    def __init__(self):
        self.scanner  = Scanner()
        self.executor = Executor()
        self.paused   = False
        self.scans    = 0
        self.sent     = 0

    def _auth(self, u: Update) -> bool:
        return UID == 0 or u.effective_user.id == UID

    async def _send(self, u: Update, text: str, markup=None):
        kw = {"disable_web_page_preview": True}
        if markup:
            kw["reply_markup"] = markup
        for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
            await u.effective_message.reply_text(chunk, **kw)

    async def _send_result(self, message, task: Task, caption_prefix=""):
        """Надсилає результат — файлом якщо можливо, інакше текстом"""
        if task.file_path and os.path.exists(task.file_path):
            label = "ГОТОВИЙ ФАЙЛ" if task.delivery_type == "file" else "ПОКРОКОВИЙ ПРОМПТ"
            await message.reply_text(
                f"{label}\n\n"
                f"Скинь цей файл клієнту на платформі.\n"
                f"Посилання: {task.url}",
                disable_web_page_preview=True,
            )
            with open(task.file_path, "rb") as f:
                await message.reply_document(
                    document=InputFile(f, filename=task.filename),
                    caption=f"{task.title_ua} — готово до здачі",
                )
        else:
            # Якщо файл не зберігся — надсилаємо текстом
            chunks = [task.result[i:i+4096] for i in range(0, len(task.result), 4096)]
            for i, chunk in enumerate(chunks):
                prefix = "РЕЗУЛЬТАТ:\n\n" if i == 0 else ""
                await message.reply_text(prefix + chunk, disable_web_page_preview=True)

    async def _push(self, app: Application, t: Task):
        DB[t.uid] = t
        try:
            await app.bot.send_message(
                chat_id=UID,
                text=card(t),
                reply_markup=kb(t),
                disable_web_page_preview=True,
            )
            self.sent += 1
        except Exception as e:
            log.error(f"push: {e}")

    # ── КОМАНДИ ──────────────────────────────────────────────

    async def start(self, u: Update, _):
        if not self._auth(u): return
        await self._send(u,
            "FREELANCE HUNTER v7\n\n"
            "Сканую Freelancer, Guru, PeoplePerHour кожні 15 хв.\n"
            "Claude вирішує що виконувати і виконує на рівні топ-фрілансера.\n\n"
            "Прості завдання: отримуєш готовий файл.\n"
            "Складніші: отримуєш покроковий промпт-гайд.\n\n"
            "Твоя участь:\n"
            "1. Скопіюй відповідь клієнту і відправ на платформі\n"
            "2. Скинь готовий файл клієнту\n"
            "3. Отримай гроші\n\n"
            "/scan — шукати зараз\n"
            "/status — статистика\n"
            "/pause — зупинити\n"
            "/resume — відновити"
        )

    async def scan(self, u: Update, _):
        if not self._auth(u): return
        msg = await u.effective_message.reply_text(
            "Збираю завдання з платформ...\nЗачекай 1-3 хвилини"
        )
        raw = await self.scanner.scan()
        self.scans += 1

        if not raw:
            await msg.edit_text(
                "Нових завдань не знайдено.\n"
                "Всі вже були показані. Перевірю знову через 15 хв."
            )
            return

        await msg.edit_text(
            f"Знайдено {len(raw)} нових.\n"
            f"Claude аналізує і виконує — це займе кілька хвилин..."
        )

        done = skip = 0
        for task in raw[:8]:
            result = self.executor.process(task)
            if result is None:
                skip += 1
                continue
            DB[result.uid] = result
            await u.effective_message.reply_text(
                card(result),
                reply_markup=kb(result),
                disable_web_page_preview=True,
            )
            done += 1
            await asyncio.sleep(2)

        if done:
            await u.effective_message.reply_text(
                f"Готово: {done} завдань виконано.\n"
                f"Пропущено: {skip} (вакансії або потребують доступу до систем клієнта)."
            )
        else:
            await u.effective_message.reply_text(
                "Всі знайдені завдання не підходять.\n"
                "Спробую знову через 15 хв."
            )

    async def status(self, u: Update, _):
        if not self._auth(u): return
        await self._send(u,
            f"Статус: {'ПАУЗА' if self.paused else 'АКТИВНИЙ'}\n"
            f"Сканів: {self.scans}\n"
            f"Надіслано: {self.sent}\n"
            f"Платформи: Freelancer, Guru, PeoplePerHour\n"
            f"Версія: v7 Professional"
        )

    async def pause(self, u: Update, _):
        if not self._auth(u): return
        self.paused = True
        await u.effective_message.reply_text("Зупинено. /resume щоб відновити.")

    async def resume(self, u: Update, _):
        if not self._auth(u): return
        self.paused = False
        await u.effective_message.reply_text("Відновлено!")

    # ── КНОПКИ ───────────────────────────────────────────────

    async def callback(self, u: Update, _):
        q = u.callback_query
        await q.answer()
        if ":" not in q.data:
            return
        action, uid = q.data.split(":", 1)
        t = DB.get(uid)

        if action == "s":
            await q.message.reply_text("Пропущено.")
            return
        if not t:
            await q.message.reply_text("Не знайдено. Запусти /scan знову.")
            return

        # Відповідь клієнту
        if action == "r":
            await q.message.reply_text(
                f"КОПІЮЙ І ВІДПРАВ КЛІЄНТУ НА ПЛАТФОРМІ:\n\n"
                f"{t.reply_en}\n\n"
                f"Посилання: {t.url}",
                disable_web_page_preview=True,
            )

        # Деталі
        elif action == "d":
            await q.message.reply_text(
                f"Оригінальна назва: {t.title}\n\n"
                f"{t.desc[:1000]}\n\n"
                f"Бюджет: {t.budget}\n"
                f"Пропонуй: ${t.price}\n"
                f"Посилання: {t.url}",
                disable_web_page_preview=True,
            )

        # Файл або промпт
        elif action == "f":
            if not t.result:
                await q.message.reply_text("Виконую через Claude...")
                t = self.executor.execute(t)
                DB[uid] = t
            await self._send_result(q.message, t)

    # ── ФОНОВИЙ ЦИКЛ ─────────────────────────────────────────

    async def _loop(self, app: Application):
        await asyncio.sleep(30)
        while True:
            if not self.paused and UID:
                try:
                    raw = await self.scanner.scan()
                    self.scans += 1
                    for task in raw[:6]:
                        result = self.executor.process(task)
                        if result:
                            await self._push(app, result)
                            await asyncio.sleep(3)
                except Exception as e:
                    log.error(f"loop: {e}")
            await asyncio.sleep(900)

    def run(self):
        if not TOKEN or not API_KEY:
            print("Встав TELEGRAM_BOT_TOKEN і ANTHROPIC_API_KEY в Railway Variables!")
            return
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start",  self.start))
        app.add_handler(CommandHandler("help",   self.start))
        app.add_handler(CommandHandler("scan",   self.scan))
        app.add_handler(CommandHandler("status", self.status))
        app.add_handler(CommandHandler("pause",  self.pause))
        app.add_handler(CommandHandler("resume", self.resume))
        app.add_handler(CallbackQueryHandler(self.callback))
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            lambda u, c: u.effective_message.reply_text(
                "Чекай — бот сам надішле завдання кожні 15 хв.\n"
                "Або /scan щоб перевірити зараз."
            )
        ))
        async def on_start(a):
            asyncio.create_task(self._loop(a))
            log.info("v7 Professional запущено!")
        app.post_init = on_start
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    Bot().run()
