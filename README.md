pyinstaller --onefile -n TwitchChatLogger main.py

Откройте получившийся файл TwitchChatLogger.spec и добавьте строчку datas:

pyinstaller TwitchChatLogger.spec --clean

## Скрипт показывает пользователей в чате twitch

Пишет логи в .json и собирает статистику просмотров чата.

## Установка

1. Клонируйте репозиторий с github
2. Установите зависимости 
```bash
pip install -r requirements.txt
```
3. Запустите скрипт 'main.py'
```bash
python main.py
```
## Настройка
1. Авторизируйтесь или зарегистрируйтесь на https://dev.twitch.tv/console, затем нажмите [Подать заявку](https://dev.twitch.tv/console/apps/create) и заполните поля - ***Название***: укажите имя бота, ***OAuth Redirect URL***: http://localhost:3000, **Категория**:
Analytics Tool. Нажмите кнопку ***Создать***.

2. Создайте файл .env в директории скрипта указав имя и значение этой переменной как на примере ниже, замените 0123456789abcdefgh на свой токен с сайта [dev.twitch.tv](https://dev.twitch.tv/console/apps/create) из графы ***Идентификатор клиента***.
```bash
twitch_id=0123456789abcdefg
```
3. Можно упаковать в один .exe файл для удобства
```bash
pyinstaller --onefile -n TwitchChatLogger main.py
```
4. Откройте получившийся файл TwitchChatLogger.spec и добавьте строчку datas в a = Analysis:
```bash
    datas=[('.env', '.')],
```
5. Поставьте в TwitchChatLogger.spec "console=False", если хотите убрать консоль при запуске exe.
```bash
    console=False
```
## Запуск
1. Запустите скрипт 'main.py' или ***TwitchChatLogger.exe*** из папки ***dist*** в каталоге скрипта.
```bash
python main.py
```
2. Нажмите Авторизоваться в Twitch и следуйте инструкциям в подсказках.
## Создано с помощью 

![Static Badge](https://img.shields.io/badge/Python-3.12-blue?style=flat-square)
