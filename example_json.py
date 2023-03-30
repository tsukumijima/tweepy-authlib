import dotenv
import os
import json
import tweepy
from pathlib import Path
from requests.cookies import RequestsCookieJar
from tweepy_authlib import CookieSessionUserHandler

try:
    terminal_size = os.get_terminal_size().columns
except OSError:
    terminal_size = 80

# ユーザー名とパスワードを環境変数から取得
dotenv.load_dotenv()
screen_name = os.environ.get('TWITTER_SCREEN_NAME', 'your_screen_name')
password = os.environ.get('TWITTER_PASSWORD', 'your_password')

# 保存した Cookie を使って認証
## 毎回ログインすると不審なログインとして扱われる可能性が高くなるため、
## できるだけ以前認証した際に保存した Cookie を使って認証することを推奨
if Path('cookie.json').exists():

    # 保存した Cookie を読み込む
    with open('cookie.json', 'r') as f:
        cookies_dict = json.load(f)

    # RequestCookieJar オブジェクトに変換
    cookies = RequestsCookieJar()
    for key, value in cookies_dict.items():
        cookies.set(key, value)

    # 読み込んだ RequestCookieJar オブジェクトを CookieSessionUserHandler に渡す
    auth_handler = CookieSessionUserHandler(cookies=cookies)

# スクリーンネームとパスワードを指定して認証
else:

    # スクリーンネームとパスワードを渡す
    ## スクリーンネームまたはパスワードが間違っている場合は、tweepy.BadRequest がスローされる
    auth_handler = CookieSessionUserHandler(screen_name=screen_name, password=password)

    # 現在のログインセッションの Cookie を取得
    cookies = auth_handler.get_cookies()

    # Cookie を pickle 化して保存
    with open('cookie.json', 'w') as f:
        json.dump(cookies.get_dict(), f, ensure_ascii=False, indent=4)

# Tweepy で Twitter API v1.1 にアクセス
api = tweepy.API(auth_handler)
print('-' * terminal_size)
print(api.verify_credentials())
print('-' * terminal_size)
print(api.home_timeline())
print('-' * terminal_size)
