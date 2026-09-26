#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Клиент реестра заявок на общую видеокарту (gpu_registry.py на ПК владельца).

Один файл, только стандартная библиотека, Python 3.8+. Скопируйте его в свой
проект как есть; основная копия — C:\\gpu-registry\\gpu_client.py.

Коротко:

    from gpu_client import GpuClient
    gpu = GpuClient("evo-archive", models=["qwen3.8:27b-ud-q4km"])

    # короткий разовый запрос (< 1 мин): заявка не нужна, спросить обязательно
    gpu.wait_turn(priority=10)                 # ждёт, пока может работать
    ...                                        # один запрос к Ollama

    # долгая работа: заявка на 1,5 ч с продлением раз в 30 мин
    with gpu.lease(priority=30, note="пересчёт индекса") as lease:
        for batch in batches:
            lease.checkpoint()                 # раз в порцию: ждёт, если карту забрали
            ...                                # порция работы

Правила (полный текст — GET <реестр>/api/gpu/rules):
  * перед каждой порцией спросить may_run;
  * долгая работа — под заявкой 1–2 ч, продление каждые 30 мин, по окончании снять;
  * уступая, выгрузить СВОЮ модель (keep_alive: 0), если её не использует тот,
    кому уступаешь; общую модель (её указали в /api/gpu/projects и другие
    проекты) и чужие модели не выгружать никогда.

Реестр не отвечает — клиент работает по старой осторожной схеме: ничего не
выгружает и ждёт, пока на карте есть модели не из своего списка
(fallback_ok). Так ведут себя все проекты, пока реестр недоступен.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

REGISTRY = os.environ.get("GPU_REGISTRY", "http://192.168.50.20:11435").rstrip("/")
OLLAMA = os.environ.get("GPU_OLLAMA", "http://192.168.50.20:11434").rstrip("/")

CHECK_SEC = 30          # как часто спрашивать may_run, пока ждём
RENEW_SEC = 30 * 60     # продление заявки
LEASE_HOURS = 1.5       # срок одной заявки: упавший прогон держит карту не дольше


class RegistryDown(Exception):
    """Реестр не ответил — работать по осторожной схеме."""


def _http(method, url, body=None, timeout=5):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            msg = None
        raise ValueError("реестр: %s %s" % (e.code, msg or e.reason))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RegistryDown(str(e))


class GpuClient:
    def __init__(self, project, models=(), registry=REGISTRY, ollama=OLLAMA, log=print):
        self.project = project
        self.models = list(models)
        self.registry = registry.rstrip("/")
        self.ollama = ollama.rstrip("/")
        self.log = log or (lambda *a: None)
        self._projects = None       # последний известный /api/gpu/projects

    # ---- реестр ----
    def may_run(self, priority=None):
        """Ответ реестра: {"ok": bool, "holder": {...}|None, "reason": str, ...}.
        Реестр недоступен — RegistryDown."""
        q = {"project": self.project}
        if priority is not None:
            q["priority"] = int(priority)
        return _http("GET", self.registry + "/api/gpu/may_run?" + urllib.parse.urlencode(q))

    def claim(self, hours=LEASE_HOURS, priority=None, note="", models=None, vram_gb=None):
        """Подать или продлить заявку (повторный вызов продлевает, место в очереди сохраняется)."""
        body = {"project": self.project, "hours": hours, "note": note,
                "models": list(models if models is not None else self.models)}
        if priority is not None:
            body["priority"] = int(priority)
        if vram_gb is not None:
            body["vram_gb"] = vram_gb
        return _http("POST", self.registry + "/api/gpu/claims", body)

    def release(self):
        return _http("DELETE", self.registry + "/api/gpu/claims/" + urllib.parse.quote(self.project))

    def projects(self):
        self._projects = _http("GET", self.registry + "/api/gpu/projects")
        return self._projects

    def register(self, priority, description="", host=""):
        """Записать свой список моделей в реестр (правило 6)."""
        return _http("PUT", self.registry + "/api/gpu/projects/" + urllib.parse.quote(self.project),
                     {"models": self.models, "priority": priority,
                      "description": description, "host": host})

    # ---- Ollama ----
    def on_card(self):
        """Имена моделей в видеопамяти; None — Ollama не отвечает."""
        try:
            with urllib.request.urlopen(self.ollama + "/api/ps", timeout=5) as r:
                return [m.get("name") or m.get("model")
                        for m in json.loads(r.read().decode("utf-8")).get("models") or []]
        except Exception:
            return None

    def mine_only(self, model):
        """Модель моя и больше ничья: только такую можно выгружать.
        Список проектов неизвестен — считаем модель общей (не трогаем)."""
        if model not in self.models:
            return False
        pr = self._projects
        if pr is None:
            try:
                pr = self.projects()
            except (RegistryDown, ValueError):
                return False
        return not any(model in (v.get("models") or []) for k, v in pr.items() if k != self.project)

    def unload_mine(self, keep=()):
        """Уступая: выгрузить свои (только свои) модели, кроме тех, что нужны
        следующему (keep — модели из заявки того, кому уступаем)."""
        card = self.on_card() or []
        for m in card:
            if m in keep or not self.mine_only(m):
                continue
            self.unload(m)

    def unload(self, model):
        """keep_alive: 0 для одной модели. Модель для эмбеддингов не умеет
        /api/generate — для неё тот же приём через /api/embed."""
        err = None
        for path, extra in (("/api/generate", {}), ("/api/embed", {"input": ""})):
            try:
                body = dict({"model": model, "keep_alive": 0}, **extra)
                req = urllib.request.Request(self.ollama + path, method="POST",
                                             data=json.dumps(body).encode("utf-8"),
                                             headers={"content-type": "application/json"})
                urllib.request.urlopen(req, timeout=30).read()
                self.log("gpu: выгрузил свою модель %s" % model)
                return True
            except Exception as e:
                err = e
        self.log("gpu: не выгрузил %s: %s" % (model, err))
        return False

    def fallback_ok(self):
        """Реестра нет: можно работать, если на карте нет чужих моделей."""
        card = self.on_card()
        if card is None:
            return False
        return all(m in self.models for m in card)

    # ---- ожидание ----
    def can_run(self, priority=None):
        """(ok, причина). Реестр недоступен — осторожная схема."""
        try:
            r = self.may_run(priority)
            return bool(r.get("ok")), r.get("reason", "")
        except RegistryDown:
            ok = self.fallback_ok()
            return ok, "реестр не отвечает; " + ("на карте нет чужих моделей" if ok
                                                  else "на карте чужая модель или Ollama не отвечает")

    def wait_turn(self, priority=None, max_wait=None, on_yield=True):
        """Ждать, пока можно работать. Возвращает True, False — если истёк max_wait (сек)."""
        t0, told, unloaded = time.time(), None, False
        while True:
            ok, why = self.can_run(priority)
            if ok:
                if told:
                    self.log("gpu: можно работать (%s)" % why)
                return True
            if why != told:
                self.log("gpu: жду — %s" % why)
                told = why
            if on_yield and not unloaded and not why.startswith("реестр не отвечает"):
                self.unload_mine(keep=self._holder_models(priority))
                unloaded = True
            if max_wait is not None and time.time() - t0 > max_wait:
                return False
            time.sleep(CHECK_SEC)

    def _holder_models(self, priority):
        try:
            h = self.may_run(priority).get("holder") or {}
            return list(h.get("models") or [])
        except (RegistryDown, ValueError):
            return []

    def lease(self, priority=None, note="", hours=LEASE_HOURS, vram_gb=None, models=None):
        return Lease(self, priority, note, hours, vram_gb, models)


class Lease:
    """Заявка на время долгой работы: подаётся на входе, продлевается в фоне
    раз в 30 минут, снимается на выходе (и при исключении)."""

    def __init__(self, gpu, priority, note, hours, vram_gb, models):
        self.gpu, self.priority, self.note = gpu, priority, note
        self.hours, self.vram_gb, self.models = hours, vram_gb, models
        self._stop = threading.Event()
        self._thread = None
        self._last_check = 0.0

    def _claim(self):
        try:
            self.gpu.claim(self.hours, self.priority, self.note, self.models, self.vram_gb)
            return True
        except RegistryDown:
            return False

    def _renew(self):
        while not self._stop.wait(RENEW_SEC):
            if self._claim():
                self.gpu.log("gpu: заявка продлена")

    def __enter__(self):
        # Заявку ставим сразу — так мы встаём в очередь равных; потом ждём своей очереди.
        if not self._claim():
            self.gpu.log("gpu: реестр не отвечает — работаю по осторожной схеме")
        self._thread = threading.Thread(target=self._renew, daemon=True, name="gpu-lease")
        self._thread.start()
        self.gpu.wait_turn(self.priority)
        self._last_check = time.time()
        return self

    def checkpoint(self, every=60):
        """Звать между порциями работы. Не чаще раза в `every` секунд спрашивает
        реестр; если карту забрали — выгружает свою модель и ждёт."""
        if time.time() - self._last_check < every:
            return
        self._last_check = time.time()
        ok, why = self.gpu.can_run(self.priority)
        if not ok:
            self.gpu.log("gpu: уступаю — %s" % why)
            self.gpu.wait_turn(self.priority)
            self._last_check = time.time()

    def __exit__(self, *exc):
        self._stop.set()
        try:
            self.gpu.release()
        except (RegistryDown, ValueError):
            pass
        return False


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "re-analyzer"
    g = GpuClient(p)
    try:
        print(json.dumps(g.may_run(), ensure_ascii=False, indent=1))
    except RegistryDown as e:
        print("реестр не отвечает:", e)
    print("на карте:", g.on_card())
