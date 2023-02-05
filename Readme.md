
# tweepy-authlib

[![PyPI - Version](https://img.shields.io/pypi/v/tweepy-authlib.svg)](https://pypi.org/project/tweepy-authlib)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/tweepy-authlib.svg)](https://pypi.org/project/tweepy-authlib)

-----

**Table of Contents**

- [tweepy-authlib](#tweepy-authlib)
  - [Description](#description)
  - [Installation](#installation)
  - [Usage](#usage)
  - [License](#license)

## Description

Tweepy で Web 版公式クライアントの内部 API を利用し、スクリーンネームとパスワードを指定した Cookie ベースでの認証を行うためのライブラリです。

スクリーンネーム (ex: @elonmusk) とパスワードを指定して認証し、取得した Cookie などの認証情報で Twitter API v1.1 にアクセスできます。  
毎回ログインしていては面倒 & 不審なアクセス扱いされそうなので、Cookie をファイルなどに保存し、次回以降はその Cookie を使ってログインする機能もあります。

Tweepy を利用しているソースコードのうち、認証部分 (`tweepy.auth.OAuth1UserHandler`) を `tweepy_authlib.CookieSessionUserHandler` に置き換えるだけで、かんたんに Cookie ベースの認証に変更できます！

Twitter API の有料化に伴って通常の OAuth API が利用できなくなった場合も、この `CookieSessionUserHandler` を使えば引き続き Twitter API v1.1 にアクセスできるはず…！  
認証部分以外は OAuth API のときの実装がそのまま使えるので、ソースコードの変更も最小限に抑えられます。

> **Note**  
> OAuth API と公式クライアント用の内部 API がほぼ共通だった v1.1 とは異なり、v2 では OAuth API と公式クライアント用の内部 API が大きく異なります。  
> そのため、`CookieSessionUserHandler` は Twitter API v2 には対応していません。  

認証フローはブラウザ上で動作する Web 版公式クライアントの API アクセス動作を可能な限りエミュレートしています。  
ブラウザから抽出した Web 版公式クライアントのログイン済み Cookie を使うことでも認証が可能です。

> **Note**  
> ブラウザから Cookie を抽出する場合、(不審なアクセス扱いされないために) できればすべての Cookie を抽出することが望ましいですが、実装上は Cookie 内の `auth_token` と `ct0` の2つの値だけあれば認証できます。  
> なお、ブラウザから取得した Cookie は事前に `requests.cookies.RequestsCookieJar` に変換してください。

さらに API アクセス時は TweetDeck の HTTP リクエスト (Twitter API v1.1) をエミュレートしているため、レートリミットなどの制限は TweetDeck と同一です。  

> **Note**  
> `CookieSessionUserHandler` で取得した認証情報を使うと、TweetDeck でしか利用できない search/universal などの内部 API にもアクセスできるようになります。  
> ただし、Tweepy はそうした内部 API をサポートしていないため、アクセスするには独自に `tweepy.API.request()` で HTTP リクエストを送る必要があります。

> **Warning**  
> このライブラリは、非公式かつ内部的な API をリバースエンジニアリングし、ブラウザとほぼ同じように API アクセスを行うことで、本来 Web 版公式クライアントでしか利用できない Cookie 認証での Twitter API v1.1 へのアクセスを可能にしています。  
> 可能な限りブラウザの挙動を模倣することでできるだけ Twitter 側に怪しまれないような実装を行っていますが、**このライブラリを利用して Twitter API にアクセスすると、最悪 Twitter によるアカウントの凍結や API 利用制限などの制限が適用される可能性があります。**  
> また、**Twitter API の仕様変更により、このライブラリが突然動作しなくなることも考えられます。**  
> このライブラリを利用して API アクセスを行うことによって生じたいかなる損害についても、著者は一切の責任を負いません。利用にあたっては十分ご注意ください。

> **Warning**  
> スクリーンネームとパスワードを指定して認証する際は、できるだけログイン実績のある IP アドレスでの実行をおすすめします。  
> このライブラリでの認証は、Web 版公式クライアントのログインと同じように行われるため、ログイン実績のない IP アドレスから認証すると、不審なログインとして扱われてしまう可能性があります。  
> また、実行毎に毎回認証を行うと、不審なログインとして扱われてしまう可能性が高くなります。  
> 初回の認証以外では、以前認証した際に保存した Cookie を使って認証することを強く推奨します。

## Installation

```console
pip install tweepy-authlib
```

## Usage

```python
import pickle
import tweepy
from pathlib import Path
from tweepy_authlib import CookieSessionUserHandler

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
    ## スクリーンネームまたはパスワードが間違っている場合は、tweepy.BadRequest がスローされる
    auth_handler = CookieSessionUserHandler(screen_name='your_screen_name', password='your_password')

    # 現在のログインセッションの Cookie を取得
    cookies = auth_handler.get_cookies()

    # Cookie を pickle 化して保存
    with open('cookie.pickle', 'wb') as f:
        pickle.dump(cookies, f)

# Tweepy で Twitter API v1.1 にアクセス
api = tweepy.API(auth_handler)
print(api.verify_credentials())
print(api.home_timeline())
```

## License

[MIT License](License.txt)
