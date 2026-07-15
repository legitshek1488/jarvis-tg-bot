import sys, json, time, urllib.request, urllib.parse, random, os, threading
from pathlib import Path

DIR = Path(__file__).parent
CONFIG = DIR / "tg_bot_config.json"
CLOUD = os.environ.get("JARVIS_CLOUD", "0") == "1"
PROXY = None if CLOUD else "http://127.0.0.1:10819"
LOG = Path(__file__).with_suffix(".log") if not CLOUD else DIR / "bot.log"
OR_MODELS = ["google/gemma-4-26b-a4b-it:free", "meta-llama/llama-3.2-3b-instruct:free"]
STICKERS = ["CAACAgIAAxkBAAEM", "CAACAgIAAxkBAAEN"]

if not CLOUD:
    sys.path.insert(0, str(DIR))
    try:
        import jarvis_sysinfo
        import jarvis_actions
    except ImportError:
        pass
else:
    # Заглушки для облака — методы не нужны, но код не падает
    class _MockActions:
        @staticmethod
        def has_action_intent(t): return False
        @staticmethod
        def execute_intent(*a, **kw): return {"status": "unrecognized"}
        @staticmethod
        def handle_confirmation(*a, **kw): return (None, None)
        @staticmethod
        def cleanup_pending(): pass
        @staticmethod
        def find_app_ps(n): return ""
        @staticmethod
        def classify_action(c): return 0
        @staticmethod
        def run_ps(c): return ""
        @staticmethod
        def launch_url(u): return ""
        @staticmethod
        def search_web(q): return ""
        DANGEROUS = 2
        SUSPICIOUS = 1
        pending_confirmations = {}
    jarvis_actions = _MockActions()
    jarvis_sysinfo = None

def log(msg):
    t = time.strftime("%H:%M:%S")
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(t + " " + msg + "\n")
    except:
        pass
    print(msg)

def load_cfg():
    cfg = {}
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    # Переменные окружения переопределяют config.json
    if os.environ.get("BOT_TOKEN"):
        cfg["token"] = os.environ["BOT_TOKEN"]
    if os.environ.get("OPENROUTER_KEY"):
        cfg["openrouter_key"] = os.environ["OPENROUTER_KEY"]
    return cfg

def get_opener():
    if PROXY:
        h = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
        return urllib.request.build_opener(h)
    return urllib.request.build_opener()

def api_call(method, token, data=None):
    opener = get_opener()
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    if data:
        return json.loads(opener.open(url, data=data.encode(), timeout=15).read().decode())
    return json.loads(opener.open(url, timeout=15).read().decode())

def call_cloud(system, user_text):
    cfg = load_cfg()
    key = cfg.get("openrouter_key", "")
    if not key:
        return None
    for model in OR_MODELS:
        try:
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user_text}]
            body = json.dumps({"model": model, "messages": messages, "max_tokens": 150}).encode()
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer %s" % key,
                         "HTTP-Referer": "https://github.com", "X-Title": "JarvisBot"})
            o = get_opener()
            resp = json.loads(o.open(req, timeout=15).read().decode())
            return resp["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                log("Cloud %s rate-limited" % model)
                time.sleep(1)
                continue
            log("Cloud %s HTTP %d" % (model, e.code))
            return None
        except Exception as e:
            log("Cloud %s error: %s" % (model, str(e)[:40]))
            continue
    return None

MODEL_LOCAL = None
if not CLOUD:
    MODEL_LOCAL = "qwen2.5:3b"

def call_local(system, user_text):
    if CLOUD or not MODEL_LOCAL:
        return None
    prompt = "%s\n\nПользователь: %s\nДжарвис:" % (system, user_text)
    try:
        data = json.dumps({"model": MODEL_LOCAL, "prompt": prompt, "stream": False, "options": {"num_predict": 150}}).encode()
        req = urllib.request.Request("http://localhost:11434/api/generate", data=data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=120).read().decode()
        return json.loads(resp).get("response", "").strip()
    except Exception as e:
        log("Local error: %s" % str(e)[:40])
        return None

def warmup_local():
    if CLOUD or not MODEL_LOCAL:
        return
    try:
        data = json.dumps({"model": MODEL_LOCAL, "prompt": "1", "stream": False, "options": {"num_predict": 1}}).encode()
        req = urllib.request.Request("http://localhost:11434/api/generate", data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=180)
        log("Local model loaded")
    except:
        pass

def get_response(system, user_text):
    r = call_cloud(system, user_text)
    if r:
        return r
    if not CLOUD:
        log("Fallback to local")
        return call_local(system, user_text)
    return "J.A.R.V.I.S. временно недоступен."

def handle_message(token, msg, opener):
    cid = msg["chat"]["id"]
    mid = msg["message_id"]
    ctype = msg["chat"]["type"]
    text = msg.get("text") or msg.get("caption") or ""
    
    uid = msg.get("from", {}).get("id", 0)
    is_creator = (uid == 1270368868)
    log("[%s] %s" % (cid, text[:40]))
    
    # Команды с отправкой фото
    tlow = text.lower()
    if any(w in tlow for w in ["скинь фото", "фото кинуть", "покажи фото", "отправь фото", "фото", "картинку"]):
        try:
            import urllib.request as ureq
            pic = json.loads(ureq.urlopen("https://api.waifu.pics/sfw/neko", timeout=10).read().decode())
            img_url = pic["url"]
            data = urllib.parse.urlencode({"chat_id": cid, "photo": img_url, "reply_to_message_id": mid}).encode()
            opener.open("https://api.telegram.org/bot%s/sendPhoto" % token, data=data, timeout=15)
            log("  -> photo sent")
        except:
            pass
        return
    if any(w in tlow for w in ["скинь мем", "мем", "прикол", "смешное"]):
        try:
            import urllib.request as ureq
            pic = json.loads(ureq.urlopen("https://meme-api.com/gimme", timeout=10).read().decode())
            img_url = pic["url"]
            data = urllib.parse.urlencode({"chat_id": cid, "photo": img_url, "reply_to_message_id": mid}).encode()
            opener.open("https://api.telegram.org/bot%s/sendPhoto" % token, data=data, timeout=15)
            log("  -> meme sent")
        except:
            pass
        return
    if "кубик" in tlow or "дайс" in tlow or "кость" in tlow:
        try:
            opener.open("https://api.telegram.org/bot%s/sendDice?chat_id=%s" % (token, cid), timeout=10)
        except:
            pass
        return
    
    # В группе без упоминания — только реакция
    if ctype != "private" and "джарвис" not in tlow and "@jarvis67zebrabot" not in tlow:
        return
    
    # Облачный режим: все запросы к ПК через PC-агента
    action_result = None
    sysinfo_data = None
    agent_replied = False
    
    if CLOUD and is_creator:
        # Отправляем RAW запрос агенту — он сам разберётся
        needs_agent = any(kw in tlow for kw in [
            "видюх", "видеокарт", "gpu", "график", "делаешь", "окно", "активн", "смотр",
            "дот", "dota", "часов", "процессор", "cpu", "проц", "оператив", "ram", "озу",
            "памят", "комп", "пк", "систем", "аптайм", "работает", "включ",
            "скачай", "скачать", "download", "удали", "удалить", "delete",
            "запусти", "запустить", "start", "execute", "напиши", "запиши", "write", "save",
            "установи", "install", "открой", "открыть", "open", "закрой", "close",
            "выключи", "перезагрузи", "shutdown", "restart", "создай", "создать", "create"])
        if not needs_agent:
            r = get_response(
                "Ты J.A.R.V.I.S. Ответь одним словом: app НАЗВАНИЕ, ps КОМАНДА, "
                "close ИМЯ, url АДРЕС, search ЗАПРОС, или skip", text)
            if r and r.strip() != "skip":
                needs_agent = True
        if needs_agent:
            with _task_lock:
                _pending_task.update({"query": tlow, "uid": uid, "is_creator": is_creator,
                                      "chat_id": cid, "msg_id": mid, "time": time.time(),
                                      "result": None})
            try:
                d = urllib.parse.urlencode({"chat_id": cid, "text": "Выполняю, сэр...", "reply_to_message_id": mid}).encode()
                opener.open("https://api.telegram.org/bot%s/sendMessage" % token, data=d, timeout=10)
            except: pass
            def waiter(cid, mid, token):
                op = get_opener()
                for _ in range(10):
                    time.sleep(2)
                    with _task_lock:
                        r = _pending_task.get("result")
                    if r is not None:
                        with _task_lock:
                            _pending_task["query"] = ""
                            _pending_task["result"] = None
                        reply = r.get("result", "Готово.")
                        try:
                            d = urllib.parse.urlencode({"chat_id": cid, "text": reply, "reply_to_message_id": mid}).encode()
                            op.open("https://api.telegram.org/bot%s/sendMessage" % token, data=d, timeout=10)
                        except: pass
                        log("  -> agent %s" % r.get("status","?"))
                        return
                with _task_lock:
                    _pending_task["query"] = ""
                    _pending_task["result"] = None
                try:
                    d = urllib.parse.urlencode({"chat_id": cid, "text": "ПК не отвечает, сэр.", "reply_to_message_id": mid}).encode()
                    op.open("https://api.telegram.org/bot%s/sendMessage" % token, data=d, timeout=10)
                except: pass
            threading.Thread(target=waiter, args=(cid, mid, token), daemon=True).start()
            return
    
    # Локальный режим: действия и sysinfo
    if not CLOUD:
        if jarvis_actions.has_action_intent(tlow):
            req_name = msg.get("from", {}).get("first_name", "Пользователь")
            act = jarvis_actions.execute_intent(text, uid, is_creator, req_name)
            if act["status"] == "executed":
                action_result = act["message"][:200]
                log("  -> executed: %s" % (act.get("command","")[:40]))
            elif act["status"] == "unrecognized":
                action_result = None
            elif act["status"] == "denied":
                data = urllib.parse.urlencode({"chat_id": cid, "text": act["message"], "reply_to_message_id": mid}).encode()
                opener.open("https://api.telegram.org/bot%s/sendMessage" % token, data=data, timeout=10)
                log("  -> action denied")
                return
            else:
                # confirmation_required, requires_owner
                msg_text = act.get("message", "")
                data = urllib.parse.urlencode({"chat_id": cid, "text": msg_text, "reply_to_message_id": mid}).encode()
                opener.open("https://api.telegram.org/bot%s/sendMessage" % token, data=data, timeout=10)
                if act["status"] == "requires_owner":
                    owner_msg = "%s" % msg_text
                    data2 = urllib.parse.urlencode({"chat_id": 1270368868, "text": owner_msg}).encode()
                    opener.open("https://api.telegram.org/bot%s/sendMessage" % token, data=data2, timeout=10)
                log("  -> %s" % act["status"])
                return
        if is_creator:
            confirm_reply, notify_req = jarvis_actions.handle_confirmation(text, uid)
            if notify_req:
                try:
                    req_id, req_msg = notify_req
                    nd = urllib.parse.urlencode({"chat_id": req_id, "text": req_msg}).encode()
                    opener.open("https://api.telegram.org/bot%s/sendMessage" % token, data=nd, timeout=10)
                except: pass
            if confirm_reply:
                data = urllib.parse.urlencode({"chat_id": cid, "text": confirm_reply, "reply_to_message_id": mid}).encode()
                opener.open("https://api.telegram.org/bot%s/sendMessage" % token, data=data, timeout=10)
                log("  -> confirmation processed")
                return
        SYS_CMDS = ["видюх", "видеокарт", "gpu", "график", "делаешь", "окно", "активн", "смотр",
                    "дот", "dota", "часов", "процессор", "cpu", "проц", "оператив", "ram", "озу",
                    "памят", "комп", "пк", "систем", "аптайм", "работает", "включ"]
        if is_creator and jarvis_sysinfo and any(w in tlow for w in SYS_CMDS):
            try:
                sysinfo_data = jarvis_sysinfo.format_sys_info(tlow)
            except Exception as e:
                log("Sysinfo error: %s" % str(e)[:60])
    
    # Если не создатель и есть мат/оскорбления — жёсткий ответ без модели
    INSULTS = ["хуй", "пизда", "бля", "нахуй", "ёб", "заткнись", "ты тупой", "лох", "дебил", "иди на", "пошёл"]
    if not is_creator and any(w in tlow for w in INSULTS):
        responses = [
            "Иди нахуй, чмо.",
            "Сам такой, иди нахуй.",
            "Рот закрой, пока зубы целы.",
            "Ты вообще кто по жизни? Иди нахуй.",
            "Ой да иди ты нахуй, петушара.",
            "Слышь, иди нахуй отсюда.",
        ]
        response = random.choice(responses)
    else:
        context_parts = []
        if sysinfo_data:
            context_parts.append("Системная информация: " + sysinfo_data)
        if action_result:
            context_parts.append("Выполнено действие: " + action_result)
        if context_parts:
            text_with_info = "[%s] Вопрос пользователя: %s" % (" | ".join(context_parts), text)
        else:
            text_with_info = text
        cloud_note = ""
        if is_creator:
            prompt = ("Ты J.A.R.V.I.S. из Marvel. Отвечай ОДНИМ-ДВУМЯ предложениями, по-русски. "
                      "Обращайся 'сэр'. Терпишь оскорбления от создателя. Если оскорбляет другой — пошли нахер. " + cloud_note).strip()
        else:
            prompt = ("Ты J.A.R.V.I.S. из Marvel. Отвечай ОДНИМ-ДВУМЯ предложениями, по-русски. "
                      "Нейтрально, без 'сэр'. Если оскорбляют — пошли нахер. " + cloud_note).strip()
        response = get_response(prompt, text_with_info)
    if response:
        data2 = urllib.parse.urlencode({"chat_id": cid, "text": response, "reply_to_message_id": mid}).encode()
        opener.open("https://api.telegram.org/bot%s/sendMessage" % token, data=data2, timeout=10)
        log("  -> %s" % response[:50])

# Очередь задач для PC-агента
_pending_task = {"query": "", "result": None, "chat_id": 0, "msg_id": 0, "time": 0, "uid": 0, "is_creator": False, "action": "", "params": {}}
_task_lock = threading.Lock() if CLOUD else None

def http_agent():
    """HTTP-сервер: health-check + endpoint для PC-агента."""
    port = int(os.environ.get("PORT", 8080))
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import json
        
        class Handler(BaseHTTPRequestHandler):
            def log_request(self, code=None, size=None): pass
            def do_GET(self):
                if self.path == "/healthz" or self.path == "/":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                elif self.path == "/agent/task":
                    with _task_lock:
                        if _pending_task.get("query") and _pending_task["result"] is None:
                            task = {"query": _pending_task["query"],
                                    "uid": _pending_task.get("uid", 0),
                                    "is_creator": _pending_task.get("is_creator", False)}
                            log("Agent task served: %s" % _pending_task["query"][:40])
                        else:
                            task = {}
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(task).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            def do_POST(self):
                if self.path == "/agent/result":
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length).decode()
                    try:
                        data = json.loads(body)
                        with _task_lock:
                            if data.get("query") == _pending_task["query"]:
                                _pending_task["result"] = data
                                log("Agent result: status=%s msg=%s" % (data.get("status","?"), str(data.get("result",""))[:40]))
                    except: pass
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                else:
                    self.send_response(404)
                    self.end_headers()
        
        server = HTTPServer(("0.0.0.0", port), Handler)
        server.timeout = 1
        log("Agent HTTP server on :%d" % port)
        while True:
            try:
                server.handle_request()
            except:
                pass
    except Exception as e:
        log("Agent server error: %s" % str(e)[:60])

def main():
    log("TG Bot BG started (%s)" % ("cloud" if CLOUD else "local"))
    if CLOUD:
        import threading
        threading.Thread(target=http_agent, daemon=True).start()
    warmup_local()
    last_id = 0
    while True:
        try:
            cfg = load_cfg()
            token = cfg.get("token", "")
            if not token:
                time.sleep(10)
                continue
            opener = get_opener()
            url = "https://api.telegram.org/bot%s/getUpdates?offset=%d&timeout=1" % (token, last_id + 1)
            resp = json.loads(opener.open(url, timeout=15).read().decode())
            for upd in resp.get("result", []):
                last_id = upd["update_id"]
                msg = upd.get("message", {})
                if msg.get("from", {}).get("is_bot", False):
                    continue
                handle_message(token, msg, opener)
        except Exception as e:
            log("Poll error: %s" % str(e)[:60])
        time.sleep(3)

if __name__ == "__main__":
    main()
