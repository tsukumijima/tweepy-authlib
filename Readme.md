
# tweepy-authlib

[![PyPI - Version](https://img.shields.io/pypi/v/tweepy-authlib.svg)](https://pypi.org/project/tweepy-authlib)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/tweepy-authlib.svg)](https://pypi.org/project/tweepy-authlib)

> [!WARNING]  
> **旧 TweetDeck の完全廃止にともない、2023/09/14 頃から内部的に残存していた Twitter API v1.1 の段階的なシャットダウンが開始されています。**  
> **2024/04/30 時点では、account/verify_credentials や upload.twitter.com 以下の API を除き大半の Twitter API v1.1 にアクセスできなくなっています。**  
> 現在 tweepy-authlib を使いタイムライン取得 / ツイート検索 / ツイート送信機能などを実装するには、別途 GraphQL API (Twitter Web App の内部 API) クライアントを自作する必要があります。  
> 私が [KonomiTV](https://github.com/tsukumijima/KonomiTV) 向けに開発した GraphQL API クライアントの実装が [こちら](https://github.com/tsukumijima/KonomiTV/blob/master/server/app/utils/TwitterGraphQLAPI.py) ([使用例](https://github.com/tsukumijima/KonomiTV/blob/master/server/app/routers/TwitterRouter.py)) にありますので、実装時の参考にしてください。

> [!IMPORTANT]  
> 2024/04/30 時点では [tweepy-authlib が依存する js2py が Python 3.12 に対応していない](https://github.com/tsukumijima/tweepy-authlib/issues/5) ため、tweepy-authlib は Python 3.12 以降では動作しません。  
> [js2py](https://github.com/PiotrDabkowski/Js2Py) の Python 3.12 対応が完了するまで、Python 3.11 以下での利用をおすすめします。

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

> [!NOTE]  
> OAuth API と公式クライアント用の内部 API がほぼ共通だった v1.1 とは異なり、v2 では OAuth API と公式クライアント用の内部 API が大きく異なります。  
> そのため、`CookieSessionUserHandler` は Twitter API v2 には対応していません。  
> また、今のところ2段階認証にも対応していません (2段階認証に関しては技術的には実装可能だが、確認コードの送信周りの実装が面倒…) 。

認証フローはブラウザ上で動作する Web 版公式クライアントの API アクセス動作や HTTP リクエストヘッダーを可能な限りエミュレートしています。  
ブラウザから抽出した Web 版公式クライアントのログイン済み Cookie を使うことでも認証が可能です。

> [!NOTE]  
> ブラウザから Cookie を抽出する場合、(不審なアクセス扱いされないために) できればすべての Cookie を抽出することが望ましいですが、実装上は Cookie 内の `auth_token` と `ct0` の2つの値だけあれば認証できます。  
> なお、ブラウザから取得した Cookie は事前に `requests.cookies.RequestsCookieJar` に変換してください。

さらに API アクセス時は TweetDeck の HTTP リクエスト (Twitter API v1.1) をエミュレートしているため、レートリミットなどの制限は TweetDeck と同一です。  

> [!NOTE]  
> `CookieSessionUserHandler` で取得した認証情報を使うと、TweetDeck でしか利用できない search/universal などの内部 API にもアクセスできるようになります。  
> ただし、Tweepy はそうした内部 API をサポートしていないため、アクセスするには独自に `tweepy.API.request()` で HTTP リクエストを送る必要があります。

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

```python
import json
import os
import tweepy
from pathlib import Path
from requests.cookies import RequestsCookieJar
from tweepy_authlib import CookieSessionUserHandler

try:
    terminal_size = os.get_terminal_size().columns
except OSError:
    terminal_size = 80

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
    ## スクリーンネームとパスワードを指定する場合は初期化時に認証のための API リクエストが多数行われるため、完了まで数秒かかる
    try:
        auth_handler = CookieSessionUserHandler(screen_name='your_screen_name', password='your_password')
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
    with open('cookie.json', 'w') as f:
        json.dump(cookies.get_dict(), f, ensure_ascii=False, indent=4)

# Tweepy で Twitter API v1.1 にアクセス
api = tweepy.API(auth_handler)
print('-' * terminal_size)
print(api.verify_credentials())
print('-' * terminal_size)

# 継続してログインしない場合は明示的にログアウト
## 単に Cookie を消去するだけだと Twitter にセッションが残り続けてしまう
## ログアウト後は、取得した Cookie では再認証できなくなる
#auth_handler.logout()
#os.unlink('cookie.json')
```

### With Pickle

```python
import os
import pickle
import tweepy
from pathlib import Path
from tweepy_authlib import CookieSessionUserHandler

try:
    terminal_size = os.get_terminal_size().columns
except OSError:
    terminal_size = 80

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
        auth_handler = CookieSessionUserHandler(screen_name='your_screen_name', password='your_password')
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
print('-' * terminal_size)
print(api.verify_credentials())
print('-' * terminal_size)

# 継続してログインしない場合は明示的にログアウト
## 単に Cookie を消去するだけだと Twitter にセッションが残り続けてしまう
## ログアウト後は、取得した Cookie では再認証できなくなる
#auth_handler.logout()
#os.unlink('cookie.pickle')
```

## License

[MIT License](License.txt)
