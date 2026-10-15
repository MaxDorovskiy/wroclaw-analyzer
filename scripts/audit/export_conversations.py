#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выгрузка всех переписок с Claude в читаемый вид — для внешнего аудита.

Переписки лежат в %USERPROFILE%\\.claude\\projects\\C--ClaudeProjects-wroclaw-analyzer\\*.jsonl
(на 15.10.2026 — одна сессия 25,5 МБ с 18.09.2026 и несколькими сжатиями
контекста). Там не только разговор, но и служебные записи, вывод команд,
картинки, а главное — персональные данные: телефоны продавцов из отладки,
почта владельца, а в выводе команд мог оказаться пароль
сайта. Отдавать сырые файлы наружу нельзя.

Образец — scripts/audit/export_conversations.py в RE Analyzer (навык
codex-exchange). Отличия для Вроцлава:
  * ПОЛЬСКИЕ телефоны (+48 и девять цифр) вдобавок к украинским;
  * пароли логинов сайта берутся из deploy/windows/env.ps1 при запуске и
    вычищаются дословно — литералом в коде их держать нельзя (этот файл в git).

Что делает:
  * реплики владельца и ответы ассистента — целиком; вызовы инструментов —
    командой; вывод инструментов — обрезанным до 1 500 знаков;
  * вычищает секреты и телефоны, картинки и «размышления» не выгружает;
  * пишет по файлу на сессию, общий файл реплик владельца, файл сводок при
    сжатии контекста (это сжатая история проекта) и оглавление;
  * в конце прогоняет те же шаблоны по результату и падает, если что-то
    осталось, — выгрузка без этой проверки не считается готовой.

    .venv\\Scripts\\python.exe scripts\\audit\\export_conversations.py C:\\ai-exchange\\wroclaw-analyzer\\chats
"""
import glob
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
# Папка переписок — путь к проекту, где всё, кроме букв и цифр, заменено на «-»
# (C:\ClaudeProjects\wroclaw-analyzer -> C--ClaudeProjects-wroclaw-analyzer).
SRC = os.path.join(os.path.expanduser("~"), ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", ROOT))
TOOL_OUT_MAX = 1500


def _site_password_rules():
    """Пароли логинов сайта из env.ps1 — дословно. Нет файла — нет правил."""
    path = os.path.join(ROOT, "deploy", "windows", "env.ps1")
    rules = []
    try:
        text = open(path, encoding="utf-8-sig").read()
    except OSError:
        return rules
    secrets = set()
    m = re.search(r'WRO_WEB_PASS\s*=\s*"([^"]+)"', text)
    if m:
        secrets.add(m.group(1))
    m = re.search(r'WRO_WEB_USERS\s*=\s*"([^"]+)"', text)
    if m:
        for pair in m.group(1).split(","):
            if ":" in pair:
                secrets.add(pair.split(":", 1)[1])
    for i, s in enumerate(sorted(secrets, key=len, reverse=True)):
        if len(s) >= 6:
            rules.append(("site-password", re.compile(re.escape(s))))
    return rules


# Порядок важен: сначала длинные и конкретные шаблоны.
REDACT = [
    ("github-token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}")),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}")),
    ("telegram-token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b")),
    # Значение cookie — только похожее на токен (буквы, цифры, %._-): у RE
    # Analyzer в шаблоне было ещё голое «session», и в нашей переписке оно
    # превращало код «db: Session = Depends(get_db)» в «СКРЫТО» (15.10.2026).
    ("cookie", re.compile(r"(?i)\b(PHPSESSID|sessionid|session_id|access_token|refresh_token)"
                          r"(\"?\s*[:=]\s*\"?)[A-Za-z0-9%._\-]{8,}")),
    # Значение — с цифрой: пароли и ключи их содержат, а русская фраза из
    # CLAUDE.md «Пустой пароль = открыт всем» — нет, и ловилась как секрет.
    # Настоящие пароли сайта ловит отдельное правило site-password дословно.
    ("secret-kv", re.compile(r"(?i)\b(password|passwd|пароль|secret|api[_-]?key|token)(\"?\s*[:=]\s*\"?)"
                             r"(?!<)(?!\$)(?=[^\s\"',}]*\d)[^\s\"',}]{6,}")),
    *_site_password_rules(),
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+\.[A-Za-z0-9.\-]+")),
    # Польский номер: +48 и девять цифр (601 234 567, 601-234-567, 601234567).
    # Девять цифр подряд — не цена и не id: у Otodom id восемь цифр, у OLX —
    # десять, а цен в сотни миллионов злотых не бывает. Рядом не должно быть
    # букв и цифр: внутри хеша коммита «3170e27e8e…» тоже встречаются девять
    # цифр подряд, и он ловился как телефон.
    ("phone-pl", re.compile(r"(?<![\w/=])(?:\+?48[\s\-]?)?[1-9]\d{2}[\s\-]?\d{3}[\s\-]?\d{3}(?!\w)")),
    ("phone-ua", re.compile(r"(?<![\w/])(?:\+?38)?0\d{2}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\w)")),
]

counts = Counter()

# Служебные тексты, которые система подставляла от имени пользователя: тексты
# навыков, напоминания, вывод слэш-команд. Это не слова владельца.
SKILL_MARKERS = ("Base directory for this skill", "Launching skill", "# Update Config Skill",
                 "## Page contract", "# Fewer Permission Prompts")
SERVICE_PREFIXES = ("<", "[Request interrupted", "Caveat:", "[Image")


def redact(text):
    for name, rx in REDACT:
        def sub(m, name=name):
            counts[name] += 1
            if name in ("cookie", "secret-kv"):
                return m.group(1) + m.group(2) + "<СКРЫТО>"
            return "<%s СКРЫТ>" % name
        text = rx.sub(sub, text)
    return text


def blocks(content):
    """(вид, текст) из поля content записи."""
    if isinstance(content, str):
        yield "text", content
        return
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            yield "text", b.get("text", "")
        elif t == "tool_use":
            inp = b.get("input") or {}
            desc = inp.get("description") or ""
            body = (inp.get("command") or inp.get("text") or inp.get("prompt")
                    or inp.get("content") or json.dumps(inp, ensure_ascii=False))
            yield "tool_use", "%s — %s\n%s" % (b.get("name"), desc, str(body)[:4000])
        elif t == "tool_result":
            c = b.get("content")
            if isinstance(c, list):
                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
            c = str(c or "")
            if len(c) > TOOL_OUT_MAX:
                c = c[:TOOL_OUT_MAX] + "\n…[обрезано: ещё %d знаков]" % (len(c) - TOOL_OUT_MAX)
            yield "tool_result", c
        # image, thinking — не выгружаем


def _pasted(text):
    """Вложение владельца <pasted_content …>…</pasted_content> — показать как цитату."""
    return re.sub(r"<pasted_content[^>]*>(.*?)</pasted_content[^>]*>",
                  lambda m: "\n> [вложение владельца]\n" + "\n".join("> " + l for l in m.group(1).strip().split("\n")),
                  text, flags=re.S)


def render(f, sid, sub=False):
    """Сессия -> (строки, начало, конец, реплик владельца, реплики, сводки).

    У субагента «user» — не владелец, а задание от основного агента: в журнал
    реплик владельца оно не идёт."""
    lines, owner, summaries, first, last, n_owner = [], [], [], None, None, 0
    for raw in open(f, encoding="utf-8", errors="ignore"):
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        typ = o.get("type")
        if typ not in ("user", "assistant"):
            continue
        ts = (o.get("timestamp") or "")[:16].replace("T", " ")
        first = first or ts
        last = ts or last
        for kind, text in blocks((o.get("message") or {}).get("content")):
            text = (text or "").strip()
            if not text:
                continue
            if kind == "text" and typ == "user":
                if sub:
                    lines.append("\n### [%s] ЗАДАНИЕ ОТ ОСНОВНОГО АГЕНТА\n%s\n" % (ts, redact(text)))
                    continue
                if text.startswith("This session is being continued"):
                    summaries.append("## %s · сессия %s\n\n%s\n" % (ts, sid, redact(text)))
                    lines.append("\n### [%s] СВОДКА ПОСЛЕ СЖАТИЯ КОНТЕКСТА — см. 02-сводки-сжатия.md\n" % ts)
                    continue
                if text.startswith(SKILL_MARKERS):
                    lines.append("\n### [%s] (служебный текст навыка, %d знаков — пропущен)\n" % (ts, len(text)))
                    continue
                if text.startswith(SERVICE_PREFIXES) and "<pasted_content" not in text:
                    continue
                n_owner += 1
                t = redact(_pasted(text))
                owner.append("### [%s] сессия %s\n%s\n" % (ts, sid, t))
                lines.append("\n### [%s] ВЛАДЕЛЕЦ\n%s\n" % (ts, t))
            elif kind == "text":
                lines.append("\n### [%s] %s\n%s\n" % (ts, u"СУБАГЕНТ" if sub else u"АССИСТЕНТ", redact(text)))
            elif kind == "tool_use":
                lines.append("\n<details><summary>[%s] вызов: %s</summary>\n\n```\n%s\n```\n</details>\n"
                             % (ts, redact(text.split("\n")[0])[:150], redact(text)))
            elif kind == "tool_result":
                lines.append("\n<details><summary>вывод</summary>\n\n```\n%s\n```\n</details>\n" % redact(text))
    return lines, first, last, n_owner, owner, summaries


def main(out):
    os.makedirs(os.path.join(out, "sessions"), exist_ok=True)
    files = sorted(glob.glob(os.path.join(SRC, "*.jsonl")), key=os.path.getmtime)
    if not files:
        print("переписок не найдено в", SRC)
        return 1
    index, owner, summaries, subs = [], [], [], []
    for f in files:
        sid = os.path.basename(f)[:8]
        lines, first, last, n_owner, own, summ = render(f, sid)
        owner += own
        summaries += summ
        name = "%s_%s.md" % ((first or "????")[:10], sid)
        with open(os.path.join(out, "sessions", name), "w", encoding="utf-8") as w:
            w.write("# Сессия %s (%s — %s)\n" % (sid, first, last))
            w.write("".join(lines))
        size = os.path.getsize(os.path.join(out, "sessions", name))
        index.append((first, last, sid, name, n_owner, size))
    # Субагенты — помощники, которых основной агент запускал на часть работы
    # (на 15.10.2026 два: аудит интерфейса и архива переписок, 24.09).
    for f in sorted(glob.glob(os.path.join(SRC, "*", "subagents", "agent-*.jsonl"))):
        aid = os.path.basename(f)[len("agent-"):-len(".jsonl")][:10]
        desc = ""
        try:
            with open(f[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as m:
                desc = json.load(m).get("description") or ""
        except (OSError, ValueError):
            pass
        lines, first, last, _, _, _ = render(f, aid, sub=True)
        os.makedirs(os.path.join(out, "sessions", "subagents"), exist_ok=True)
        name = "%s_%s.md" % ((first or "????")[:10], aid)
        with open(os.path.join(out, "sessions", "subagents", name), "w", encoding="utf-8") as w:
            w.write("# Субагент %s — %s (%s — %s)\n" % (aid, desc, first, last))
            w.write("".join(lines))
        subs.append((first, aid, desc, name))

    with open(os.path.join(out, "01-реплики-владельца.md"), "w", encoding="utf-8") as w:
        w.write("# Все реплики владельца по времени\n\nЭто журнал решений и требований. "
                "Секреты, телефоны и почта вычищены.\n\n")
        seen, uniq = set(), []
        for x in sorted(owner):
            key = x.split("\n", 1)[0][:20] + x.split("\n", 1)[-1][:300]
            if key not in seen:
                seen.add(key)
                uniq.append(x)
        w.write("\n".join(uniq))
    with open(os.path.join(out, "02-сводки-сжатия.md"), "w", encoding="utf-8") as w:
        w.write("# Сводки при сжатии контекста\n\nКогда разговор переполнял контекст, ассистент "
                "писал сводку сделанного: запросы владельца, решения, файлы, ошибки и как их "
                "исправили. Это сжатая история проекта — читать первой.\n\n")
        w.write("\n".join(summaries))
    with open(os.path.join(out, "00-оглавление.md"), "w", encoding="utf-8") as w:
        w.write("# Переписка владельца с Claude по проекту Wrocław Analyzer\n\n"
                "Проектирование 18.09.2026 шло в облачной сессии — её сырая переписка на этот ПК не "
                "попала, сжатая версия лежит в репозитории: `docs/chat-archive/`.\n"
                "Дальше вся работа — на ПК владельца, это файлы ниже.\n\n"
                "Порядок чтения: `02-сводки-сжатия.md` (сжатая история) → "
                "`01-реплики-владельца.md` (все требования и решения) → сессия целиком, "
                "когда нужен контекст конкретного решения.\n\n"
                "| с | по | сессия | файл | реплик владельца | размер |\n|---|---|---|---|---|---|\n")
        for a, b, sid, name, n, size in sorted(index):
            w.write("| %s | %s | %s | sessions/%s | %d | %.1f МБ |\n" % (a, b, sid, name, n, size / 1e6))
        if subs:
            w.write("\nСубагенты (помощники основного агента: задание и их ответ):\n\n")
            for first, aid, desc, name in sorted(subs):
                w.write("- %s · %s — sessions/subagents/%s\n" % (first, desc, name))
        w.write("\nВычищено: %s\n" % (", ".join("%s %d" % kv for kv in counts.most_common()) or "ничего"))

    # Контроль: те же шаблоны по результату. Остаток — провал выгрузки.
    left = Counter()
    for root, _, fs in os.walk(out):
        for fn in fs:
            t = open(os.path.join(root, fn), encoding="utf-8", errors="ignore").read()
            for name, rx in REDACT:
                hits = [m for m in rx.finditer(t) if "СКРЫТ" not in m.group(0)]
                left[name] += len(hits)
    print("вычищено:", dict(counts))
    print("осталось после вычистки:", {k: v for k, v in left.items() if v} or "ничего")
    return 1 if any(left.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
