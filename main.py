import requests
import tkinter as tk
import threading
import time
import json
import webbrowser
import logging
import os
import http.server
import socketserver
import sys
import traceback
import tkinter.ttk as tk_ttk
from contextlib import contextmanager
from datetime import datetime, timedelta
from tkinter import messagebox, scrolledtext, simpledialog
from dotenv import load_dotenv
from pathlib import Path
from functools import partial

chatters_file = None
settings_file = None
settings_dir = None
CLIENT_ID = None
ACCESS_TOKEN = None
REDIRECT_URI = "http://localhost:3000"
SCOPE = "moderator:read:chatters"
BOTS_TO_IGNORE = {'moobot', 'nightbot', 'streamelements', 'streamlabs', 'wizebot'}
version = "0.6"


def should_ignore_user(username: str) -> bool:
    return username.lower() in {bot.lower() for bot in BOTS_TO_IGNORE}


def parse_duration(duration_str):
    try:
        parts = duration_str.split(':')
        if len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
            return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    except:
        pass
    return timedelta(0)


def format_duration(td):
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def load_chatters_data():
    try:
        with open(chatters_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_chatters_data(data):
    with open(chatters_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)


def update_chatter(username: str, event_type: str, entry_time: datetime = None):
    if should_ignore_user(username):
        return load_chatters_data()
    data = load_chatters_data()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    if username not in data:
        data[username] = {
            "username": username,
            "visits": 1,
            "first_seen": now_str,
            "last_seen": now_str,
            "total_watch_time": "0:00:00",
            "entry_time": now_str
        }
    else:
        user_data = data[username]
        if event_type == 'entry':
            user_data["visits"] = user_data.get("visits", 0) + 1
            user_data["last_seen"] = now_str
            user_data["entry_time"] = now_str

        elif event_type == 'exit' and entry_time:
            user_data["last_seen"] = now_str
            duration = now - entry_time
            if duration.total_seconds() > 0:
                current_total = parse_duration(user_data.get("total_watch_time", "0:00:00"))
                new_total = current_total + duration
                user_data["total_watch_time"] = format_duration(new_total)

            if "entry_time" in user_data:
                del user_data["entry_time"]

    save_chatters_data(data)
    return data


def update_all_online_users(usernames: set):
    usernames = {user for user in usernames if not should_ignore_user(user)}
    data = load_chatters_data()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for username in usernames:
        if username in data:
            data[username]["last_seen"] = now_str
        else:
            data[username] = {
                "username": username,
                "visits": 1,
                "first_seen": now_str,
                "last_seen": now_str,
                "total_watch_time": "0:00:00",
                "entry_time": now_str
            }

    save_chatters_data(data)


def load_settings() -> dict:
    if settings_file and settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text(encoding="utf-8"))
            BOTS_TO_IGNORE.update(settings.get("ignored_bots", []))
            return settings
        except json.JSONDecodeError:
            pass
    return {}


def save_settings(data: dict):
    try:
        with settings_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except OSError as e:
        print("Не удалось сохранить настройки:", e)


def resource_path(rel: str) -> Path:
    base = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(__file__).parent
    return base / rel


def load_twitch_credentials(key_id, key_access):
    return os.getenv(key_id), os.getenv(key_access)


@contextmanager
def redirect_stdout_stderr_to_file(log_path):
    log_path = Path(log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    f = None
    try:
        f = open(str(log_path), "a", encoding="utf-8")
        sys.stdout = f
        sys.stderr = f
        yield
    except Exception:
        try:
            orig_stderr.write("Failed to redirect stdout/stderr:\n")
            orig_stderr.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        yield
    finally:
        try:
            if f:
                f.flush()
                f.close()
        except Exception:
            pass
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr


class TwitchChatLogger:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Twitch Chat Logger (Helix API) v{version}")
        self.root.geometry("900x750")
        self.root.resizable(True, True)
        self.root.configure(bg="#f0f0f0")
        self.broadcaster_id = None
        self.is_monitoring = False
        self.previous_chatters = set()
        self.user_entry_times = {}
        self.access_token = ACCESS_TOKEN
        self.log_file = None
        self.logger = self.setup_logger()
        self.obs_dir = settings_dir / "obs_stats"
        self.obs_dir.mkdir(exist_ok=True)
        self.obs_data_file = self.obs_dir / "obs_data.json"
        self.create_widgets()
        self.restore_fields()
        self.clear_server_logs()

    def clear_server_logs(self):
        try:
            obs_dir = self.obs_dir
            log_filename = "web_server.log"
            log_file = obs_dir / log_filename
            os.remove(log_file)
        except Exception as e:
            pass

    def web_server(self):
        obs_dir = str(self.obs_dir)
        port = 8000
        obs_dir = Path(obs_dir)
        obs_dir_str = str(obs_dir)
        log_filename = "web_server.log"
        log_file = obs_dir / log_filename
        handler = partial(http.server.SimpleHTTPRequestHandler, directory=obs_dir_str)
        with redirect_stdout_stderr_to_file(log_file):
            try:
                print(f"Веб-сервер: раздаёт {obs_dir_str} на порту {port}")
                with socketserver.TCPServer(("", port), handler) as httpd:
                    print(f"Сервер запущен на порту {port}, лог: {log_file}")
                    try:
                        httpd.serve_forever()
                    except KeyboardInterrupt:
                        print("Остановка сервера по KeyboardInterrupt")
                    finally:
                        try:
                            httpd.server_close()
                        except Exception:
                            traceback.print_exc()
            except Exception:
                traceback.print_exc()

    def setup_logger(self):
        logger = logging.getLogger(__name__)
        logging.basicConfig(
            level=logging.INFO,
            filename=settings_dir / "errors.log",
            filemode="a",
            format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        return logger

    def create_widgets(self):
        title = tk.Label(
            self.root,
            text=f"📺 Twitch Chatters Logger v{version}",
            font=("Arial", 16, "bold"),
            bg="#f0f0f0",
            fg="#333"
        )
        title.pack(pady=10)

        self.auth_btn = tk.Button(
            self.root,
            text="🔑 Авторизоваться в Twitch",
            command=self.auth_via_browser,
            bg="#4a90e2",
            fg="white",
            font=("Arial", 12),
            padx=10,
            pady=5
        )
        self.auth_btn.pack(pady=5)
        #
        tk.Label(
            self.root,
            text="🔹 Имя канала:",
            bg="#f0f0f0",
            font=("Arial", 10)
        ).pack(pady=(10, 0))

        self.channel_entry = tk.Entry(self.root, font=("Arial", 12), width=30)
        self.channel_entry.pack(pady=5)

        self.check_btn = tk.Button(
            self.root,
            text="🔍 Проверить канал",
            command=self.check_channel,
            bg="#50e3c2",
            fg="white",
            font=("Arial", 10),
            padx=8,
            pady=3
        )
        self.check_btn.pack(pady=5)

        self.status_label = tk.Label(
            self.root,
            text="⏳ Статус: Не авторизован",
            bg="#f0f0f0",
            fg="orange",
            font=("Arial", 10)
        )
        self.status_label.pack(pady=5)

        btn_frame = tk.Frame(self.root, bg="#f0f0f0")
        btn_frame.pack(pady=10)

        self.start_btn = tk.Button(
            btn_frame,
            text="▶️ Запустить мониторинг",
            command=self.start_monitoring,
            bg="#2ecc71",
            fg="white",
            font=("Arial", 10),
            padx=10,
            pady=5,
            state="disabled"
        )
        self.start_btn.grid(row=0, column=0, padx=5)

        self.stop_btn = tk.Button(
            btn_frame,
            text="⏹️ Остановить",
            command=self.stop_monitoring,
            bg="#e74c3c",
            fg="white",
            font=("Arial", 10),
            padx=10,
            pady=5,
            state="disabled"
        )
        self.stop_btn.grid(row=0, column=1, padx=5)

        self.open_browser_btn = tk.Button(
            self.root,
            text="🌐 Открыть в браузере",
            command=self.web_server_files,
            bg="#204760",
            fg="white",
            font=("Arial", 10, "bold"),
            padx=15,
            pady=8,
            state="disabled"
        )
        self.open_browser_btn.pack(pady=(10, 5))

        self.stats_btn = tk.Button(
            self.root,
            text="📊 Показать статистику",
            command=self.show_statistics,
            bg="#9b59b6",
            fg="white",
            font=("Arial", 11),
            padx=15,
            pady=5
        )
        self.stats_btn.pack(pady=8)

        obs_info_frame = tk.Frame(self.root, bg="#f0f0f0", relief="ridge", bd=2)
        obs_info_frame.pack(pady=5, padx=10, fill=tk.X)
        tk.Label(
            obs_info_frame,
            text="📺 Настройка в OBS (Browser Source):",
            bg="#f0f0f0",
            font=("Arial", 10, "bold"),
            fg="#e74c3c"
        ).pack(pady=(5, 2))

        tk.Label(
            obs_info_frame,
            text="1. Источники → + → Браузер",
            bg="#f0f0f0",
            font=("Arial", 9),
            fg="#555"
        ).pack(anchor="w", padx=10)

        tk.Label(
            obs_info_frame,
            text="2. URL: выберите файл .html из папки",
            bg="#f0f0f0",
            font=("Arial", 9),
            fg="#555"
        ).pack(anchor="w", padx=10)

        tk.Label(
            obs_info_frame,
            text="3. Ширина: 400, Высота: 600",
            bg="#f0f0f0",
            font=("Arial", 9),
            fg="#555"
        ).pack(anchor="w", padx=10)

        self.obs_path_label = tk.Label(
            obs_info_frame,
            text=f"📁 {self.obs_dir}",
            bg="#f0f0f0",
            font=("Arial", 8),
            fg="#3498db"
        )
        self.obs_path_label.pack(pady=(5, 0))

        tk.Button(
            obs_info_frame,
            text="📂 Открыть папку OBS файлов",
            command=self.open_obs_folder,
            bg="#95a5a6",
            fg="white",
            font=("Arial", 9),
            padx=8,
            pady=3
        ).pack(pady=(5, 5))

        tk.Label(
            self.root,
            text="📋 Лог входа/выхода:",
            bg="#f0f0f0",
            font=("Arial", 10)
        ).pack(pady=(10, 0))

        self.log_text = scrolledtext.ScrolledText(
            self.root,
            font=("Consolas", 9),
            height=8,
            wrap=tk.WORD,
            state="disabled"
        )
        self.log_text.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        self.file_label = tk.Label(
            self.root,
            text="📁 JSON файл статистики: не создан",
            bg="#f0f0f0",
            fg="blue",
            font=("Arial", 9)
        )
        self.file_label.pack(pady=(5, 10))

    def restore_fields(self):
        settings = load_settings()
        self.channel_entry.delete(0, tk.END)  # Очистка перед вставкой
        self.channel_entry.insert(0, settings.get("channel", ""))
        if "twitch_user_token" in settings:
            self.access_token = settings["twitch_user_token"]
            self.status_label.config(text="✅ Авторизован (из памяти)", fg="green")

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"[{timestamp}] {message}"
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, full_message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(full_message + "\n")
            except Exception as e:
                self.log(f"⚠️ Ошибка записи в файл: {e}")

    def open_obs_folder(self):
        import subprocess
        if sys.platform == 'win32':
            os.startfile(self.obs_dir)
        elif sys.platform == 'darwin':
            subprocess.run(['open', self.obs_dir])
        else:
            subprocess.run(['xdg-open', self.obs_dir])

    def web_server_files(self):
        auth_url = ("http://localhost:8000/")
        webbrowser.open(auth_url)

    def auth_via_browser(self):
        auth_url = (
            f"https://id.twitch.tv/oauth2/authorize?"
            f"client_id={CLIENT_ID}&"
            f"redirect_uri={REDIRECT_URI}&"
            f"response_type=token&"
            f"scope={SCOPE}"
        )
        webbrowser.open(auth_url)
        messagebox.showinfo(
            "Инструкция",
            "1. Войдите в Twitch под нужным аккаунтом\n"
            "2. Разрешите доступ\n"
            "3. Скопируйте токен из URL после #access_token=\n"
            "4. Вставьте его в поле ввода ниже"
        )

        token = simpledialog.askstring(
            "Ввод токена",
            "Введите Access Token (после #access_token=):"
        )

        if token:
            self.access_token = token.strip()
            self.status_label.config(text="✅ Авторизован", fg="green")
            settings = load_settings()
            settings["twitch_user_token"] = self.access_token
            save_settings(settings)
            messagebox.showinfo("Успех", "Токен сохранён в settings.json!")
            self.status_label.config(text="✅ Авторизован", fg="green")
            messagebox.showinfo("Успех", "Токен сохранён!")

    def check_channel(self):
        channel_name = self.channel_entry.get().strip()
        if not channel_name:
            messagebox.showwarning("Ошибка", "Введите имя канала!")
            return

        url = "https://api.twitch.tv/helix/users"
        headers = {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {self.access_token}"
        }
        params = {"login": channel_name}
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json().get("data", [])
            if data:
                self.broadcaster_id = data[0]["id"]
                display_name = data[0].get("display_name", channel_name)
                self.status_label.config(
                    text=f"✅ Канал: {display_name} (ID: {self.broadcaster_id})",
                    fg="green"
                )
                self.start_btn.config(state="normal")
                self.log(f"✅ Канал найден: {display_name} (ID: {self.broadcaster_id})")
            else:
                raise Exception("Канал не найден")
        except requests.exceptions.HTTPError as e:
            self.status_label.config(text=f"❌ Ошибка API: {e}", fg="red")
            self.log(f"❌ HTTP ошибка при проверке канала: {e}")
        except requests.exceptions.RequestException as e:
            self.status_label.config(text=f"❌ Сетевая ошибка: {e}", fg="red")
            self.log(f"❌ Сетевая ошибка при проверке канала: {e}")
        except Exception as e:
            self.status_label.config(text=f"❌ Ошибка: {e}", fg="red")
            self.log(f"❌ Ошибка проверки канала: {e}")

    def start_monitoring(self):
        if not self.broadcaster_id or not self.access_token:
            messagebox.showwarning("Ошибка", "Сначала авторизуйтесь и проверьте канал!")
            return
        self.log_file = settings_dir / "monitoring.log"
        self.is_monitoring = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.open_browser_btn.config(state="normal")
        self.status_label.config(text="📡 Мониторинг запущен...", fg="blue")
        self.file_label.config(text=f"📁 JSON файл: {chatters_file}")
        self.log(f"📝 Лог-файл создан: {self.log_file}")
        self.log(f"📊 JSON статистика: {chatters_file}")
        self.log(f"📺 OBS файлы: {self.obs_dir}")
        self.log(f"📺 WEB для OBS: http://localhost:8000/")
        self.update_obs_files(set(), None)
        self.create_obs_html_files()
        threading.Thread(target=self.web_server, daemon=True).start()
        threading.Thread(target=self.monitor_chat, daemon=True).start()

    def stop_monitoring(self):
        self.is_monitoring = False
        self.log("💾 Сохранение данных перед выходом...")
        for username, entry_time in self.user_entry_times.items():
            update_chatter(username, 'exit', entry_time)
        self.user_entry_times.clear()
        self.previous_chatters.clear()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_label.config(text="⏸️ Мониторинг остановлен", fg="orange")
        self.log("🛑 Мониторинг остановлен пользователем.")
        self.update_obs_files(set(), None)

    def get_chatters(self):
        url = "https://api.twitch.tv/helix/chat/chatters"
        headers = {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {self.access_token}"
        }
        params = {
            "broadcaster_id": self.broadcaster_id,
            "moderator_id": self.broadcaster_id
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            chatters_data = data.get("data", [])
            if chatters_data:
                chatters = {chatter["user_login"] for chatter in chatters_data}
                return {user for user in chatters if not should_ignore_user(user)}
            else:
                self.log("⚠️ API вернул пустой список чаттеров")
                return set()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                self.log("❌ Токен истек или неверный. Требуется повторная авторизация.")
                self.root.after(0, lambda: self.status_label.config(
                    text="❌ Токен истек",
                    fg="red"
                ))
            elif e.response.status_code == 403:
                self.log("❌ Нет прав для чтения чаттеров. Нужен модератор или стример.")
                self.log(f"   Требуется scope: moderator:read:chatters")
                self.root.after(0, lambda: messagebox.showerror(
                    "Ошибка доступа",
                    "Для чтения списка чаттеров нужно:\n"
                    "1. Быть модератором канала, ИЛИ\n"
                    "2. Авторизоваться под аккаунтом стримера\n\n"
                    "Scope: moderator:read:chatters"
                ))
            else:
                self.log(f"❌ HTTP ошибка {e.response.status_code}: {e}")
            return None
        except Exception as e:
            self.log(f"❌ Ошибка сети: {e}")
            return None

    def get_stream_info(self):
        url = "https://api.twitch.tv/helix/streams"
        headers = {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {self.access_token}"
        }
        params = {"user_id": self.broadcaster_id}
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json().get("data", [])
            if data:
                return {
                    "viewer_count": data[0].get("viewer_count", 0),
                    "title": data[0].get("title", ""),
                    "game_name": data[0].get("game_name", ""),
                    "is_live": True,
                    "started_at": data[0].get("started_at", "")
                }
            else:
                return {
                    "viewer_count": 0,
                    "title": "",
                    "game_name": "",
                    "is_live": False,
                    "started_at": ""
                }
        except Exception as e:
            self.log(f"⚠️ Ошибка получения инфо стрима: {e}")
            return None

    def create_obs_html_files(self):
        # === HTML для счетчика зрителей ===
        viewers_html = f'''<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="30">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Arial, sans-serif;
                background: transparent;
                color: white;
                padding: 15px;
            }}
            .container {{
                background: rgba(0, 0, 0, 0.7);
                border-radius: 12px;
                padding: 15px 20px;
                backdrop-filter: blur(5px);
            }}
            .viewers {{
                font-size: 32px;
                font-weight: bold;
                text-align: center;
            }}
            .viewers .icon {{ font-size: 28px; }}
            .viewers .count {{ 
                color: #00ff88;
                text-shadow: 0 0 10px #00ff88;
            }}
            .game {{
                font-size: 14px;
                text-align: center;
                margin-top: 8px;
                color: #aaa;
            }}
            .offline {{
                color: #ff4444;
                text-shadow: 0 0 10px #ff4444;
            }}
            .error {{
                color: #ffaa00;
                font-size: 12px;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="viewers" id="viewers">⏳ Загрузка...</div>
            <div class="game" id="game"></div>
            <div class="error" id="error"></div>
        </div>
        <script>
            fetch('obs_data.json?t=' + Date.now())
                .then(r => {{
                    if (!r.ok) throw new Error('Файл не найден');
                    return r.json();
                }})
                .then(data => {{
                    const v = document.getElementById('viewers');
                    const g = document.getElementById('game');
                    const e = document.getElementById('error');

                    console.log('Data loaded:', data);
                    e.textContent = 'Обновлено: ' + new Date().toLocaleTimeString();

                    if (data.is_live) {{
                        v.innerHTML = '<span class="icon">👁️</span> <span class="count">' + data.viewer_count + '</span>';
                        g.textContent = '🎮 ' + (data.game_name || 'Не указано');
                    }} else {{
                        v.innerHTML = '<span class="offline">⛔ Стрим оффлайн</span>';
                        g.textContent = '';
                    }}
                }})
                .catch(err => {{
                    console.error('Error:', err);
                    document.getElementById('viewers').innerHTML = '<span class="offline">❌ Ошибка загрузки</span>';
                    document.getElementById('error').textContent = err.message;
                }});
        </script>
    </body>
    </html>'''

        # === HTML для списка чаттеров ===
        chatters_html = '''<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="30">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', Arial, sans-serif;
                background: transparent;
                color: white;
                padding: 10px;
            }
            .container {
                background: rgba(0, 0, 0, 0.7);
                border-radius: 12px;
                padding: 15px;
                max-height: 580px;
                overflow: hidden;
            }
            .header {
                font-size: 18px;
                font-weight: bold;
                margin-bottom: 10px;
                padding-bottom: 8px;
                border-bottom: 2px solid #9b59b6;
            }
            .count {
                color: #9b59b6;
                text-shadow: 0 0 8px #9b59b6;
            }
            .chatters-list {
                font-size: 13px;
                max-height: 500px;
                overflow: hidden;
            }
            .chatter {
                padding: 4px 0;
                border-bottom: 1px solid rgba(255,255,255,0.1);
                display: flex;
                align-items: center;
            }
            .chatter:last-child { border-bottom: none; }
            .num {
                color: #666;
                margin-right: 8px;
                min-width: 25px;
            }
            .name {
                color: #fff;
                text-shadow: 0 0 5px rgba(155, 89, 182, 0.5);
            }
            .more {
                color: #888;
                font-style: italic;
                padding-top: 8px;
                text-align: center;
            }
            .empty { color: #666; text-align: center; padding: 20px; }
            .debug {
                color: #888;
                font-size: 9px;
                margin-top: 10px;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">💬 В чате: <span class="count" id="count">0</span></div>
            <div class="chatters-list" id="list">
                <div class="empty">⏳ Загрузка...</div>
            </div>
            <div class="debug" id="debug"></div>
        </div>
        <script>
            fetch('obs_data.json?t=' + Date.now())
                .then(r => {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then(data => {
                    console.log('Chatters data:', data);

                    document.getElementById('count').textContent = data.chatters_count || 0;
                    document.getElementById('debug').textContent = 
                        'Всего: ' + (data.chatters_count || 0) + 
                        ' | ' + new Date().toLocaleTimeString();

                    const list = document.getElementById('list');

                    if (data.chatters && data.chatters.length > 0) {
                        let html = '';
                        const maxShow = 30;
                        const show = data.chatters.slice(0, maxShow);

                        show.forEach((name, i) => {
                            html += '<div class="chatter"><span class="num">' + (i+1) + '.</span><span class="name">' + name + '</span></div>';
                        });

                        if (data.chatters.length > maxShow) {
                            html += '<div class="more">... и ещё ' + (data.chatters.length - maxShow) + '</div>';
                        }

                        list.innerHTML = html;
                    } else {
                        list.innerHTML = '<div class="empty">чат пуст или стрим оффлайн</div>';
                    }
                })
                .catch(err => {
                    console.error('Error:', err);
                    document.getElementById('list').innerHTML = 
                        '<div class="empty">❌ ' + err.message + '</div>';
                    document.getElementById('debug').textContent = 'Ошибка: ' + err.message;
                });
        </script>
    </body>
    </html>
'''

        # === HTML для ТОП зрителей ===
        top_html = '''<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="30">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', Arial, sans-serif;
                background: transparent;
                color: white;
                padding: 10px;
            }
            .container {
                background: rgba(0, 0, 0, 0.7);
                border-radius: 12px;
                padding: 15px;
            }
            .header {
                font-size: 18px;
                font-weight: bold;
                margin-bottom: 12px;
                padding-bottom: 8px;
                border-bottom: 2px solid #f39c12;
            }
            .top-item {
                padding: 8px 0;
                border-bottom: 1px solid rgba(255,255,255,0.1);
            }
            .top-item:last-child { border-bottom: none; }
            .rank {
                font-size: 20px;
                font-weight: bold;
                display: inline-block;
                width: 30px;
            }
            .rank-1 { color: #ffd700; text-shadow: 0 0 10px #ffd700; }
            .rank-2 { color: #c0c0c0; text-shadow: 0 0 10px #c0c0c0; }
            .rank-3 { color: #cd7f32; text-shadow: 0 0 10px #cd7f32; }
            .name {
                font-size: 15px;
                font-weight: bold;
                color: #fff;
            }
            .stats {
                font-size: 11px;
                color: #888;
                margin-top: 3px;
                padding-left: 30px;
            }
            .empty { color: #666; text-align: center; padding: 20px; }
            .debug {
                color: #888;
                font-size: 9px;
                margin-top: 10px;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">🏆 ТОП ЗРИТЕЛИ</div>
            <div id="toplist">
                <div class="empty">⏳ Загрузка...</div>
            </div>
            <div class="debug" id="debug"></div>
        </div>
        <script>
            fetch('obs_data.json?t=' + Date.now())
                .then(r => {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then(data => {
                    console.log('Top data:', data);
                    const list = document.getElementById('toplist');
                    const debug = document.getElementById('debug');

                    debug.textContent = 'Топ: ' + (data.top_viewers ? data.top_viewers.length : 0) + ' | ' + new Date().toLocaleTimeString();

                    if (data.top_viewers && data.top_viewers.length > 0) {
                        let html = '';
                        data.top_viewers.forEach((item, i) => {
                            const rankClass = i < 3 ? 'rank-' + (i+1) : '';
                            html += '<div class="top-item">';
                            html += '<span class="rank ' + rankClass + '">' + (i+1) + '.</span>';
                            html += '<span class="name">' + item.name + '</span>';
                            html += '<div class="stats">⏱️ ' + item.time + ' | 🔄 ' + item.visits + ' визитов</div>';
                            html += '</div>';
                        });
                        list.innerHTML = html;
                    } else {
                        list.innerHTML = '<div class="empty">Нет данных о зрителях</div>';
                    }
                })
                .catch(err => {
                    console.error('Error:', err);
                    document.getElementById('toplist').innerHTML = 
                        '<div class="empty">❌ ' + err.message + '</div>';
                    document.getElementById('debug').textContent = 'Ошибка: ' + err.message;
                });
        </script>
    </body>
    </html>'''
        # === HTML FULLOVERLAY ===
        online_and_chatters_html = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">    
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            background: transparent;
            color: white;
            padding: 15px;
        }
        .panel {
            background: rgba(0, 0, 0, 0.75);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 15px;
            backdrop-filter: blur(8px);
        }
        .viewers-panel {
            text-align: center;
        }
        .big-number {
            font-size: 48px;
            font-weight: bold;
            color: #00ff88;
            text-shadow: 0 0 20px #00ff88;
        }
        .game-name {
            font-size: 16px;
            color: #aaa;
            margin-top: 5px;
        }
        .section-title {
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 10px;
            padding-bottom: 5px;
            border-bottom: 2px solid;
        }
        .chatters-title { border-color: #9b59b6; }
        .top-title { border-color: #f39c12; }
        .chatters-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 5px;
            font-size: 12px;
        }
        .chatter-name {
            padding: 3px 8px;
            background: rgba(155, 89, 182, 0.3);
            border-radius: 4px;
        }
        .top-item {
            padding: 6px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .top-item:last-child { border-bottom: none; }
        .offline { color: #ff4444; }
    </style>
</head>
<body>
    <div class="panel viewers-panel">
        <div class="big-number" id="viewers">-</div>
        <div class="game-name" id="game"></div>
    </div>

    <div class="panel">
        <div class="section-title chatters-title">💬 В чате (<span id="count">0</span>)</div>
        <div class="chatters-grid" id="chatters"></div>
    </div>

    <script>

        function updateData() {
            fetch('obs_data.json?t=' + Date.now())
                .then(r => r.json())
                .then(data => {

                    const vEl = document.getElementById('viewers');
                    const gEl = document.getElementById('game');

                    if (data.is_live) {
                        vEl.innerHTML = '👁️ ' + data.viewer_count;
                        vEl.className = 'big-number';
                        gEl.textContent = '🎮 ' + data.game_name;
                    } else {
                        vEl.innerHTML = '⛔ ОФФЛАЙН';
                        vEl.className = 'big-number offline';
                        gEl.textContent = '';
                    }


                    document.getElementById('count').textContent = data.chatters_count;
                    const cEl = document.getElementById('chatters');

                    if (data.chatters && data.chatters.length > 0) {
                        const show = data.chatters.slice(0, 20);
                        cEl.innerHTML = show.map(n => '<div class="chatter-name">' + n + '</div>').join('');
                    } else {
                        cEl.innerHTML = '<div style="color:#666">Пусто</div>';
                    }


                    const tEl = document.getElementById('top');
                    if (tEl && data.top_viewers && data.top_viewers.length > 0) {
                        tEl.innerHTML = data.top_viewers.slice(0, 5).map((item, i) =>
                            '<div class="top-item"><b>' + (i+1) + '. ' + item.name + '</b> <small style="color:#888">(' + item.time + ')</small></div>'
                        ).join('');
                    }
                })
                .catch(err => console.error('Ошибка загрузки:', err));
        }


        updateData();

        setInterval(updateData, 10000);
    </script>
</body>
</html>'''

        (self.obs_dir / "viewers.html").write_text(viewers_html, encoding="utf-8")
        (self.obs_dir / "chatters.html").write_text(chatters_html, encoding="utf-8")
        (self.obs_dir / "top_viewers.html").write_text(top_html, encoding="utf-8")
        (self.obs_dir / "online_and_chatters.html").write_text(online_and_chatters_html, encoding="utf-8")
        self.log("✅ HTML файлы для OBS созданы")

    def update_obs_files(self, chatters, stream_info):
        try:
            data = load_chatters_data()
            sorted_data = sorted(
                (item for item in data.items() if not should_ignore_user(item[0])),
                key=lambda x: parse_duration(x[1].get("total_watch_time", "0:00:00")),
                reverse=True
            )[:10]
            top_viewers = [
                {
                    "name": username,
                    "time": user_data.get("total_watch_time", "0:00:00"),
                    "visits": user_data.get("visits", 0)
                }
                for username, user_data in sorted_data
            ]

            obs_data = {
                "viewer_count": stream_info.get("viewer_count", 0) if stream_info else 0,
                "game_name": stream_info.get("game_name", "") if stream_info else "",
                "title": stream_info.get("title", "") if stream_info else "",
                "is_live": stream_info.get("is_live", False) if stream_info else False,
                "chatters_count": len(chatters) if chatters else 0,
                "chatters": sorted([user for user in chatters if not should_ignore_user(user)]) if chatters else [],
                "top_viewers": top_viewers,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(self.obs_data_file, 'w', encoding='utf-8') as f:
                json.dump(obs_data, f, indent=2, ensure_ascii=False)
            if self.obs_data_file.exists():
                pass
            else:
                self.log(f"❌ JSON не создан!")
        except Exception as e:
            self.log(f"⚠️ Ошибка обновления OBS данных: {e}")
            self.logger.exception("Ошибка update_obs_files")

    def monitor_chat(self):
        while self.is_monitoring:
            try:
                current_chatters = self.get_chatters()
                if current_chatters is None:
                    time.sleep(10)
                    continue
                stream_info = self.get_stream_info()
                self.update_obs_files(current_chatters, stream_info)
                newcomers = current_chatters - self.previous_chatters
                leavers = self.previous_chatters - current_chatters
                for user in newcomers:
                    now = datetime.now()
                    self.user_entry_times[user] = now
                    update_chatter(user, 'entry')
                    self.log(f"🟢 [ВХОД] Пользователь '{user}' зашёл в чат")
                for user in leavers:
                    if user in self.user_entry_times:
                        entry_time = self.user_entry_times[user]
                        update_chatter(user, 'exit', entry_time)
                        del self.user_entry_times[user]
                        self.log(f"🔴 [ВЫХОД] Пользователь '{user}' вышел из чата")
                self.previous_chatters = set(current_chatters)
                time.sleep(10)
            except Exception as e:
                self.log(f"⚠️ Ошибка мониторинга: {e}")
                self.logger.exception("Ошибка в цикле мониторинга")
                time.sleep(10)

    def show_statistics(self):
        import tkinter.ttk as ttk
        data = load_chatters_data()
        if not data:
            messagebox.showinfo("Статистика", "Данные отсутствуют.")
            return
        stats_window = tk.Toplevel(self.root)
        stats_window.title("📊 Статистика чаттеров")
        stats_window.geometry("950x650")
        stats_window.configure(bg="#f5f5f5")
        header_label = tk.Label(
            stats_window,
            text="📊 Статистика посетителей чата",
            font=("Arial", 14, "bold"),
            bg="#f5f5f5",
            fg="#333"
        )
        header_label.pack(pady=(10, 5))
        tree_frame = tk.Frame(stats_window, bg="#f5f5f5")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        columns = ("nickname", "visits", "first_seen", "last_seen", "watch_time")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=5)
        column_config = {
            "nickname": ("Ник", 180),
            "visits": ("Визиты", 100),
            "first_seen": ("Первый раз", 170),
            "last_seen": ("Последний раз", 170),
            "watch_time": ("Время пребывания", 150)
        }
        for col, (heading, width) in column_config.items():
            tree.heading(col, text=f"{heading} ↕", anchor="center")
            tree.column(col, width=width, anchor="center")
        v_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        def get_sort_value(username, user_data, column):
            if column == "nickname":
                return username.lower()
            elif column == "visits":
                return int(user_data.get("visits", 0))
            elif column == "first_seen":
                first = user_data.get("first_seen", "")
                try:
                    return datetime.strptime(first, "%Y-%m-%d %H:%M:%S")
                except:
                    return datetime.min
            elif column == "last_seen":
                last = user_data.get("last_seen", "")
                try:
                    return datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
                except:
                    return datetime.min
            elif column == "watch_time":
                return parse_duration(user_data.get("total_watch_time", "0:00:00"))
            return ""

        sort_state = {"column": "watch_time", "reverse": True}

        def populate_tree(sorted_data):
            for item in tree.get_children():
                tree.delete(item)
            for username, user_data in sorted_data:
                tree.insert("", "end", values=(
                    username,
                    user_data.get("visits", 0),
                    user_data.get("first_seen", "N/A"),
                    user_data.get("last_seen", "N/A"),
                    user_data.get("total_watch_time", "0:00:00")
                ))

        def sort_by_column(column):
            if sort_state["column"] == column:
                sort_state["reverse"] = not sort_state["reverse"]
            else:
                sort_state["column"] = column
                sort_state["reverse"] = False if column == "nickname" else True
            sorted_items = sorted(
                data.items(),
                key=lambda x: get_sort_value(x[0], x[1], column),
                reverse=sort_state["reverse"]
            )
            for col in columns:
                arrow = ""
                if col == column:
                    arrow = " ↓" if sort_state["reverse"] else " ↑"
                heading_text = column_config[col][0]
                tree.heading(col, text=f"{heading_text}{arrow}")
            populate_tree(sorted_items)

        for col in columns:
            tree.heading(col, command=lambda c=col: sort_by_column(c))
        sort_by_column("watch_time")
        info_frame = tk.Frame(stats_window, bg="#f5f5f5")
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        total_users = len(data)
        total_visits = sum(u.get("visits", 0) for u in data.values())
        total_time = timedelta()
        for u in data.values():
            total_time += parse_duration(u.get("total_watch_time", "0:00:00"))
        info_text = f"👥 Уникальных: {total_users}  |  🔄 Визитов: {total_visits}  |  ⏱️ Общее время: {format_duration(total_time)}"
        info_label = tk.Label(
            info_frame,
            text=info_text,
            font=("Arial", 10),
            bg="#f5f5f5",
            fg="#555"
        )
        info_label.pack(side=tk.LEFT)
        hint_label = tk.Label(
            info_frame,
            text="💡 Клик на заголовок = сортировка",
            font=("Arial", 9, "italic"),
            bg="#f5f5f5",
            fg="#888"
        )
        hint_label.pack(side=tk.RIGHT)
        btn_frame = tk.Frame(stats_window, bg="#f5f5f5")
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        def export_to_csv():
            csv_file = settings_dir / "chatters_export.csv"
            try:
                with open(csv_file, 'w', encoding='utf-8-sig') as f:
                    f.write("Ник;Визиты;Первый раз;Последний раз;Время пребывания\n")
                    for username, user_data in sorted(data.items()):
                        f.write(f"{username};{user_data.get('visits', 0)};"
                                f"{user_data.get('first_seen', 'N/A')};"
                                f"{user_data.get('last_seen', 'N/A')};"
                                f"{user_data.get('total_watch_time', '0:00:00')}\n")
                messagebox.showinfo("Экспорт", f"Данные экспортированы в:\n{csv_file}")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось экспортировать: {e}")

        export_btn = tk.Button(
            btn_frame,
            text="📁 Экспорт в CSV",
            command=export_to_csv,
            bg="#3498db",
            fg="white",
            font=("Arial", 9),
            padx=10,
            pady=3
        )

        def close_stats():
            stats_window.destroy()

        export_btn.pack(side=tk.LEFT, padx=5)
        close_btn = tk.Button(

            btn_frame,
            text="❌ Закрыть",
            command=close_stats,
            bg="#e74c3c",
            fg="white",
            font=("Arial", 9),
            padx=10,
            pady=3
        )
        close_btn.pack(side=tk.RIGHT, padx=5)

    def on_closing(self):
        if self.is_monitoring:
            self.stop_monitoring()
        settings = load_settings()
        settings["channel"] = self.channel_entry.get().strip()
        settings["ignored_bots"] = list(BOTS_TO_IGNORE)
        if self.access_token:
            settings["twitch_user_token"] = self.access_token
        save_settings(settings)
        self.root.destroy()


def main():
    global chatters_file, settings_file, settings_dir, CLIENT_ID, ACCESS_TOKEN
    app_name = "Twitch Chatters Logger"
    settings_dir = Path(os.getenv('APPDATA')) / app_name
    settings_dir.mkdir(parents=True, exist_ok=True)
    chatters_file = settings_dir / "chatters.json"
    settings_file = settings_dir / "settings.json"
    settings_file.touch(exist_ok=True)
    if not chatters_file.exists():
        save_chatters_data({})
    load_dotenv(resource_path('.env'))
    CLIENT_ID, ACCESS_TOKEN = load_twitch_credentials('twitch_id', 'twitch_user_token')
    if ACCESS_TOKEN is None:
        ACCESS_TOKEN = ""
    if CLIENT_ID is None:
        CLIENT_ID = ""
    root = tk.Tk()
    app = TwitchChatLogger(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    import tkinter.ttk as tk_ttk

    tk.ttk = tk_ttk
    main()
    
