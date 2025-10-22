
# tweepy-authlib

[![PyPI - Version](https://img.shields.io/pypi/v/tweepy-authlib.svg)](https://pypi.org/project/tweepy-authlib)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/tweepy-authlib.svg)](https://pypi.org/project/tweepy-authlib)

> [!IMPORTANT]  
> **2025年10月リリースの tweepy-authlib v1.7.0 以降では、長らく動作していなかったログイン処理が正常に動作するようになりました！また、Python 3.12・3.13 に対応しました。**  
> [curl-cffi](https://github.com/lexiforest/curl_cffi) を使い API リクエスト時の TLS フィンガープリントを Chrome に偽装し、また [X-Client-Transaction-ID ヘッダーを生成](https://github.com/iSarabjitDhiman/XClientTransaction)・付与した状態でリクエストすることで、ログインの成功確率が大幅に向上しています。  
> さらに、取得済みの Cookie で Twitter API v1.1 にアクセスする際の Bot 判定対策も大幅に強化されています。  
> **凍結やアカウントロックのリスクを下げるためにも、最新版の tweepy-authlib の利用をおすすめします。**
> 
> なお、**ログイン実績のない IP からログインを実行すると、ほぼ確実に確認コードの入力が必要となり、このライブラリではログイン処理に失敗します。**  
> 同じ IP を共有しているデバイスから Web 版公式クライアントで当該アカウントにログインし、確認コードの入力を終えてから時間を空けて実行すると、ログインできる可能性が高くなります。

> [!WARNING]  
> **旧 TweetDeck の完全廃止にともない、2023/09/14 頃から、内部的に残存していた Twitter API v1.1 の段階的なシャットダウンが開始されています。**  
> **2025年10月時点では、下記 API が既に廃止されています ([参考](https://github.com/dimdenGD/OldTweetDeck/blob/main/src/interception.js)) 。**  
> - `search/tweets` : ツイート検索
> - `search/universal` : ツイート検索 (旧 TweetDeck 独自 API)
> - `users/search` : ユーザー検索
> - `statuses/update` : ツイート投稿
> - `statuses/retweet/:id` : リツイート
> - `statuses/unretweet/:id` : リツイート取り消し
> - `statuses/show/:id` : ツイート詳細
> - `statuses/destroy/:id` : ツイート削除
> - `statuses/user_timeline` : ユーザーのツイート一覧
> - `statuses/bookmarks` : ブックマーク一覧
> - `translations/show` : 翻訳されたツイート詳細
> - `favorites/list` : ユーザーのいいね！一覧
> - `friends/list` : ユーザーのフォロー一覧 (2025年10月中旬廃止)
> - `lists/statuses` : リストのツイート一覧
> 
> 2025年10月時点では、2023年09月にサーバー負荷が高い API が一括で廃止された以降、大きな動きはありません。  
> **`account/verify_credentials`・`statuses/home_timeline`・`followers/list` など、上記以外の一部 API は今なお残存しており、tweepy と tweepy-authlib を組み合わせることでアクセス可能です (下記サンプルコードを参照) 。**  
> ただし、リストにない API も既に廃止されている可能性があることに注意してください。
>
> **現在 tweepy-authlib を利用して上記の廃止された API 機能を再現するには、別途 GraphQL API (Twitter Web App の内部 API) クライアントを自作する必要があります。**  
> 私が [KonomiTV](https://github.com/tsukumijima/KonomiTV) 向けに開発した GraphQL API クライアントの実装が [こちら](https://github.com/tsukumijima/KonomiTV/blob/master/server/app/utils/TwitterGraphQLAPI.py) ([使用例](https://github.com/tsukumijima/KonomiTV/blob/master/server/app/routers/TwitterRouter.py)) にありますので、参考になれば幸いです。  
> また現時点で廃止されていない API を利用したサンプルコードが [example_json.py](example_json.py) と [example_pickle.py](example_pickle.py) にありますので、そちらもご一読ください。

-----

**Table of Contents**

- [tweepy-authlib](#tweepy-authlib)
  - [Description](#description)
  - [Installation](#installation)
  - [Usage](#usage)
    - [With JSON](#with-json)
    - [With Pickle](#with-pickle)
  - [License](#license)

## Description

Twitter Web App (Web 版公式クライアント) の内部 API を使い、[Tweepy](https://github.com/tweepy/tweepy) でスクリーンネームとパスワードで認証するためのライブラリです。

スクリーンネーム (ex: `@elonmusk`) とパスワードを指定して認証し、取得した Cookie などの認証情報で Twitter API v1.1 にアクセスできます。  
毎回ログインしていては面倒 & 不審なアクセス扱いされそうなので、Cookie をファイルなどに保存し、次回以降はその Cookie を使ってログインする機能もあります。

Tweepy を利用しているソースコードのうち、認証部分 (`tweepy.auth.OAuth1UserHandler`) を `tweepy_authlib.CookieSessionUserHandler` に置き換えるだけで、かんたんに Cookie ベースの認証に変更できます！  
認証部分以外は OAuth API のときの実装がそのまま使えるので、ソースコードの変更も最小限に抑えられます。

認証フローは、ブラウザ上で動作する Web 版公式クライアントの API アクセス動作や HTTP リクエストヘッダーを、可能な限りシミュレートしています。  
ブラウザから抽出した Web 版公式クライアントのログイン済み Cookie を使うことでも認証が可能です。

> [!WARNING]
> **このライブラリは2段階認証 (MFA) や、不審なログインと判定された際の確認コードの入力には対応していません。**  
> 技術的には実装できますが、確認コードの送受信周りの API インターフェイスをどう設計するかが面倒で…。  
> 2段階認証に対応したクライアント実装として、他に [twikit](https://github.com/d60/twikit/blob/main/twikit/client/client.py) や [TweeterPy](https://github.com/iSarabjitDhiman/TweeterPy/blob/master/tweeterpy/login.py) があります (いずれもコード入力で `input()` を使用しており CLI 端末前提となる) 。

> [!NOTE]  
> OAuth API と公式クライアント用の内部 API がほぼ共通だった v1.1 とは異なり、v2 では OAuth API と公式クライアント用の内部 API (GraphQL API) が大きく異なります。  
> そのため、`CookieSessionUserHandler` は Twitter API v2 には対応していません。  

> [!NOTE]  
> ブラウザから Cookie を抽出する場合、(不審なアクセス扱いされないために) できればすべての Cookie を抽出することが望ましいですが、実装上は Cookie 内の `auth_token` と `ct0` の2つの値だけあれば認証できます。  
> なお、ブラウザから取得した Cookie は事前に `requests.cookies.RequestsCookieJar` に変換してください。

> [!WARNING]  
> このライブラリは、非公式かつ内部的な API をリバースエンジニアリングし、ブラウザとほぼ同じように API アクセスを行うことで、本来 Web 版公式クライアントでしか利用できない Cookie 認証での Twitter API v1.1 へのアクセスを可能にしています。  
> 可能な限りブラウザの挙動を模倣することでできるだけ Twitter 側に怪しまれないような実装を行っていますが、非公式な方法ゆえ、**このライブラリを利用して Twitter API にアクセスすると、最悪アカウント凍結やシャドウバンなどの制限が適用される可能性もあります。**  
> また、**Twitter API の仕様変更により、このライブラリが突然動作しなくなることも考えられます。**  
> このライブラリを利用して API アクセスを行うことによって生じたいかなる損害についても、著者は一切の責任を負いません。利用にあたっては十分ご注意ください。

> [!WARNING]  
> **スクリーンネームとパスワードを指定して認証する際は、できるだけログイン実績のある IP アドレスでの実行をおすすめします。**  
> このライブラリでの認証は、Web 版公式クライアントのログインと同じように行われるため、ログイン実績のない IP アドレスから認証すると、不審なログインとして扱われてしまう可能性があります。  
> また、実行毎に毎回認証を行うと、不審なログインとして扱われてしまう可能性が高くなります。  
> **初回の認証以降では、以前認証した際に保存した Cookie を使って認証することを強く推奨します。**

## Installation

```console
pip install tweepy-authlib
```

## Usage

### With JSON

[example_json.py](example_json.py)

```python
import json
import os
from pathlib import Path
from pprint import pprint

import dotenv
import tweepy
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
    with open('cookie.json') as f:
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
    ## スクリーンネームとパスワードを指定する場合は初期化時に認証のための API リクエストが多数行われるため、完了まで数秒かかる
    try:
        auth_handler = CookieSessionUserHandler(screen_name=screen_name, password=password)
    except tweepy.HTTPException as ex:
        # パスワードが間違っているなどの理由で認証に失敗した場合
        if len(ex.api_codes) > 0 and len(ex.api_messages) > 0:
            error_message = f'Code: {ex.api_codes[0]}, Message: {ex.api_messages[0]}'
        else:
            error_message = 'Unknown Error'
        raise Exception(f'Failed to authenticate with password ({error_message})')
    except tweepy.TweepyException as ex:
        # 認証フローの途中で予期せぬエラーが発生し、ログインに失敗した
        error_message = f'Message: {ex}'
        raise Exception(f'Unexpected error occurred while authenticate with password ({error_message})')

    # 現在のログインセッションの Cookie を取得
    cookies_dict = auth_handler.get_cookies_as_dict()

    # Cookie を JSON ファイルに保存
    with open('cookie.json', 'w') as f:
        json.dump(cookies_dict, f, ensure_ascii=False, indent=4)

# Tweepy で Twitter API v1.1 にアクセス
api = tweepy.API(auth_handler)

print('=' * terminal_size)
print('Logged in user:')
print('-' * terminal_size)
user = api.verify_credentials()
assert user.screen_name == os.environ['TWITTER_SCREEN_NAME']
pprint(user._json)
print('=' * terminal_size)

print('Followers (3 users):')
print('-' * terminal_size)
followers = user.followers(count=3)
for follower in followers:
    pprint(follower._json)
    print('-' * terminal_size)
print('=' * terminal_size)

print('Home timeline (3 tweets):')
print('-' * terminal_size)
home_timeline = api.home_timeline(count=3)
for status in home_timeline:
    pprint(status._json)
    print('-' * terminal_size)
print('=' * terminal_size)

tweet_id = home_timeline[0].id
print('Like tweet:')
print('-' * terminal_size)
pprint(api.create_favorite(tweet_id)._json)
print('=' * terminal_size)

print('Unlike tweet:')
print('-' * terminal_size)
pprint(api.destroy_favorite(tweet_id)._json)
print('=' * terminal_size)

# 継続してログインしない場合は明示的にログアウト
## 単に Cookie を消去するだけだと Twitter にセッションが残り続けてしまう
## ログアウト後は、取得した Cookie は再利用できなくなる
# auth_handler.logout()
# os.unlink('cookie.json')
```

### With Pickle

[example_pickle.py](example_pickle.py)

```python
import os
import pickle
from pathlib import Path
from pprint import pprint

import dotenv
import tweepy
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
if Path('cookie.pickle').exists():
    # 保存した Cookie を読み込む
    with open('cookie.pickle', 'rb') as f:
        cookies = pickle.load(f)

    # 読み込んだ RequestCookieJar オブジェクトを CookieSessionUserHandler に渡す
    auth_handler = CookieSessionUserHandler(cookies=cookies)

# スクリーンネームとパスワードを指定して認証
else:
    # スクリーンネームとパスワードを渡す
    ## スクリーンネームとパスワードを指定する場合は初期化時に認証のための API リクエストが多数行われるため、完了まで数秒かかる
    try:
        auth_handler = CookieSessionUserHandler(screen_name=screen_name, password=password)
    except tweepy.HTTPException as ex:
        # パスワードが間違っているなどの理由で認証に失敗した場合
        if len(ex.api_codes) > 0 and len(ex.api_messages) > 0:
            error_message = f'Code: {ex.api_codes[0]}, Message: {ex.api_messages[0]}'
        else:
            error_message = 'Unknown Error'
        raise Exception(f'Failed to authenticate with password ({error_message})')
    except tweepy.TweepyException as ex:
        # 認証フローの途中で予期せぬエラーが発生し、ログインに失敗した
        error_message = f'Message: {ex}'
        raise Exception(f'Unexpected error occurred while authenticate with password ({error_message})')

    # 現在のログインセッションの Cookie を取得
    cookies = auth_handler.get_cookies()

    # Cookie を pickle 化して保存
    with open('cookie.pickle', 'wb') as f:
        pickle.dump(cookies, f)

# Tweepy で Twitter API v1.1 にアクセス
api = tweepy.API(auth_handler)

print('=' * terminal_size)
print('Logged in user:')
print('-' * terminal_size)
user = api.verify_credentials()
assert user.screen_name == os.environ['TWITTER_SCREEN_NAME']
pprint(user._json)
print('=' * terminal_size)

print('Followers (3 users):')
print('-' * terminal_size)
followers = user.followers(count=3)
for follower in followers:
    pprint(follower._json)
    print('-' * terminal_size)
print('=' * terminal_size)

print('Home timeline (3 tweets):')
print('-' * terminal_size)
home_timeline = api.home_timeline(count=3)
for status in home_timeline:
    pprint(status._json)
    print('-' * terminal_size)
print('=' * terminal_size)

tweet_id = home_timeline[0].id
print('Like tweet:')
print('-' * terminal_size)
pprint(api.create_favorite(tweet_id)._json)
print('=' * terminal_size)

print('Unlike tweet:')
print('-' * terminal_size)
pprint(api.destroy_favorite(tweet_id)._json)
print('=' * terminal_size)

# 継続してログインしない場合は明示的にログアウト
## 単に Cookie を消去するだけだと Twitter にセッションが残り続けてしまう
## ログアウト後は、取得した Cookie は再利用できなくなる
# auth_handler.logout()
# os.unlink('cookie.pickle')
```

## License

[MIT License](License.txt)
