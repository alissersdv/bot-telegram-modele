#!/usr/bin/env python3
"""Bot Telegram de supervision DevOps (modèle sans données personnelles).

Python 3.9+ ; bibliothèque standard uniquement.
"""
import json
import os
import shutil
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_env(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(HERE / ".env")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # organisation/depot
FRONTEND_URL = os.getenv("FRONTEND_URL", "")
BACKEND_HEALTH_URL = os.getenv("BACKEND_HEALTH_URL", "")
GITHUB_INTERVAL = max(30, int(os.getenv("GITHUB_INTERVAL", "90")))
HEALTH_INTERVAL = max(30, int(os.getenv("HEALTH_INTERVAL", "300")))
STATE_PATH = HERE / "state.json"

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit("Configurer TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans .env")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def json_request(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode() if data is not None else None,
        headers=headers or {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def telegram(method, **params):
    result = json_request(f"{API}/{method}", params, timeout=40)
    if not result.get("ok"):
        raise RuntimeError(f"Erreur Telegram: {method}")
    return result["result"]


def keyboard():
    return {"inline_keyboard": [
        [{"text": "État des services", "callback_data": "status"},
         {"text": "Machine", "callback_data": "machine"}],
        [{"text": "Dernière CI/CD", "callback_data": "cicd"},
         {"text": "Historique", "callback_data": "history"}],
        [{"text": "Statistiques", "callback_data": "stats"},
         {"text": "Aide", "callback_data": "help"}],
    ]}


def send(message, chat_id=CHAT_ID, markup=None):
    payload = {"chat_id": chat_id, "text": message[:4000]}
    if markup is not None:
        payload["reply_markup"] = json.dumps(markup, ensure_ascii=False)
    return telegram("sendMessage", **payload)


def github(endpoint):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError("GITHUB_TOKEN ou GITHUB_REPO non configuré")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "devops-telegram-monitor",
    }
    return json_request(f"https://api.github.com/repos/{GITHUB_REPO}/{endpoint}", headers=headers)


def runs(limit=10):
    result = github(f"actions/runs?per_page={limit}")
    return result.get("workflow_runs", [])


def fmt_run(run):
    state = run.get("conclusion") or run.get("status") or "inconnu"
    return (f"#{run['id']} • {run.get('name', 'Workflow')}\n"
            f"État : {state} | Branche : {run.get('head_branch', '?')}\n"
            f"Événement : {run.get('event', '?')}\n"
            f"{run.get('html_url', '')}")


def history_message():
    items = runs(10)
    if not items:
        return "Aucune exécution GitHub Actions trouvée."
    return "10 dernières exécutions :\n\n" + "\n\n".join(fmt_run(x) for x in items)


def run_detail(run_id):
    run = github(f"actions/runs/{run_id}")
    jobs = github(f"actions/runs/{run_id}/jobs?per_page=100").get("jobs", [])
    lines = [fmt_run(run), "", "Jobs :"]
    for job in jobs:
        lines.append(f"• {job.get('name', '?')} : {job.get('conclusion') or job.get('status')}")
        for step in job.get("steps", []):
            if step.get("conclusion") in ("failure", "cancelled", "timed_out"):
                lines.append(f"  ↳ {step.get('name')} : {step.get('conclusion')}")
    return "\n".join(lines)


def statistics():
    items = runs(30)
    completed = [x for x in items if x.get("status") == "completed"]
    success = sum(x.get("conclusion") == "success" for x in completed)
    failed = sum(x.get("conclusion") == "failure" for x in completed)
    return (f"CI/CD — {len(items)} dernières exécutions\n"
            f"Terminées : {len(completed)}\n"
            f"Réussies : {success}\nÉchouées : {failed}\n"
            f"Taux de réussite (terminées) : {success / len(completed) * 100:.0f}%"
            if completed else "Aucune exécution terminée dans les derniers résultats.")


def check_http(url, expected_json=False):
    if not url:
        return None, "URL non configurée"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DevOps-Monitor/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            status = response.status
            body = response.read(2048)
        if expected_json:
            good = status == 200 and json.loads(body).get("status") == "ok"
        else:
            good = status == 200
        return good, f"HTTP {status}" + (" (health invalide)" if not good and status == 200 else "")
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        return False, f"Échec de la vérification ({type(exc).__name__})"


def services():
    return {"Frontend": check_http(FRONTEND_URL),
            "Backend": check_http(BACKEND_HEALTH_URL, expected_json=True)}


def status_message():
    parts = ["État des services :"]
    for name, (ok, detail) in services().items():
        label = "OK" if ok is True else "PANNE" if ok is False else "NON CONFIGURÉ"
        parts.append(f"{name} : {label} — {detail}")
    return "\n".join(parts)


def machine_message():
    total, used, _ = shutil.disk_usage("/")
    with open("/proc/meminfo", encoding="utf-8") as fp:
        mem = {p[0].rstrip(":"): int(p[1]) for line in fp if len(p := line.split()) >= 2}
    ram_used = 100 * (1 - mem["MemAvailable"] / mem["MemTotal"])
    with open("/proc/uptime", encoding="utf-8") as fp:
        uptime = int(float(fp.read().split()[0]))
    return (f"Machine : {socket.gethostname()}\n"
            f"Charge (1/5/15 min) : {' / '.join(f'{v:.2f}' for v in os.getloadavg())}\n"
            f"RAM utilisée : {ram_used:.1f}%\nDisque utilisé : {used / total * 100:.1f}%\n"
            f"Uptime : {uptime // 3600} h {(uptime % 3600) // 60} min")


def execute(command):
    if command in ("start", "help", "menu"):
        return ("Bot de supervision DevOps\n\n"
                "Boutons : services, machine, CI/CD, historique, statistiques.\n"
                "Commandes : /status /machine /cicd /historique /stats /run ID /menu")
    if command == "status":
        return status_message()
    if command == "machine":
        return machine_message()
    if command == "cicd":
        items = runs(1)
        return fmt_run(items[0]) if items else "Aucune exécution trouvée."
    if command in ("history", "historique"):
        return history_message()
    if command == "stats":
        return statistics()
    if command.startswith("run "):
        run_id = command.split(" ", 1)[1].strip()
        if not run_id.isdecimal():
            return "Usage : /run 123456789"
        return run_detail(run_id)
    return "Commande inconnue. Utilisez /menu."


def load_state():
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            return state
    except (FileNotFoundError, ValueError, OSError):
        pass
    return {"seen_runs": [], "health": {}}


def save_state(state):
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(STATE_PATH)


def monitor_github(state):
    items = runs(25)
    seen = set(state.get("seen_runs", []))
    if not state.get("github_initialized"):
        state["seen_runs"] = [x["id"] for x in items]
        state["github_initialized"] = True
        save_state(state)
        return  # Ne pas notifier les anciennes exécutions à l'installation
    for run in reversed(items):
        if run["id"] in seen:
            continue
        if run.get("status") == "completed":
            send("Pipeline terminé :\n\n" + fmt_run(run))
            seen.add(run["id"])
    state["seen_runs"] = list(seen)[-200:]
    save_state(state)


def monitor_health(state):
    health = state.setdefault("health", {})
    for name, (ok, detail) in services().items():
        if ok is None:
            continue
        previous = health.get(name)
        if previous is not None and previous != ok:
            send(f"{'RÉTABLISSEMENT' if ok else 'ALERTE'} — {name}\n{detail}")
        health[name] = ok
    save_state(state)


def main():
    # getUpdates exige que le bot ne possède pas de webhook actif.
    telegram("deleteWebhook", drop_pending_updates=False)
    state = load_state()
    offset = None
    next_github = 0.0
    next_health = 0.0
    print("Bot démarré ; Ctrl+C pour arrêter.", flush=True)
    send("Bot de supervision démarré. Utilisez les boutons.", markup=keyboard())
    while True:
        try:
            now = time.monotonic()
            if now >= next_github and GITHUB_TOKEN and GITHUB_REPO:
                try:
                    monitor_github(state)
                finally:
                    next_github = time.monotonic() + GITHUB_INTERVAL
            if now >= next_health:
                try:
                    monitor_health(state)
                finally:
                    next_health = time.monotonic() + HEALTH_INTERVAL
            payload = {"timeout": 10, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset is not None:
                payload["offset"] = offset
            updates = telegram("getUpdates", **payload)
            for update in updates:
                offset = update["update_id"] + 1
                callback = update.get("callback_query")
                if callback:
                    # Répondre immédiatement pour éviter l'animation permanente des boutons.
                    telegram("answerCallbackQuery", callback_query_id=callback["id"])
                    chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
                    if chat_id != CHAT_ID:
                        continue
                    command = callback.get("data", "menu")
                else:
                    msg = update.get("message", {})
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if chat_id != CHAT_ID:
                        continue
                    text = msg.get("text", "").strip()
                    if not text.startswith("/"):
                        continue
                    command = text[1:].split("@", 1)[0].strip().lower()
                try:
                    result = execute(command)
                    send(result, markup=keyboard())
                except Exception as exc:
                    print(f"Erreur commande : {type(exc).__name__}: {exc}", flush=True)
                    send("Impossible de récupérer les informations demandées.", markup=keyboard())
        except KeyboardInterrupt:
            print("Arrêt demandé.", flush=True)
            break
        except Exception as exc:
            print(f"Erreur de supervision : {type(exc).__name__}: {exc}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    main()
