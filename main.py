import requests
import tkinter as tk
import threading
import time
import datetime
import webbrowser
import re
import logging
import os
import sys
from tkinter import messagebox, scrolledtext, simpledialog
from dotenv import load_dotenv
from pathlib import Path


def resource_path(rel: str) -> Path:
    base = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(__file__).parent
    return base / rel


def load_twitch_credentials(key_id, key_access):
    return os.getenv(key_id), os.getenv(key_access)


def open_text_file():
    logs_dir = Path("logs")
    chatters_dir = logs_dir / "Chatters"
    result_table_file = chatters_dir / "result_table.txt"
    path = Path(result_table_file)
    if not path.exists():
        raise FileNotFoundError(path)
    if sys.platform.startswith("win"):
        os.startfile(str(path))
    else:
        print("Файл готов:", path)


class TwitchChatLogger:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Twitch Chat Logger (Helix API) {version}")
        self.root.geometry("800x650")
        self.root.resizable(True, True)
        self.root.configure(bg="#f0f0f0")
        self.app_resolution = (1920, 1080)
        self.broadcaster_id = None
        self.is_monitoring = False
        self.previous_chatters = set()
        self.access_token = ACCESS_TOKEN
        self.log_file = None
        self.logger = self.setup_logger()
        self.create_widgets()

    def setup_logger(self):
        logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO, filename="logs/errors.log", filemode="a",
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        return logger

    def create_widgets(self):
        title = tk.Label(self.root, text=f"📺 Twitch Chatters Logger {version} ", font=("Arial", 16, "bold"),
                         bg="#f0f0f0", fg="#333")
        title.pack(pady=10)

        self.auth_btn = tk.Button(self.root, text="🔑 Авторизоваться в Twitch", command=self.auth_via_browser,
                                  bg="#4a90e2", fg="white", font=("Arial", 12), padx=10, pady=5)
        self.auth_btn.pack(pady=5)

        tk.Label(self.root, text="🔹 Имя канала :", bg="#f0f0f0", font=("Arial", 10)).pack(pady=(10, 0))
        self.channel_entry = tk.Entry(self.root, font=("Arial", 12), width=30)
        self.channel_entry.insert(0, "Streamers")
        self.channel_entry.pack(pady=5)

        self.check_btn = tk.Button(self.root, text="🔍 Проверить канал", command=self.check_channel,
                                   bg="#50e3c2", fg="white", font=("Arial", 10), padx=8, pady=3)
        self.check_btn.pack(pady=5)

        self.status_label = tk.Label(self.root, text="⏳ Статус: Не авторизован", bg="#f0f0f0", fg="orange",
                                     font=("Arial", 10))
        self.status_label.pack(pady=5)
        btn_frame = tk.Frame(self.root, bg="#f0f0f0")
        btn_frame.pack(pady=10)
        self.start_btn = tk.Button(btn_frame, text="▶️ Запустить мониторинг", command=self.start_monitoring,
                                   bg="#2ecc71", fg="white", font=("Arial", 10), padx=10, pady=5, state="disabled")
        self.start_btn.grid(row=0, column=0, padx=5)

        self.stop_btn = tk.Button(btn_frame, text="⏹️ Остановить", command=self.stop_monitoring,
                                  bg="#e74c3c", fg="white", font=("Arial", 10), padx=10, pady=5, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=5)

        self.sort_btn = tk.Button(self.root, text="📊 Сортировать логи", command=self.sort_logs,
                                  bg="#9b59b6", fg="white", font=("Arial", 11), padx=15, pady=5)
        self.sort_btn.pack(pady=8)
        tk.Label(self.root, text="📋 Лог входа/выхода:", bg="#f0f0f0", font=("Arial", 10)).pack(pady=(10, 0))
        self.log_text = scrolledtext.ScrolledText(self.root, font=("Consolas", 9), height=12, wrap=tk.WORD,
                                                  state="disabled")
        self.log_text.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        self.file_label = tk.Label(self.root, text="📁 Лог-файл: не создан", bg="#f0f0f0", fg="blue", font=("Arial", 9))
        self.file_label.pack(pady=(5, 10))

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"[{timestamp}] {message}"
        print(full_message)
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

    def auth_via_browser(self):
        auth_url = (
            f"https://id.twitch.tv/oauth2/authorize?"
            f"client_id={CLIENT_ID}&"
            f"redirect_uri={REDIRECT_URI}&"
            f"response_type=token&"
            f"scope={SCOPE}"
        )
        webbrowser.open(auth_url)
        messagebox.showinfo("Инструкция",
                            "1. Войдите в Twitch под нужным аккаунтом\n"
                            "2. Разрешите доступ\n"
                            "3. Скопируйте токен из URL после #access_token=\n"
                            "4. Вставьте его в поле ввода ниже")

        token = simpledialog.askstring("Ввод токена", "Введите Access Token (после #access_token=):")
        if token:
            self.access_token = token.strip()
            self.status_label.config(text="✅ Авторизован", fg="green")
            messagebox.showinfo("Успех", "Токен сохранён!")


    def check_channel(self):
        channel_name = self.channel_entry.get().strip()
        if not channel_name:
            messagebox.showwarning("Ошибка", "Введите имя канала!")
            return

        url = "https://api.twitch.tv/helix/users"
        headers = {"Client-ID": CLIENT_ID, "Authorization": f"Bearer {self.access_token}"}
        params = {"login": channel_name}
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json().get("data", [])
            if data:
                self.broadcaster_id = data[0]["id"]
                self.status_label.config(text=f"✅ Канал: {channel_name} (ID: {self.broadcaster_id})", fg="green")
                self.start_btn.config(state="normal")
                self.log(f"✅ Канал найден: {channel_name} (ID: {self.broadcaster_id})")
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
        self.is_monitoring = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_label.config(text="📡 Мониторинг запущен...", fg="blue")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_file = f"logs/chatters_log_{timestamp}.txt"
        self.file_label.config(text=f"📁 Лог-файл: {self.log_file}")
        self.log(f"📝 Лог-файл создан: {self.log_file}")
        threading.Thread(target=self.monitor_chat, daemon=True).start()

    def stop_monitoring(self):
        self.is_monitoring = False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_label.config(text="⏸️ Мониторинг остановлен", fg="orange")
        stop_loging = "1"
        self.get_table_stats(chatters_file, stop_loging)

        self.log("🛑 Мониторинг остановлен пользователем.")

    def monitor_chat(self):
        while self.is_monitoring:
            try:
                current_chatters = self.get_chatters()
                if not current_chatters:
                    time.sleep(20)
                    continue

                newcomers = current_chatters - self.previous_chatters
                for user in newcomers:
                    self.log(f"🟢 [ВХОД] Пользователь '{user}' зашёл в чат")
                leavers = self.previous_chatters - current_chatters
                for user in leavers:
                    self.log(f"🔴 [ВЫХОД] Пользователь '{user}' вышел из чата")
                self.previous_chatters = current_chatters
                time.sleep(10)
            except Exception as e:
                self.log(f"⚠️ Ошибка мониторинга: {e}")
                time.sleep(10)

    def get_chatters(self):
        url = "https://api.twitch.tv/helix/chat/chatters"
        headers = {"Client-ID": CLIENT_ID, "Authorization": f"Bearer {self.access_token}"}
        params = {
            "broadcaster_id": self.broadcaster_id,
            "moderator_id": self.broadcaster_id
        }
        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json().get("data", [])
                return {chatter["user_login"] for chatter in data}
            else:
                self.log(f"❌ Ошибка API: {response.status_code} - {response.text}")
                return set()
        except Exception as e:
            self.log(f"❌ Ошибка сети: {e}")
            return set()

    def sort_logs(self):
        try:
            self.log("📊 Начинаю сортировку логов...")
            self.root.update()
            path = Path.cwd()
            processed_count = 0
            for log_file in (path / "logs").iterdir():
                if not log_file.is_file():
                    continue
                if log_file.name == "errors.log":
                    continue
                try:
                    content = log_file.read_text(encoding="utf-8")
                    if not content.strip():
                        os.remove(log_file)
                        continue
                    with open(chatters_file, 'a', encoding="utf-8") as file:
                        file.write(f'\n{content.strip()}')
                    os.remove(log_file)
                    processed_count += 1
                except UnicodeDecodeError:
                    self.log(f"⚠️ Невозможно прочитать {log_file.name} — некорректная кодировка")
                except PermissionError:
                    self.log(f"⚠️ Нет прав на удаление {log_file.name}")
                except Exception as e:
                    self.logger.exception("Ошибка при обработке файла %s", log_file)
                    self.log(f"⚠️ Ошибка обработки {log_file.name}: {e}")
            self.log(f"📁 Обработано файлов: {processed_count}")
            self.get_table_stats(chatters_file)
            open_text_file()
            self.log("✅ Сортировка завершена!")
        except Exception as e:
            self.logger.exception("Ошибка при сортировке логов")
            self.log(f"❌ Ошибка сортировки: {e}")
            messagebox.showerror("Ошибка", f"Ошибка при сортировке: {e}")

    def get_table_stats(self, log_file,stop_loging=None):
        chatters_dir = log_file.parent
        try:
            log_text = log_file.read_text(encoding="utf-8")
        except Exception as e:
            self.log(f"⚠️ Ошибка чтения файла {log_file}: {e}")
            return
        pattern_entry = re.compile(
            r"\[(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\].*?\[ВХОД\].*?['\"](?P<user>[^'\"]+)['\"]",
            flags=re.IGNORECASE | re.UNICODE
        )
        pattern_exit = re.compile(
            r"\[(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\].*?\[ВЫХОД\].*?['\"](?P<user>[^'\"]+)['\"]",
            flags=re.IGNORECASE | re.UNICODE
        )
        entries = []
        exits = {}
        for line in log_text.splitlines():
            line = line.strip()
            if not line:
                continue
            m_in = pattern_entry.search(line)
            m_out = pattern_exit.search(line)
            if m_in:
                try:
                    ts = datetime.datetime.strptime(m_in.group("ts"), "%Y-%m-%d %H:%M:%S")
                    user = m_in.group("user")
                    entries.append((user, ts))
                except Exception:
                    continue
            if m_out:
                try:
                    ts = datetime.datetime.strptime(m_out.group("ts"), "%Y-%m-%d %H:%M:%S")
                    user = m_out.group("user")
                    exits[user] = ts
                except Exception:
                    continue
            if stop_loging:
                now = datetime.datetime.now()
                for user, _ in entries:
                    if user not in exits:
                        exits[user] = now
        stats = {}
        for user, ts in entries:
            day = ts.date()
            if user not in stats:
                stats[user] = {"first": ts, "last": ts, "days": {day}}
            else:
                if ts < stats[user]["first"]:
                    stats[user]["first"] = ts
                if ts > stats[user]["last"]:
                    stats[user]["last"] = ts
                stats[user]["days"].add(day)

        def format_duration(entry_dt, exit_dt):
            if exit_dt is None:
                return "Не выходил"
            delta = exit_dt - entry_dt
            total_seconds = int(delta.total_seconds())
            if total_seconds < 0:
                return "Ошибка времени"
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return f"{hours:02}:{minutes:02}:{seconds:02}"

        rows_with_dt = []
        for user, times in stats.items():
            first_dt = times["first"]
            last_dt = times["last"]
            days_count = len(times["days"])
            first_str = first_dt.strftime("%Y-%m-%d %H:%M:%S")
            last_str = last_dt.strftime("%Y-%m-%d %H:%M:%S")
            exit_dt = exits.get(user)
            duration = format_duration(last_dt, exit_dt)
            rows_with_dt.append({
                "Ник": user,
                "Потоков": str(days_count),
                "Первый заход": first_str,
                "Последний заход str": last_str,
                "Последний заход dt": last_dt,
                "Длительность": duration
            })
        rows_with_dt.sort(key=lambda r: r["Последний заход dt"], reverse=True)
        rows = [
            {
                "Ник": r["Ник"],
                "Потоков": r["Потоков"],
                "Первый заход": r["Первый заход"],
                "Последний заход": r["Последний заход str"],
                "Длительность": r["Длительность"]
            }
            for r in rows_with_dt
        ]
        
        def build_ascii_table(rows):
            headers = ["Ник", "Потоков", "Первый заход", "Последний заход", "Длительность"]
            col_widths = {h: len(h) for h in headers}
            for row in rows:
                for h in headers:
                    col_widths[h] = max(col_widths[h], len(str(row.get(h, ""))))

            def sep_line():
                parts = ["+" + "-" * (col_widths[h] + 2) for h in headers]
                return "".join(parts) + "+\n"

            def format_row(values):
                parts = []
                for h, v in zip(headers, values):
                    s = str(v)
                    parts.append("| " + s + " " * (col_widths[h] - len(s)) + " ")
                return "".join(parts) + "|\n"
            result_table = []
            result_table.append(sep_line())
            result_table.append(format_row(headers))
            result_table.append(sep_line())
            for row in rows:
                result_table.append(format_row([row.get(h, "") for h in headers]))
            result_table.append(sep_line())
            return "".join(result_table)
        if not rows:
            table_str = "Нет найденных заходов — таблица пуста.\n"
        else:
            table_str = build_ascii_table(rows)
        result_table_file = chatters_dir / "result_table.txt"
        result_table_file.write_text(table_str, encoding="utf-8")
        self.log(f"📊 Таблица создана: {Path.cwd()}{result_table_file}")

    def on_closing(self):
        if self.is_monitoring:
            self.stop_monitoring()
        self.root.destroy()


if __name__ == "__main__":
    version = "0.1.8"
    load_dotenv(resource_path('.env'))
    os.makedirs(f"logs", exist_ok=True)
    logs_dir = Path("logs")
    chatters_dir = logs_dir / "Chatters"
    chatters_file = chatters_dir / "chatters_alltime.txt"
    chatters_dir.mkdir(parents=True, exist_ok=True)
    chatters_file.touch(exist_ok=True)
    REDIRECT_URI = "http://localhost:3000"
    SCOPE = "moderator:read:chatters"
    CLIENT_ID, ACCESS_TOKEN = load_twitch_credentials('twitch_id', 'twitch_user_token')
    root = tk.Tk()
    app = TwitchChatLogger(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
