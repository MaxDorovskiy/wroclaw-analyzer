#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Обменная папка с внешним аудитором (Codex на ПК, другая LLM): «что сейчас в проекте».

    .venv\\Scripts\\python.exe scripts\\audit\\export_exchange.py C:\\ai-exchange

Образец — export_exchange.py в RE Analyzer (навык codex-exchange). Кладёт в
<папка>\\wroclaw-analyzer\\:

  snapshot/code/       код на HEAD (git archive, без истории git)
  snapshot/docs/       CLAUDE.md, DEFERRED.md, README.md; правила владельца для
                       всех проектов; память Claude по проекту — то, что он
                       помнит между сессиями (всё — через вычистку)
  snapshot/evidence/   метрики с боевой базы (только чтение), прогон тестов,
                       /api/health боевого сервера
  changes/<база>..<HEAD>/  патчи коммитов с последней проверки аудитора
  README.md            как устроена папка (из scripts/audit/EXCHANGE-README.md)
  STATE.json           что выгружено, от какой базы, итог проверки на секреты

База для патчей — коммит из from-codex/REVIEWED_HEAD (аудитор пишет туда
последний проверенный), а пока его нет — первый коммит репозитория: история
короткая (38 коммитов на 15.10.2026), и для первого аудита полезна вся — в
сообщениях коммитов записано, ЧТО было сломано и чем это подтверждено.
Файлы в from-codex/ (аудитора) выгрузка не трогает; from-claude/ и chats/
не перезаписывает, но прогоняет через вычистку вместе со всем остальным.

Всё выгруженное прогоняется шаблонами export_conversations.REDACT. Остался
секрет или телефон — выгрузка падает и не считается сделанной. Базу, фото и
сессии кабинетов не кладём никогда.
"""
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_conversations import REDACT  # noqa: E402

PROJECT = "wroclaw-analyzer"
TEXT_EXT = {".py", ".js", ".jsx", ".css", ".html", ".md", ".txt", ".json", ".sh", ".ps1",
            ".sql", ".patch", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".svg", ""}
#: Общие шаблоны «ключ=значение» в КОДЕ ловят имена переменных
#: (token = settings.get(...)), поэтому к коду их не применяем.
CODE_SKIP = {"cookie", "secret-kv"}
#: «Почта» в коде, которая не почта человека: заглушки в тестах и фикстурах.
CODE_EMAIL_KEEP = ("@example.com", "@example.invalid", "@anthropic.com", "@localhost")
#: Телефоны-заглушки из тестов и фикстур (make_fixtures.py ставит их вместо
#: настоящих). Скрывать их нельзя: в JSON-фикстуре 900000001 — число, после
#: замены файл перестаёт читаться, и тесты снимка падают. Любой другой номер
#: в коде скрывается и считается находкой: 15.10.2026 так нашлись два
#: настоящих номера, попавших в тест и в комментарий (убраны в HEAD).
CODE_PHONE_KEEP = {"500000000", "899999999", "512987654", "600100200", "600100299", "600111222",
                   "601234567", "900000001", "900000002", "910000000", "910000001", "910000002",
                   "910000003", "910000099", "911223344"}
_HAS_ALNUM = re.compile(r"[A-Za-z0-9]")
_PHONES = ("phone-pl", "phone-ua")


def sh(*cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw).stdout.decode("utf-8", "replace")


def _venv_python(repo):
    for p in (os.path.join(repo, ".venv", "Scripts", "python.exe"), os.path.join(repo, ".venv", "bin", "python")):
        if os.path.exists(p):
            return p
    return sys.executable


def _digits(s):
    d = re.sub(r"\D", "", s)
    return d[2:] if len(d) == 11 and d.startswith("48") else d


def _keep(name, m, code):
    """Совпадение в коде, которое не секрет: заглушка-почта, декоратор, номер-заглушка."""
    if not code:
        return False
    s = m.group(0)
    if name == "email":
        return s.lower().endswith(CODE_EMAIL_KEEP) or not _HAS_ALNUM.search(s.split("@")[0])
    if name in _PHONES:
        return _digits(s) in CODE_PHONE_KEEP
    return False


def redact_text(text, code):
    for name, rx in REDACT:
        if code and name in CODE_SKIP:
            continue
        if name in ("cookie", "secret-kv"):
            text = rx.sub(lambda m: m.group(1) + m.group(2) + "<СКРЫТО>", text)
        else:
            text = rx.sub(lambda m, n=name: m.group(0) if _keep(n, m, code) else "<%s СКРЫТ>" % n, text)
    return text


def redact_file(path, code):
    # newline="" — переводы строк как есть: патч с CRLF, переписанный в LF,
    # перестаёт применяться
    try:
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    except (UnicodeDecodeError, OSError):
        return
    new = redact_text(text, code)
    if new != text:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new)


def left_after(root, code_dirs, skip_dirs):
    left = []
    for d, _dirs, files in os.walk(root):
        if any(d.startswith(s) for s in skip_dirs):
            continue
        code = any(d.startswith(c) for c in code_dirs)
        for fn in files:
            if os.path.splitext(fn)[1] not in TEXT_EXT:
                continue
            p = os.path.join(d, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    t = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            for name, rx in REDACT:
                if code and name in CODE_SKIP:
                    continue
                hits = [m for m in rx.finditer(t) if "СКРЫТ" not in m.group(0) and not _keep(name, m, code)]
                if hits:
                    left.append((os.path.relpath(p, root), name, len(hits)))
    return left


def patches_apply(repo, base, ch):
    """Применяются ли выгруженные (уже вычищенные) патчи к базовому коммиту —
    во временном клоне, не трогая рабочую копию. Аудитор читает код по
    патчам, и вычистка не должна их ломать."""
    patches = sorted(p for p in os.listdir(ch) if p.endswith(".patch"))
    if not patches:
        return {"ok": True, "patches": 0}
    tmp = tempfile.mkdtemp(prefix="wro-exchange-")
    try:
        subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", repo, tmp], check=True, capture_output=True)
        subprocess.run(["git", "-C", tmp, "checkout", "-q", base], check=True, capture_output=True)
        bad = []
        for p in patches:
            r = subprocess.run(["git", "-C", tmp, "apply", "--check", os.path.join(ch, p)], capture_output=True)
            if r.returncode != 0:
                bad.append("%s: %s" % (p, r.stderr.decode("utf-8", "replace").strip()[-200:]))
            else:
                subprocess.run(["git", "-C", tmp, "apply", os.path.join(ch, p)], capture_output=True)
        return {"ok": not bad, "patches": len(patches), "failed": bad}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "patches": len(patches), "failed": [str(e.stderr or e)[-200:]]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _evidence(repo, ev):
    py = _venv_python(repo)
    env = dict(os.environ, PYTHONUTF8="1", GPU_REGISTRY="off")
    jobs = (("data-metrics.md", [py, "scripts/audit/data_metrics.py"]),
            ("tests.txt", [py, "-m", "pytest", "tests", "-q", "-p", "no:warnings"]))
    for name, cmd in jobs:
        r = subprocess.run(cmd, capture_output=True, env=env, cwd=repo)
        out = r.stdout.decode("utf-8", "replace")
        if r.returncode != 0:
            out += "\n\nКОД ВЫХОДА %d\n%s" % (r.returncode, r.stderr.decode("utf-8", "replace")[-2000:])
        with open(os.path.join(ev, name), "w", encoding="utf-8") as f:
            f.write(out)
    try:
        port = os.environ.get("WRO_PORT") or "8020"
        with urllib.request.urlopen("http://127.0.0.1:%s/api/health" % port, timeout=10) as r:
            health = r.read().decode("utf-8")
    except Exception as e:  # сервер выключен — это тоже факт для аудитора
        health = json.dumps({"error": str(e)}, ensure_ascii=False)
    with open(os.path.join(ev, "health.json"), "w", encoding="utf-8") as f:
        f.write(health)


def main(dest):
    repo = sh("git", "rev-parse", "--show-toplevel").strip()
    os.chdir(repo)
    head = sh("git", "rev-parse", "--short", "HEAD").strip()
    first = sh("git", "rev-list", "--max-parents=0", "HEAD").split()[0][:7]
    out = os.path.join(dest, PROJECT)
    for sub in ("from-codex", "from-claude", "chats"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    reviewed = first
    rh = os.path.join(out, "from-codex", "REVIEWED_HEAD")
    if os.path.exists(rh):
        with open(rh, encoding="utf-8") as f:
            reviewed = f.read().strip() or first

    snap = os.path.join(out, "snapshot")
    shutil.rmtree(snap, ignore_errors=True)
    code = os.path.join(snap, "code")
    os.makedirs(code)
    archive = subprocess.run(["git", "archive", "HEAD"], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(code)

    docs = os.path.join(snap, "docs")
    os.makedirs(docs)
    for f in ("CLAUDE.md", "DEFERRED.md", "README.md", "REJECTED.md"):
        if os.path.exists(f):
            shutil.copy(f, docs)
    home = os.path.expanduser("~")
    owner_rules = os.path.join(home, ".claude", "CLAUDE.md")
    if os.path.exists(owner_rules):
        shutil.copy(owner_rules, os.path.join(docs, "owner-rules-all-projects.md"))
    mem = os.path.join(home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", repo), "memory")
    if os.path.isdir(mem):
        shutil.copytree(mem, os.path.join(docs, "claude-memory"))

    ev = os.path.join(snap, "evidence")
    os.makedirs(ev)
    _evidence(repo, ev)

    ch = os.path.join(out, "changes", "%s..%s" % (reviewed, head))
    shutil.rmtree(ch, ignore_errors=True)
    os.makedirs(ch)
    sh("git", "format-patch", "-q", "%s..HEAD" % reviewed, "-o", ch)
    with open(os.path.join(ch, "00-список.md"), "w", encoding="utf-8") as f:
        f.write("# Коммиты %s..%s\n\n" % (reviewed, head))
        f.write(sh("git", "log", "--reverse", "--format=- `%h` %ad %s", "--date=format:%d.%m.%Y %H:%M",
                   "%s..HEAD" % reviewed))

    shutil.copy(os.path.join(repo, "scripts", "audit", "EXCHANGE-README.md"), os.path.join(out, "README.md"))

    # Патчи — тоже код: широкие шаблоны «ключ=значение» в них ловят имена
    # переменных и сигнатуры, а не секреты.
    # Вычищается всё, кроме папок аудиторов from-codex/, from-<имя>/ (файлы не
    # наши): и from-claude/ — там дословные реплики и вложения владельца, — и
    # chats/ (их уже вычистил export_conversations, повтор ничего не портит).
    code_dirs = [code, ch]
    skip = [os.path.join(out, x) for x in os.listdir(out) if x.startswith("from-") and x != "from-claude"]
    for d, _dirs, files in os.walk(out):
        if any(d.startswith(s) for s in skip):
            continue
        for fn in files:
            if os.path.splitext(fn)[1] in TEXT_EXT:
                redact_file(os.path.join(d, fn), any(d.startswith(c) for c in code_dirs))
    left = left_after(out, code_dirs, skip)
    applied = patches_apply(repo, reviewed, ch)
    state = {"project": PROJECT, "exported_head": head,
             "exported_at": datetime.datetime.now().isoformat(timespec="minutes"),
             "changes_since": reviewed, "left_after_redaction": left, "patches_apply": applied}
    with open(os.path.join(out, "STATE.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    print("выгружено: HEAD %s, патчи %s..%s (%d шт.), применяются к базе: %s" % (
        head, reviewed, head, len([x for x in os.listdir(ch) if x.endswith(".patch")]),
        "да" if applied["ok"] else "НЕТ — %s" % applied.get("failed")))
    if left:
        print("ОСТАЛОСЬ после вычистки:", left[:20])
        return 1
    print("проверка: секретов и телефонов не осталось")
    return 0


if __name__ == "__main__":
    sys.exit(main(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else r"C:\ai-exchange")))
