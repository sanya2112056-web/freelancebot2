#!/usr/bin/env python3
"""
FREELANCE HUNTER v9 — фінальна робоча версія
Знаходить замовлення → дає готовий промпт для claude.ai
"""
import asyncio, aiohttp, hashlib, re, logging, json, os
from dataclasses import dataclass
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    time_ua: str = "1 год"
    price: int = 60
    reply_en: str = ""
    prompt: str = ""

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
            "chatgpt", "telegram bot", "python script",
            "content writing", "blog article", "copywriting",
            "web scraping", "data entry", "translation",
            "resume writing", "proofreading", "ai assistant",
            "automation", "google sheets", "email writing",
            "social media", "product description", "chatbot",
            "ghostwriting", "rewriting", "editing", "research",
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
                    b    = p.get("budget", {})
                    bmin = int(b.get("minimum", 0) or 0)
                    bmax = int(b.get("maximum", 0) or 0)
                    tasks.append(Task(
                        title=title, desc=desc,
                        url=f"https://www.freelancer.com/projects/{pid}",
                        source="Freelancer",
                        budget=f"${bmin}–${bmax}" if bmin else "Not specified",
                    ))
            await asyncio.sleep(1)
        log.info(f"Freelancer: {len(tasks)}")
        return tasks

    async def _guru(self) -> list[Task]:
        import feedparser
        queries = [
            "chatgpt", "telegram+bot", "python+script",
            "content+writing", "blog", "translation",
            "resume", "automation", "copywriting", "rewriting",
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
                    tasks.append(Task(title=title, desc=desc, url=url, source="Guru"))
            await asyncio.sleep(0.8)
        log.info(f"Guru: {len(tasks)}")
        return tasks

    async def _pph(self) -> list[Task]:
        import feedparser
        queries = [
            "chatgpt", "telegram+bot", "python",
            "content+writing", "blog", "translation",
            "resume", "copywriting", "automation",
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
                    tasks.append(Task(title=title, desc=desc, url=url, source="PeoplePerHour"))
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
# CLAUDE — суддя і генератор промптів
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

JUDGE = """You are a senior manager at an AI freelance agency. Analyze this freelance task.

TASK:
Title: {title}
Description: {desc}
Budget: {budget}
Platform: {source}

ACCEPT (can_do=true) if Claude AI can complete it with one detailed prompt:
- Any writing: articles, blogs, emails, social posts, product descriptions, scripts, newsletters
- Documents: resumes, cover letters, proposals, business plans, reports
- Code: Python scripts, Telegram bots, web scrapers, Google Sheets automations, HTML pages
- Translation, proofreading, editing, rewriting
- Research summaries using public information
- Creative writing, ghostwriting

REJECT (can_do=false) if:
- It's a job position (salary, benefits, full-time, years of experience, we are hiring)
- Needs client's private systems or data to work
- Graphic design, video editing, mobile app development

Reply ONLY with JSON, no markdown:
{{
  "can_do": true,
  "reject_reason": "",
  "title_ua": "Назва українською (коротко)",
  "what_ua": "Що потрібно зробити (1 речення українською)",
  "time_ua": "30 хв / 1 год / 2 год",
  "price": 75,
  "reply_en": "Professional bid to client. 3 sentences. Confident, specific about deliverable and timeline. Sound like an expert who has done this 100 times."
}}"""


PROMPT_GEN = """You are a senior AI freelance specialist. Create a perfect Claude prompt for this task.

TASK:
Title: {title}
Description: {desc}

Create a prompt that when pasted into Claude will produce a COMPLETE, PROFESSIONAL, ready-to-deliver result.

The prompt must:
1. Be written in the same language as the task
2. Include all context from the task description
3. Specify exact quality standards expected
4. Ask Claude to deliver more than the minimum — exceed expectations
5. Specify format, length, tone appropriate for the task
6. Include instruction to NOT use asterisks for formatting
7. Tell Claude the result will be sent directly to a paying client

Write ONLY the prompt itself. Nothing else. Start directly with the prompt text."""


class Executor:
    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=API_KEY)

    def _ask(self, prompt: str, max_tokens=1000) -> str:
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
            max_tokens=400,
        )
        try:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                return None
            d = json.loads(m.group(0))
            if not d.get("can_do", False):
                log.info(f"SKIP: {task.title[:55]}")
                return None
            task.title_ua = d.get("title_ua", task.title[:55])
            task.what_ua  = d.get("what_ua", "")
            task.time_ua  = d.get("time_ua", "1 год")
            task.price    = int(d.get("price", 60))
            task.reply_en = d.get("reply_en", "")
            log.info(f"OK: {task.title_ua}")
            return task
        except Exception as e:
            log.error(f"judge: {e}")
            return None

    def make_prompt(self, task: Task) -> str:
        return self._ask(
            PROMPT_GEN.format(title=task.title, desc=task.desc),
            max_tokens=800,
        )

    def process(self, task: Task) -> Optional[Task]:
        task = self.judge(task)
        if not task:
            return None
        task.prompt = self.make_prompt(task)
        return task


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# БОТ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DB: dict[str, Task] = {}


def card(t: Task) -> str:
    return (
        f"НОВЕ ЗАМОВЛЕННЯ — {t.source}\n\n"
        f"{t.title_ua}\n\n"
        f"Що: {t.what_ua}\n\n"
        f"Час: {t.time_ua}\n"
        f"Бюджет: {t.budget}\n"
        f"Запропонуй: ${t.price}"
    )


def kb(t: Task) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Відповідь клієнту", callback_data=f"r:{t.uid}"),
            InlineKeyboardButton("Деталі",            callback_data=f"d:{t.uid}"),
        ],
        [
            InlineKeyboardButton("Промпт для claude.ai", callback_data=f"p:{t.uid}"),
        ],
        [
            InlineKeyboardButton("Відкрити замовлення", url=t.url),
            InlineKeyboardButton("Пропустити",          callback_data=f"s:{t.uid}"),
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

    async def _push(self, app, t: Task):
        DB[t.uid] = t
        try:
            await app.bot.send_message(
                chat_id=UID, text=card(t),
                reply_markup=kb(t),
                disable_web_page_preview=True,
            )
            self.sent += 1
        except Exception as e:
            log.error(f"push: {e}")

    async def start(self, u: Update, _):
        if not self._auth(u): return
        await u.effective_message.reply_text(
            "FREELANCE HUNTER v9\n\n"
            "Сканую Freelancer, Guru, PeoplePerHour кожні 15 хв.\n\n"
            "Як це працює:\n\n"
            "1. Бот знаходить замовлення\n"
            "2. Натискаєш Відповідь клієнту\n"
            "   Копіюєш текст, відкриваєш замовлення, вставляєш\n"
            "3. Клієнт погоджується\n"
            "4. Натискаєш Промпт для claude.ai\n"
            "   Копіюєш, відкриваєш claude.ai, вставляєш\n"
            "   Отримуєш готовий результат\n"
            "5. Копіюєш результат, здаєш клієнту\n"
            "6. Гроші на баланс\n\n"
            "/scan — шукати зараз\n"
            "/status — статистика\n"
            "/pause — зупинити авто-режим\n"
            "/resume — відновити"
        )

    async def scan(self, u: Update, _):
        if not self._auth(u): return
        msg = await u.effective_message.reply_text(
            "Збираю завдання...\nЗачекай 2-3 хвилини"
        )
        raw = await self.scanner.scan()
        self.scans += 1

        if not raw:
            await msg.edit_text(
                "Нових замовлень не знайдено.\n"
                "Всі вже були показані. Перевірю через 15 хв автоматично."
            )
            return

        await msg.edit_text(
            f"Знайдено {len(raw)} нових.\n"
            f"Аналізую через Claude..."
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
                f"Готово. {done} замовлень надіслано.\n"
                f"Пропущено {skip} (вакансії або потребують доступу до систем клієнта)."
            )
        else:
            await u.effective_message.reply_text(
                "Підходящих замовлень не знайдено. Спробую через 15 хв."
            )

    async def status(self, u: Update, _):
        if not self._auth(u): return
        await u.effective_message.reply_text(
            f"Статус: {'ПАУЗА' if self.paused else 'АКТИВНИЙ'}\n"
            f"Сканів: {self.scans}\n"
            f"Надіслано замовлень: {self.sent}\n"
            f"Платформи: Freelancer, Guru, PeoplePerHour"
        )

    async def pause(self, u: Update, _):
        if not self._auth(u): return
        self.paused = True
        await u.effective_message.reply_text("Зупинено. /resume щоб відновити.")

    async def resume(self, u: Update, _):
        if not self._auth(u): return
        self.paused = False
        await u.effective_message.reply_text("Відновлено!")

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
                f"КРОК 1 — ВІДПОВІДЬ КЛІЄНТУ\n\n"
                f"Скопіюй і відправ на платформі:\n\n"
                f"{t.reply_en}\n\n"
                f"Потім: {t.url}",
                disable_web_page_preview=True,
            )

        # Деталі
        elif action == "d":
            await q.message.reply_text(
                f"Оригінал: {t.title}\n\n"
                f"{t.desc[:1000]}\n\n"
                f"Бюджет: {t.budget}\n"
                f"Пропонуй: ${t.price}\n"
                f"Посилання: {t.url}",
                disable_web_page_preview=True,
            )

        # Промпт для claude.ai
        elif action == "p":
            if not t.prompt:
                await q.message.reply_text("Генерую промпт...")
                t.prompt = self.executor.make_prompt(t)
                DB[uid] = t

            if not t.prompt:
                await q.message.reply_text("Помилка. Спробуй ще раз.")
                return

            # Промпт надсилаємо частинами якщо великий
            header = "КРОК 2 — ПРОМПТ ДЛЯ CLAUDE.AI\n\nСкопіюй весь текст нижче і вставте на claude.ai:\n\n"
            full = header + t.prompt

            # Розбиваємо на частини по 4000 символів
            chunks = [full[i:i+4000] for i in range(0, len(full), 4000)]
            for chunk in chunks:
                await q.message.reply_text(chunk, disable_web_page_preview=True)

            await q.message.reply_text(
                "Отримаєш готовий результат.\n"
                "Скопіюй його і здай клієнту через:\n"
                f"{t.url}",
                disable_web_page_preview=True,
            )

    async def _loop(self, app):
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
                "Чекай — бот сам надішле замовлення кожні 15 хв.\n"
                "Або /scan щоб перевірити зараз."
            )
        ))

        async def on_start(a):
            asyncio.create_task(self._loop(a))
            log.info("v9 запущено!")

        app.post_init = on_start
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    Bot().run()
