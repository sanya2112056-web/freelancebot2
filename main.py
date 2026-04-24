#!/usr/bin/env python3
"""
FREELANCE HUNTER v6
Claude сам вирішує що виконувати — без жорстких фільтрів.
Скидає тільки те що може зробити за 1-2 промпти.
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
    return text.strip()[:700]


def get_budget(text: str) -> str:
    for p in [r'\$[\d,]+\s*[-–]\s*\$[\d,]+', r'\$[\d,]+\+?', r'£[\d,]+', r'€[\d,]+']:
        m = re.search(p, text, re.I)
        if m:
            return m.group(0).strip()
    return "не вказано"


@dataclass
class Task:
    title: str
    desc: str
    url: str
    source: str
    budget: str = "не вказано"
    uid: str = ""
    # Після Claude аналізу
    title_ua: str = ""
    what_ua: str = ""
    how_ua: str = ""
    time_ua: str = ""
    price: int = 0
    reply_en: str = ""
    result: str = ""
    filename: str = "result.txt"
    file_path: str = ""

    def __post_init__(self):
        self.uid = hashlib.md5((self.url + self.title).encode()).hexdigest()[:10]
        self.desc = clean(self.desc)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# СКАНЕР — збирає ВСЕ, Claude потім відбирає
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
        """Freelancer API — всі свіжі проекти без фільтрів"""
        queries = [
            "chatgpt", "telegram bot", "python script",
            "content writing", "blog article", "copywriting",
            "web scraping", "data entry", "translation",
            "resume", "proofreading", "ai assistant",
            "automation", "google sheets", "email writing",
            "social media", "product description", "chatbot",
            "landing page", "html", "summarize", "research",
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
                    bmin = int(b.get("minimum", 0) or 0)
                    bmax = int(b.get("maximum", 0) or 0)
                    bstr = f"${bmin}-${bmax}" if bmin else "не вказано"
                    tasks.append(Task(
                        title=title, desc=desc,
                        url=f"https://www.freelancer.com/projects/{pid}",
                        source="Freelancer", budget=bstr,
                    ))
            await asyncio.sleep(1)
        log.info(f"Freelancer: {len(tasks)} зібрано")
        return tasks

    async def _guru(self) -> list[Task]:
        import feedparser
        queries = [
            "chatgpt", "telegram bot", "python script",
            "content writing", "blog", "translation",
            "resume", "data entry", "automation",
            "copywriting", "web scraping", "ai",
        ]
        tasks = []
        for q in queries:
            text = await self._get(
                f"https://www.guru.com/jobs/search/index.aspx?output=rss&keyword={q.replace(' ', '+')}",
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
                        title=title, desc=desc, url=url,
                        source="Guru",
                        budget=get_budget(title + " " + desc),
                    ))
            await asyncio.sleep(0.8)
        log.info(f"Guru: {len(tasks)} зібрано")
        return tasks

    async def _pph(self) -> list[Task]:
        import feedparser
        queries = [
            "chatgpt", "telegram bot", "python",
            "content writing", "blog", "translation",
            "resume", "copywriting", "automation",
        ]
        tasks = []
        for q in queries:
            text = await self._get(
                f"https://www.peopleperhour.com/rss/jobs?q={q.replace(' ', '+')}",
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
                        title=title, desc=desc, url=url,
                        source="PeoplePerHour",
                        budget=get_budget(title + " " + desc),
                    ))
            await asyncio.sleep(0.8)
        log.info(f"PeoplePerHour: {len(tasks)} зібрано")
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

        # Тільки нові (не показані раніше)
        new = [t for t in all_tasks if t.uid not in self.seen]
        for t in new:
            self.seen.add(t.uid)
        log.info(f"Нових: {len(new)} з {len(all_tasks)}")
        return new


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLAUDE — аналізує і вирішує сам
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

JUDGE_PROMPT = """Ти AI фріланс агент. Проаналізуй це завдання з фріланс платформи.

ЗАВДАННЯ:
Назва: {title}
Опис: {desc}
Бюджет: {budget}
Платформа: {source}

ТВОЄ ЗАВДАННЯ — вирішити чи можна виконати це за 1-2 промпти в Claude AI.

Приклади що МОЖНА виконати:
- Написати статтю/пост/опис
- Зробити переклад тексту
- Написати резюме або cover letter
- Написати Python скрипт для автоматизації
- Зробити Telegram/Discord бота
- Зробити веб-скрапер
- Переписати/відредагувати текст
- Зробити email послідовність
- Написати контент для соцмереж
- Зробити просту HTML сторінку
- Проаналізувати дані і написати звіт

Приклади що НЕ МОЖНА (вакансія або занадто складне):
- Повноцінна робота на ставці (salary, full-time, senior position)
- Мобільний додаток з нуля
- Складна ML модель
- Дизайн логотипу/бренду
- Відеомонтаж

Відповідай ТІЛЬКИ JSON без markdown:
{{
  "can_do": true або false,
  "reason": "чому можна або не можна (1 речення)",
  "title_ua": "Назва завдання українською",
  "what_ua": "Що конкретно зробимо (1 речення)",
  "how_ua": "Як виконаємо через Claude (1 речення)",
  "time_ua": "30 хв або 1 год або 2 год",
  "price": 50,
  "reply_en": "Готова відповідь клієнту англійською. 2-3 речення. Природньо. Назви ціну і термін.",
  "filename": "result.txt або result.py або result.md"
}}"""

EXECUTE_PROMPT = """Ти топовий AI фріланс виконавець. Виконай завдання ПОВНІСТЮ і якісно.

НАЗВА: {title}
ДЕТАЛІ: {desc}

ПРАВИЛА:
- Виконай повністю — клієнт отримає готовий результат
- Якщо код — повний робочий код з коментарями
- Якщо текст — повний готовий текст
- Якщо переклад — повний переклад
- Якщо бракує деталей — прийми найкраще рішення самостійно
- НЕ пиши "зверніться до мене" або "уточніть деталі"
- Результат має бути готовий до відправки БЕЗ змін"""


class Executor:
    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=API_KEY)

    def _ask(self, prompt: str, max_tokens=3000) -> str:
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
        """Claude сам вирішує чи виконувати"""
        raw = self._ask(
            JUDGE_PROMPT.format(
                title=task.title,
                desc=task.desc[:500],
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
                log.info(f"SKIP: {task.title[:50]} | {d.get('reason', '')}")
                return None

            task.title_ua = d.get("title_ua", task.title[:60])
            task.what_ua  = d.get("what_ua", "")
            task.how_ua   = d.get("how_ua", "")
            task.time_ua  = d.get("time_ua", "1-2 год")
            task.price    = int(d.get("price", 50))
            task.reply_en = d.get("reply_en", "Hi! I can help with this.")
            task.filename = d.get("filename", "result.txt")
            log.info(f"OK: {task.title_ua}")
            return task
        except Exception as e:
            log.error(f"judge parse: {e}")
            return None

    def execute(self, task: Task) -> Task:
        """Claude виконує завдання"""
        result = self._ask(
            EXECUTE_PROMPT.format(title=task.title, desc=task.desc),
            max_tokens=3000,
        )
        task.result = result
        safe = re.sub(r'[^\w\-.]', '_', task.filename)
        path = f"/tmp/{task.uid}_{safe}"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(result)
            task.file_path = path
        except Exception as e:
            log.error(f"save file: {e}")
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
    return (
        f"НОВЕ ЗАВДАННЯ — {t.source}\n\n"
        f"{t.title_ua}\n\n"
        f"Що: {t.what_ua}\n"
        f"Як: {t.how_ua}\n\n"
        f"Час: {t.time_ua}\n"
        f"Бюджет: {t.budget}\n"
        f"Запропонуй: ${t.price}\n\n"
        f"Файл готовий нижче"
    )


def kb(t: Task) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Відповідь клієнту", callback_data=f"r:{t.uid}"),
            InlineKeyboardButton("Деталі",            callback_data=f"d:{t.uid}"),
        ],
        [
            InlineKeyboardButton("Отримати файл",     callback_data=f"f:{t.uid}"),
        ],
        [
            InlineKeyboardButton("Відкрити",          url=t.url),
            InlineKeyboardButton("Пропустити",        callback_data=f"s:{t.uid}"),
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

    async def _push(self, app: Application, t: Task):
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
        await self._send(u,
            "FREELANCE HUNTER v6\n\n"
            "Збираю ВСІ завдання з Freelancer, Guru, PeoplePerHour.\n"
            "Claude сам вирішує що може виконати за 1-2 промпти.\n"
            "Виконує і надсилає готовий файл.\n\n"
            "Твоя участь:\n"
            "1. Скопіюй відповідь клієнту — вставте на платформі\n"
            "2. Отримай файл — скинь клієнту\n"
            "3. Гроші на баланс\n\n"
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
                "Всі вже були показані раніше.\n"
                "Перевірю знову через 15 хв автоматично."
            )
            return

        await msg.edit_text(
            f"Знайдено {len(raw)} нових.\n"
            f"Claude аналізує що може виконати..."
        )

        done = skip = 0
        for task in raw[:10]:
            result = self.executor.process(task)
            if result is None:
                skip += 1
                continue
            DB[result.uid] = result
            await u.effective_message.reply_text(
                card(result), reply_markup=kb(result),
                disable_web_page_preview=True,
            )
            done += 1
            await asyncio.sleep(2)

        if done:
            await u.effective_message.reply_text(
                f"Готово: {done} завдань виконано і надіслано.\n"
                f"Пропущено {skip} (вакансії або надто складні)."
            )
        else:
            await u.effective_message.reply_text(
                f"З {len(raw)} знайдених Claude пропустив всі.\n"
                f"Всі виявились вакансіями або завданнями що потребують доступу до систем клієнта.\n"
                f"Спробую через 15 хв."
            )

    async def status(self, u: Update, _):
        if not self._auth(u): return
        await self._send(u,
            f"Статус: {'ПАУЗА' if self.paused else 'АКТИВНИЙ'}\n"
            f"Сканів: {self.scans}\n"
            f"Надіслано завдань: {self.sent}\n"
            f"Платформи: Freelancer, Guru, PeoplePerHour\n"
            f"Логіка: Claude сам вирішує що виконувати"
        )

    async def pause(self, u: Update, _):
        if not self._auth(u): return
        self.paused = True
        await u.effective_message.reply_text("Зупинено. /resume щоб відновити.")

    async def resume(self, u: Update, _):
        if not self._auth(u): return
        self.paused = False
        await u.effective_message.reply_text("Відновлено! Сканую кожні 15 хв.")

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

        if action == "r":
            await q.message.reply_text(
                f"КОПІЮЙ І ВІДПРАВ КЛІЄНТУ:\n\n{t.reply_en}\n\n"
                f"Посилання: {t.url}",
                disable_web_page_preview=True,
            )

        elif action == "d":
            await q.message.reply_text(
                f"Оригінал: {t.title}\n\n"
                f"{t.desc[:800]}\n\n"
                f"Бюджет: {t.budget}\n"
                f"Пропонуй: ${t.price}\n"
                f"Посилання: {t.url}",
                disable_web_page_preview=True,
            )

        elif action == "f":
            if not t.result:
                await q.message.reply_text("Виконую через Claude...")
                t = self.executor.execute(t)
                DB[uid] = t

            await q.message.reply_text(
                f"Готово — скинь клієнту на платформі:\n{t.url}",
                disable_web_page_preview=True,
            )
            if t.file_path and os.path.exists(t.file_path):
                with open(t.file_path, "rb") as f:
                    await q.message.reply_document(
                        document=InputFile(f, filename=t.filename),
                        caption=t.title_ua,
                    )
            else:
                for chunk in [t.result[i:i+4096] for i in range(0, len(t.result), 4096)]:
                    await q.message.reply_text(chunk)

    async def _loop(self, app: Application):
        await asyncio.sleep(30)
        while True:
            if not self.paused and UID:
                try:
                    raw = await self.scanner.scan()
                    self.scans += 1
                    for task in raw[:8]:
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
            log.info("v6 запущено!")

        app.post_init = on_start
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    Bot().run()
