pyinstaller --onefile -n TwitchChatLogger main.py

Откройте получившийся файл TwitchChatLogger.spec и добавьте строчку datas:

a = Analysis(
    ...
    datas=[('.env', '.')],   # положить .env в корень временной папки _MEIPASS
    ...
)
console=False

pyinstaller TwitchChatLogger.spec --clean