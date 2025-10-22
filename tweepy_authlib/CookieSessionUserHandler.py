import binascii
import copy
import json
import random
import re
import secrets
import time
from io import BytesIO
from typing import Any, Optional, TypeVar, Union, cast
from urllib.parse import urlparse

import js2py_
import requests
import tweepy
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from js2py_.base import JsObjectWrapper
from requests.auth import AuthBase
from requests.cookies import RequestsCookieJar
from requests.models import PreparedRequest
from x_client_transaction.transaction import ClientTransaction
from x_client_transaction.utils import get_ondemand_file_url

from tweepy_authlib.__about__ import __version__
from tweepy_authlib.XPFFHeaderGenerator import XPFFHeaderGenerator


Self = TypeVar('Self', bound='CookieSessionUserHandler')


class CookieSessionUserHandler(AuthBase):
    """
    Twitter Web App の内部 API を使い、Cookie ログインで Twitter API を利用するための認証ハンドラー

    認証フローは2025年10月現在の Twitter Web App (Chrome Desktop) の挙動に極力合わせたもの
    requests.auth.AuthBase を継承しているので、tweepy.API の auth パラメーターに渡すことができる

    ref: https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/twitter.py
    ref: https://github.com/fa0311/TwitterFrontendFlow/blob/master/TwitterFrontendFlow/TwitterFrontendFlow.py
    ref: https://github.com/d60/twikit
    ref: https://github.com/iSarabjitDhiman/TweeterPy
    ref: https://github.com/iSarabjitDhiman/XClientTransaction
    """

    # User-Agent と Sec-CH-UA を Chrome 141 に偽装
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
    SEC_CH_UA = '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"'

    # Twitter Web App (GraphQL API) の Bearer トークン
    TWITTER_WEB_APP_BEARER_TOKEN = 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'

    # 旧 TweetDeck (Twitter API v1.1) の Bearer トークン
    TWEETDECK_BEARER_TOKEN = 'Bearer AAAAAAAAAAAAAAAAAAAAAFQODgEAAAAAVHTp76lzh3rFzcHbmHVvQxYYpTw%3DckAlMINMjmCwxUcaXbAN4XqJVdgMJaHqNOFgPMK0zN1qLqLQCF'

    def __init__(
        self,
        cookies: Optional[RequestsCookieJar] = None,
        screen_name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        """
        CookieSessionUserHandler を初期化する
        cookies と screen_name, password のどちらかを指定する必要がある

        Args:
            cookies (Optional[RequestsCookieJar], optional): リクエスト時に利用する Cookie. Defaults to None.
            screen_name (Optional[str], optional): Twitter のスクリーンネーム (@は含まない). Defaults to None.
            password (Optional[str], optional): Twitter のパスワード. Defaults to None.

        Raises:
            ValueError: Cookie が指定されていないのに、スクリーンネームまたはパスワードが (もしくはどちらも) 指定されていない
            ValueError: スクリーンネームが空文字列
            ValueError: パスワードが空文字列
            tweepy.BadRequest: スクリーンネームまたはパスワードが間違っている
            tweepy.HTTPException: サーバーエラーなどの問題でログインに失敗した
            tweepy.TweepyException: 認証フローの途中でエラーが発生し、ログインに失敗した
        """

        self.screen_name = screen_name
        self.password = password

        # Cookie が指定されていないのに、スクリーンネームまたはパスワードが (もしくはどちらも) 指定されていない
        if cookies is None and (self.screen_name is None or self.password is None):
            raise ValueError('Either cookie or screen_name and password must be specified.')

        # スクリーンネームが空文字列
        if self.screen_name == '':
            raise ValueError('screen_name must not be empty string.')

        # パスワードが空文字列
        if self.password == '':
            raise ValueError('password must not be empty string.')

        # HTML 取得時の HTTP リクエストヘッダー
        self._HTML_HEADERS = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'ja',
            'sec-ch-ua': self.SEC_CH_UA,
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': self.USER_AGENT,
        }

        # JavaScript 取得時の HTTP リクエストヘッダー
        self._JS_HEADERS = self._HTML_HEADERS.copy()
        self._JS_HEADERS['accept'] = '*/*'
        self._JS_HEADERS['referer'] = 'https://x.com/'
        self._JS_HEADERS['sec-fetch-dest'] = 'script'
        self._JS_HEADERS['sec-fetch-mode'] = 'no-cors'
        self._JS_HEADERS['sec-fetch-site'] = 'cross-site'
        del self._JS_HEADERS['sec-fetch-user']

        # 認証フロー API アクセス時の HTTP リクエストヘッダー
        self._AUTH_FLOW_API_HEADERS = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'ja',
            # 本来は Twitter Web App の Bearer トークンを使うべきだが、旧 TweetDeck 用の Bearer トークンを使うと
            # なぜか castle_token 必須化後も Bot 判定されずに突破できるっぽいので、当面これを使う
            'authorization': self.TWEETDECK_BEARER_TOKEN,
            'content-type': 'application/json',
            'origin': 'https://x.com',
            'referer': 'https://x.com/',
            'sec-ch-ua': self.SEC_CH_UA,
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': self.USER_AGENT,
            'x-csrf-token': '',  # ここは後でセットされる (ヘッダー順序確保のためにここで空文字列を定義している)
            'x-guest-token': '',  # ここは後でセットされる (ヘッダー順序確保のためにここで空文字列を定義している)
            'x-twitter-active-user': 'yes',
            'x-twitter-client-language': 'ja',
        }

        # GraphQL API (Twitter Web App API) アクセス時の HTTP リクエストヘッダー
        self._GRAPHQL_API_HEADERS = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'ja',
            'authorization': self.TWITTER_WEB_APP_BEARER_TOKEN,
            'content-type': 'application/json',
            'origin': 'https://x.com',
            'referer': 'https://x.com/home',
            'sec-ch-ua': self.SEC_CH_UA,
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.USER_AGENT,
            'x-csrf-token': '',  # ここは後でセットされる (ヘッダー順序確保のためにここで空文字列を定義している)
            'x-twitter-active-user': 'yes',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'ja',
        }

        # Cookie ログイン用のセッションを作成
        ## 実際の Twitter API へのリクエストには tweepy.API 側で作成されたセッションが利用される
        ## その際、__call__() で tweepy.API で作成されたセッションのリクエストヘッダーと Cookie を上書きしている
        self._session = curl_requests.Session(
            # Cookie が指定されている場合は、それをセッションにセット (再ログインを省略する)
            cookies=cookies,
            ## リダイレクトを追跡する
            allow_redirects=True,
            ## curl-cffi に実装されている中で一番新しい Chrome バージョンに偽装する
            impersonate='chrome',
            ## 可能な限り Chrome からのリクエストに偽装するため、明示的に HTTP/2 で接続する
            http_version='v2',
        )

        # X-Client-Transaction-ID ヘッダーを生成するために使う XClientTransaction インスタンス
        # 必要になったタイミングで遅延初期化される
        self._client_transaction: Optional[ClientTransaction] = None

        # X-XP-Forwarded-For ヘッダーを生成するために使う XPFFHeaderGenerator インスタンス
        self._xpff_header_generator = XPFFHeaderGenerator(user_agent=self.USER_AGENT)

        # castle_token のキャッシュ管理用変数
        self._castle_token: Optional[str] = None
        self._castle_token_timestamp: Optional[float] = None

        # Cookie が指定されていない場合は、ここでログインを試みる
        if cookies is None:
            self._login()

        # Cookie から auth_token または ct0 が取得できなかった場合
        ## auth_token と ct0 はいずれも認証に最低限必要な Cookie のため、取得できなかった場合は認証に失敗したものとみなす
        if (
            self._session.cookies.get('auth_token', default=None) is None
            or self._session.cookies.get('ct0', default=None) is None
        ):
            raise tweepy.TweepyException('Failed to get auth_token or ct0 from Cookie')

        # Cookie の "gt" 値 (ゲストトークン) を認証フロー API 用ヘッダーにセット
        guest_token = self._session.cookies.get('gt')
        if guest_token:
            self._AUTH_FLOW_API_HEADERS['x-guest-token'] = guest_token

        # Cookie の "ct0" 値 (CSRF トークン) を GraphQL API 用ヘッダーにセット
        csrf_token = self._session.cookies.get('ct0')
        if csrf_token:
            self._AUTH_FLOW_API_HEADERS['x-csrf-token'] = csrf_token
            self._GRAPHQL_API_HEADERS['x-csrf-token'] = csrf_token

        # 従来はセッションのヘッダーを GraphQL API 用のものに差し替えていたが、暗黙的に意図しないヘッダーが送信される可能性があるため、
        # 意図的にこのライブラリから飛ばすリクエストごとに使うヘッダーを明示するような設計に変更した

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        """
        tweepy.API インスタンス内の requests ライブラリからリクエスト開始時に呼び出されるフック

        Args:
            request (PreparedRequest): PreparedRequest オブジェクト

        Returns:
            PreparedRequest: 認証情報を追加した PreparedRequest オブジェクト
        """

        # PreparedRequest が持つ HTTP ヘッダーを GraphQL API 用のものに差し替える
        ## 以前は旧 TweetDeck API 用ヘッダーに差し替えていたが、旧 TweetDeck が完全廃止されたことで
        ## 逆に怪しまれる可能性があるため GraphQL API 用ヘッダーに変更した
        ## cross_origin=True を指定して、x.com から api.x.com にクロスオリジンリクエストを送信した際のヘッダーを模倣する
        ## content-type を上書きしないよう、content-type を控えておいてから差し替える
        content_type = request.headers.get('content-type', None)
        graphql_api_headers = self.get_graphql_api_headers(cross_origin=True)
        request.headers.update(graphql_api_headers)
        if content_type is not None:
            request.headers['content-type'] = content_type  # 元の content-type に戻す

        # 現在のログインセッションの Cookie を取得し、PreparedRequest で送る際の Cookie にセット
        cookies = self.get_cookies()
        request._cookies.update(cookies)  # type: ignore[attr-defined]
        cookie_header = ''
        for key, value in cookies.get_dict().items():
            cookie_header += f'{key}={value}; '
        request.headers['cookie'] = cookie_header.rstrip('; ')

        # API リクエストがまだ *.twitter.com に対して行われている場合は、*.x.com に差し替える
        ## サードパーティー向け API は互換性のため引き続き api.twitter.com でアクセスできるはずだが、
        ## tweepy-authlib でアクセスしている API は内部 API のため、api.twitter.com のままアクセスしていると怪しまれる可能性がある
        assert request.url is not None
        request.url = request.url.replace('twitter.com/', 'x.com/')

        # API にリクエストする際は原則 X-Client-Transaction-ID ヘッダーを付与する
        ## アップロード系 API のみ、この後の処理で X-Client-Transaction-ID ヘッダーを削除した上でリクエストされる
        ## twitter.com を x.com に置換してから実行するのが重要
        assert request.method is not None
        http_method = cast(curl_requests.session.HttpMethod, request.method.upper())
        transaction_id = self._generate_x_client_transaction_id(http_method, request.url)
        request.headers['x-client-transaction-id'] = transaction_id

        # API にリクエストする際は原則 X-XP-Forwarded-For ヘッダーを付与する
        ## アップロード系 API のみ、この後の処理で X-XP-Forwarded-For ヘッダーを削除した上でリクエストされる
        guest_id = cookies.get_dict().get('guest_id', '')  # guest_id はゲストトークンとは異なる
        xpff_header = self._xpff_header_generator.generate(guest_id)
        request.headers['x-xp-forwarded-for'] = xpff_header

        # Twitter API v1.1 の一部 API には旧 TweetDeck 用の Bearer トークンでないとアクセスできないため、
        # 該当の API のみ旧 TweetDeck 用の Bearer トークンに差し替える
        # それ以外の API ではそのまま Twitter Web App の Bearer トークンを使い続けることで、不審判定される可能性を下げる
        ## OldTweetDeck の interception.js に記載の API のうち、明示的に PUBLIC_TOKENS[1] が設定されている API が対象
        ## ref: https://github.com/dimdenGD/OldTweetDeck/blob/main/src/interception.js
        TWEETDECK_BEARER_TOKEN_REQUIRED_APIS = [
            '/1.1/statuses/home_timeline.json',
            '/1.1/activity/about_me.json',
            '/1.1/statuses/mentions_timeline.json',
            '/1.1/favorites/',
            '/1.1/collections/',
            '/1.1/users/show.json',
            '/1.1/account/verify_credentials.json',
            '/1.1/translations/show.json',
        ]
        if any(api_url in request.url for api_url in TWEETDECK_BEARER_TOKEN_REQUIRED_APIS):
            request.headers['authorization'] = self.TWEETDECK_BEARER_TOKEN

        # upload.x.com (upload.twitter.com) 以下の API のみ、Twitter Web App の挙動に合わせいくつかのヘッダーを追加削除する
        if 'upload.x.com' in request.url or 'upload.twitter.com' in request.url:
            # x.com から見て upload.x.com の API リクエストはクロスオリジンになるため、必ず origin と referer を追加する
            request.headers['origin'] = 'https://x.com'
            request.headers['referer'] = 'https://x.com/'
            # 以下のヘッダーは upload.x.com への API リクエストではなぜか付与されていないため削除する
            request.headers.pop('x-client-transaction-id', None)
            request.headers.pop('x-twitter-active-user', None)
            request.headers.pop('x-twitter-client-language', None)
            request.headers.pop('x-xp-forwarded-for', None)

        # API からレスポンスが返ってきた際に自動で CSRF トークンを更新する
        ## やらなくても大丈夫かもしれないけど、念のため
        request.hooks['response'].append(self._on_response_received)

        # HTTP ヘッダーと Cookie を追加した PreparedRequest オブジェクトを返す
        return request

    def apply_auth(self: Self) -> Self:
        """
        tweepy.API の初期化時に認証ハンドラーを適用するためのメソッド
        自身のインスタンスを認証ハンドラーとして返す

        Args:
            self (Self): 自身のインスタンス

        Returns:
            Self: 自身のインスタンス
        """

        return self

    def get_cookies(self) -> RequestsCookieJar:
        """
        現在のログインセッションの Cookie を取得する
        返される RequestsCookieJar を pickle などで保存しておくことで、再ログインせずにセッションを継続できる

        Returns:
            RequestsCookieJar: Cookie
        """

        # curl_cffi.requests.Session.cookies.jar が持つ CookieJar を RequestsCookieJar に変換
        jar = RequestsCookieJar()
        for cookie in self._session.cookies.jar:
            jar.set_cookie(copy.copy(cookie))
        return jar

    def get_cookies_as_dict(self) -> dict[str, str]:
        """
        現在のログインセッションの Cookie を dict として取得する
        返される dict を JSON などで保存しておくことで、再ログインせずにセッションを継続できる

        Returns:
            dict[str, str]: Cookie
        """

        return self._session.cookies.get_dict()

    def get_html_headers(self) -> dict[str, str]:
        """
        Twitter Web App の HTML アクセス用の HTTP リクエストヘッダーを取得する
        Cookie やトークン類の取得のために HTML ページに HTTP リクエストを送る際の利用を想定している

        Returns:
            dict[str, str]: HTML アクセス用の HTTP リクエストヘッダー
        """

        return self._HTML_HEADERS.copy()

    def get_js_headers(self, cross_origin: bool = False) -> dict[str, str]:
        """
        Twitter Web App の JavaScript アクセス用の HTTP リクエストヘッダーを取得する
        Challenge 用コードの取得のために JavaScript ファイルに HTTP リクエストを送る際の利用を想定している
        cross_origin=True を指定すると、例えば https://abs.twimg.com/ 以下にある JavaScript ファイルを取得する際のヘッダーを取得できる

        Args:
            cross_origin (bool, optional): x.com 以外のオリジンに送信する HTTP リクエストヘッダーかどうか. Defaults to False.

        Returns:
            dict[str, str]: JavaScript アクセス用の HTTP リクエストヘッダー
        """

        headers = self._JS_HEADERS.copy()
        if cross_origin is True:
            headers['sec-fetch-mode'] = 'cors'
        return headers

    def get_graphql_api_headers(self, cross_origin: bool = True) -> dict[str, str]:
        """
        GraphQL API (Twitter Web App API) アクセス用の HTTP リクエストヘッダーを取得する
        このリクエストヘッダーを使い独自に API リクエストを行う際は、
        必ず x-csrf-token ヘッダーの値を常に Cookie 内の "ct0" と一致させるように実装しなければならない
        cross_origin=False を指定すると、origin, referer ヘッダーを付与しない

        Args:
            cross_origin (bool, optional): 返すヘッダーを x.com 以外のオリジンに送信するかどうか. Defaults to True.

        Returns:
            dict[str, str]: GraphQL API (Twitter Web App API) アクセス用の HTTP リクエストヘッダー
        """

        headers = self._GRAPHQL_API_HEADERS.copy()
        if cross_origin is False:
            headers.pop('origin', None)
            headers.pop('referer', None)
        return headers

    def logout(self) -> None:
        """
        ログアウト処理を行い、Twitter からセッションを切断する
        単に Cookie を削除するだけだと Twitter にセッションが残り続けてしまうため、今後ログインしない場合は明示的にこのメソッドを呼び出すこと
        このメソッドを呼び出した後は、取得した Cookie では再認証できなくなる

        Raises:
            tweepy.HTTPException: サーバーエラーなどの問題でログアウトに失敗した
            tweepy.TweepyException: ログアウト処理中にエラーが発生した
        """

        # ログアウト API 専用ヘッダー
        ## self._graphql_api_headers と基本共通で、content-type だけ application/x-www-form-urlencoded に変更
        logout_headers = self._GRAPHQL_API_HEADERS.copy()
        logout_headers['content-type'] = 'application/x-www-form-urlencoded'

        # ログアウト API にログアウトすることを伝える
        ## この API を実行すると、サーバー側でセッションが切断され、今まで持っていたほとんどの Cookie が消去される
        logout_api_response = self._session_request(
            method='POST',
            url='https://api.x.com/1.1/account/logout.json',
            headers=logout_headers,
            data={
                'redirectAfterLogout': 'https://x.com/account/switch',
            },
        )
        if logout_api_response.status_code != 200:
            raise self._get_tweepy_exception(logout_api_response)

        # 基本固定値のようなので不要だが、念のためステータスチェック
        try:
            status = logout_api_response.json()['status']
        except Exception:
            raise tweepy.TweepyException('Failed to logout (failed to parse response)')
        if status != 'ok':
            raise tweepy.TweepyException(f'Failed to logout (status: {status})')

    def _session_request(
        self,
        method: curl_requests.session.HttpMethod,
        url: str,
        headers: dict[str, Any],
        data: Optional[Union[dict[str, str], list[tuple[Any, ...]], str, BytesIO, bytes]] = None,
        json: Optional[Union[dict[str, Any], list[Any]]] = None,
        add_transaction_id: Optional[bool] = None,
    ) -> curl_requests.Response:
        """
        curl-cffi セッションでリクエストを送り、API からレスポンスが返ってきた際に自動で CSRF トークンを更新する
        認証に成功したタイミングで、Cookie の "ct0" 値 (CSRF トークン) がクライアント側で生成したものから、サーバー側で生成したものに更新される

        Args:
            method (curl_requests.session.HttpMethod): リクエストメソッド
            url (str): リクエスト URL
            headers (dict[str, str]): リクエストヘッダー。誤ったリクエストヘッダーで送信されるのを防ぐために毎回明示的に設定が必要。
            data (Optional[Union[dict[str, str], list[tuple[Any, ...]], str, BytesIO, bytes]], optional): リクエストボディ. Defaults to None.
            json (Optional[Union[dict[str, Any], list[Any]]], optional): JSON ボディ. Defaults to None.
            add_transaction_id (Optional[bool], optional): X-Client-Transaction-ID を付与するかどうか. Defaults to None.

        Returns:
            curl_requests.Response: レスポンス
        """

        # 明示指定がない場合、URL から X-Client-Transaction-ID を付与するか判定
        if add_transaction_id is None:
            add_transaction_id = True
            # https://api.x.com または https://x.com/i/api/ 以下「以外」の URL にはヘッダーを付与しない
            # HTML や JavaScript リソースの取得時には X-Client-Transaction-ID の付与は不要
            if not url.startswith('https://api.x.com/') and not url.startswith('https://x.com/i/api/'):
                add_transaction_id = False

        # API リクエストに対応する X-Client-Transaction-ID の付与が有効なとき、
        # メソッドと API パスから X-Client-Transaction-ID を生成
        if add_transaction_id is True:
            transaction_id = self._generate_x_client_transaction_id(method, url)
            # 生成した X-Client-Transaction-ID ヘッダーを追加
            headers['x-client-transaction-id'] = transaction_id

        # API リクエストに対応する X-Client-Transaction-ID ヘッダーの付与が有効なとき、
        # ゲストトークンから X-XP-Forwarded-For ヘッダーを生成
        ## X-Client-Transaction-ID を付与する場合は X-XP-Forwarded-For ヘッダーも付与するべき
        if add_transaction_id is True:
            guest_id = self.get_cookies_as_dict().get('guest_id', '')  # guest_id はゲストトークンとは異なる
            xpff_header = self._xpff_header_generator.generate(guest_id)
            headers['x-xp-forwarded-for'] = xpff_header

        # リクエストを実行し、レスポンスをコールバックに渡す
        response = self._session.request(
            method,
            url,
            headers=headers,
            data=data,
            json=json,
        )
        self._on_response_received(response)

        return response

    def _generate_x_client_transaction_id(
        self,
        method: curl_requests.session.HttpMethod,
        url: str,
    ) -> str:
        """
        XClientTransaction ライブラリを使い X-Client-Transaction-ID を生成する

        Args:
            method (curl_requests.session.HttpMethod): リクエストメソッド
            url (str): リクエスト URL

        Returns:
            str: 生成された X-Client-Transaction-ID
        """

        # XClientTransaction インスタンスが未初期化の場合は初期化する
        if self._client_transaction is None:
            self._initialize_client_transaction()
            assert self._client_transaction is not None, 'Failed to initialize XClientTransaction'

        # メソッドと API パス (クエリは含めない) を指定して X-Client-Transaction-ID を生成
        # 例: method="POST", path="/i/api/graphql/1VOOyvKkiI3FMmkeDNxM9A/UserByScreenName"
        # ref: https://github.com/iSarabjitDhiman/XClientTransaction#generate-x-client-transaction-i-tid
        return self._client_transaction.generate_transaction_id(method, urlparse(url).path)

    def _initialize_client_transaction(self) -> None:
        """
        XClientTransaction インスタンスを遅延初期化する

        Raises:
            tweepy.TweepyException: 必要な JavaScript リソースが取得できなかった
        """

        # すでに XClientTransaction インスタンスが初期化されている場合は何もしない
        if self._client_transaction is not None:
            return

        # 一度 https://x.com/home にアクセスする
        ## 未ログイン時は、ゲストトークンの Cookie (Cookie 内の "gt" 値) をセットさせる
        ## 取得した HTML は X-Client-Transaction-ID 生成に必要な ondemand.js スクリプトの取得にも活用する
        home_page_response = self._session_request(
            method='GET',
            url='https://x.com/home',
            headers=self._HTML_HEADERS,  # HTML 取得用ヘッダーを使う
            add_transaction_id=False,  # HTML リソースの取得なので付与不要
        )
        if home_page_response.status_code != 200:
            raise self._get_tweepy_exception(home_page_response)

        # X-Client-Transaction-ID 生成に必要な ondemand.js スクリプトを取得
        home_page_response_soup = BeautifulSoup(home_page_response.text, 'html.parser')
        ondemand_js_url = get_ondemand_file_url(home_page_response_soup)
        if ondemand_js_url is None:
            raise tweepy.TweepyException('Failed to locate ondemand script for X-Client-Transaction-ID')
        ondemand_js_response = self._session_request(
            method='GET',
            url=ondemand_js_url,
            headers=self._JS_HEADERS,  # JavaScript 取得用ヘッダーを使う
            add_transaction_id=False,  # JavaScript リソースの取得なので付与不要
        )
        if ondemand_js_response.status_code != 200:
            raise self._get_tweepy_exception(ondemand_js_response)

        # XClientTransaction インスタンスを初期化
        ondemand_js_response_soup = BeautifulSoup(ondemand_js_response.text, 'html.parser')
        self._client_transaction = ClientTransaction(home_page_response_soup, ondemand_js_response_soup)

    def _on_response_received(
        self, response: Union[curl_requests.Response, requests.Response], *args: Any, **kwargs: Any
    ) -> None:
        """
        レスポンスが返ってきた際に、自動的にリクエストヘッダーや Cookie に設定されている CSRF トークンを更新するためのコールバック

        Args:
            response (requests.Response): レスポンス
        """

        csrf_token = response.cookies.get('ct0')
        if csrf_token:
            # 現在セッションに保持されている CSRF トークンと一致しない場合、新しい CSRF トークンでセッションを更新
            if self._session.cookies.get('ct0') != csrf_token:
                self._session.cookies.set('ct0', csrf_token, domain='.x.com')
            # 認証フロー API 用ヘッダーと GraphQL API 用ヘッダーに新しい CSRF トークンをセット
            self._AUTH_FLOW_API_HEADERS['x-csrf-token'] = csrf_token
            self._GRAPHQL_API_HEADERS['x-csrf-token'] = csrf_token

    def _get_tweepy_exception(self, response: curl_requests.Response) -> tweepy.TweepyException:
        """
        TweepyException を継承した、ステータスコードと一致する例外クラスを取得する

        Args:
            status_code (int): ステータスコード

        Returns:
            tweepy.TweepyException: 例外
        """

        if response.status_code == 400:
            return tweepy.BadRequest(response)
        elif response.status_code == 401:
            return tweepy.Unauthorized(response)
        elif response.status_code == 403:
            return tweepy.Forbidden(response)
        elif response.status_code == 404:
            return tweepy.NotFound(response)
        elif response.status_code == 429:
            return tweepy.TooManyRequests(response)
        elif 500 <= response.status_code <= 599:
            return tweepy.TwitterServerError(response)
        else:
            return tweepy.TweepyException(response)

    def generate_castle_token(self, cuid: str) -> str:
        """
        castle_token 生成用 API から認証用 API の突破に必要な castle_token を生成し、60 秒間キャッシュする
        castle_token の castle とは https://castle.io/ が提供する Bot 対策ソリューションらしい
        ref: https://github.com/d60/twikit/pull/393
        ref: https://github.com/heysurfer/twikit/blob/main/twikit/castle_token/castle_token.py

        Args:
            cuid (str): 生成に利用する cuid

        Returns:
            str: 生成された castle_token
        """

        # キャッシュが有効な場合は、キャッシュされた castle_token を返す
        # キャッシュの有効期間は60秒
        if self._castle_token is not None and self._castle_token_timestamp is not None:
            is_token_fresh = (time.time() - self._castle_token_timestamp) < 60.0
            if is_token_fresh is True:
                return self._castle_token

        # 有志が公開している castle_token 生成用外部 API にリクエストを送り、新しい castle_token を取得する
        # レート制限があるらしく、制限を解除して欲しければ有料 API キーを買えということらしいが、そこまで使う人はまずいないはず
        # ref: https://github.com/d60/twikit/pull/393
        castle_response = curl_requests.post(
            url='https://castle.botwitter.com/generate-token',
            headers={
                'accept': '*/*',
                'accept-encoding': 'gzip, deflate, br, zstd',
                'accept-language': 'ja',
                'content-type': 'application/json',
                # これは有志が公開してくれている API なので、tweepy-authlib から利用していることを明示的に伝える
                'user-agent': f'Mozilla/5.0 tweepy-authlib/{__version__}',
            },
            json={
                'userAgent': self.USER_AGENT,
                'cuid': cuid,
            },
        )
        if castle_response.status_code != 200:
            raise tweepy.TweepyException('Failed to generate castle_token')
        try:
            response_data = castle_response.json()
        except Exception:
            raise tweepy.TweepyException('Failed to decode castle_token response')

        # レスポンスから castle_token を取得してキャッシュする
        castle_token = response_data.get('token')
        if castle_token is None or castle_token == '':
            raise tweepy.TweepyException('castle_token not found in response')
        self._castle_token = castle_token
        self._castle_token_timestamp = time.time()

        return castle_token

    def _generate_csrf_token(self, size: int = 16) -> str:
        """
        Twitter の CSRF トークン (Cookie 内の "ct0" 値) を生成する

        Args:
            size (int, optional): トークンサイズ. Defaults to 16.

        Returns:
            str: 生成されたトークン
        """

        data = random.getrandbits(size * 8).to_bytes(size, 'big')
        return binascii.hexlify(data).decode()

    def _get_guest_token(self) -> str:
        """
        ゲストトークン (Cookie 内の "gt" 値) を取得する
        通常はこのメソッドを呼び出す必要はなく、_initialize_client_transaction() で初期化することで副次的にセットされるはず

        Returns:
            str: 取得されたトークン
        """

        # HTTP ヘッダーは基本的に認証用セッションの物を使うが、CSRF トークンとゲストトークンは不要なため削除
        guest_activate_headers = self._AUTH_FLOW_API_HEADERS.copy()
        guest_activate_headers.pop('x-csrf-token')
        guest_activate_headers.pop('x-guest-token')

        # API からゲストトークンを取得する
        # ref: https://github.com/fa0311/TwitterFrontendFlow/blob/master/TwitterFrontendFlow/TwitterFrontendFlow.py#L26-L36
        guest_token_response = self._session_request(
            method='POST',
            url='https://api.x.com/1.1/guest/activate.json',
            headers=guest_activate_headers,
        )
        if guest_token_response.status_code != 200:
            raise self._get_tweepy_exception(guest_token_response)
        try:
            guest_token = guest_token_response.json()['guest_token']
        except Exception:
            raise tweepy.TweepyException('Failed to get guest token')

        return guest_token

    def _get_ui_metrics(self, js_inst: str) -> dict[str, Any]:
        """
        https://x.com/i/js_inst?c_name=ui_metrics から出力される難読化された JavaScript から ui_metrics を取得する
        ref: https://github.com/hfthair/TweetScraper/blob/master/TweetScraper/spiders/following.py#L50-L94

        Args:
            js_inst (str): 難読化された JavaScript

        Returns:
            dict[str, Any]: 取得された ui_metrics
        """

        # 難読化された JavaScript の中から ui_metrics を取得する関数を抽出
        js_inst_function = js_inst.split('\n')[2]
        js_inst_function_name = (
            re.search(re.compile(r'function [a-zA-Z]+'), js_inst_function).group().replace('function ', '')  # type: ignore
        )

        # 難読化された JavaScript を実行するために簡易的に DOM API をモックする
        ## とりあえず最低限必要そうなものだけ
        js_dom_mock = """
            var _element = {
                appendChild: function(x) {
                    // do nothing
                },
                removeChild: function(x) {
                    // do nothing
                },
                setAttribute: function(x, y) {
                    // do nothing
                },
                innerText: '',
                innerHTML: '',
                outerHTML: '',
                tagName: '',
                textContent: '',
            }
            _element['children'] = [_element];
            _element['firstElementChild'] = _element;
            _element['lastElementChild'] = _element;
            _element['nextSibling'] = _element;
            _element['nextElementSibling'] = _element;
            _element['parentNode'] = _element;
            _element['previousSibling'] = _element;
            _element['previousElementSibling'] = _element;
            document = {
                createElement: function(x) {
                    return _element;
                },
                getElementById: function(x) {
                    return _element;
                },
                getElementsByClassName: function(x) {
                    return [_element];
                },
                getElementsByName: function(x) {
                    return [_element];
                },
                getElementsByTagName: function(x) {
                    return [_element];
                },
                getElementsByTagNameNS: function(x, y) {
                    return [_element];
                },
                querySelector: function(x) {
                    return _element;
                },
                querySelectorAll: function(x) {
                    return [_element];
                },
            }
            """

        # 難読化された JavaScript を実行
        js_context = js2py_.EvalJs()
        js_context.execute(js_dom_mock)
        js_context.execute(js_inst_function)
        js_context.execute(f'var ui_metrics = {js_inst_function_name}()')

        # ui_metrics を取得
        ui_metrics = cast(JsObjectWrapper, js_context.ui_metrics)
        return cast(dict[str, Any], ui_metrics.to_dict())

    def _login(self) -> None:
        """
        スクリーンネームとパスワードを使って認証し、ログインする

        Raises:
            tweepy.BadRequest: スクリーンネームまたはパスワードが間違っている
            tweepy.HTTPException: サーバーエラーなどの問題でログインに失敗した
            tweepy.TweepyException: 認証フローの途中でエラーが発生し、ログインに失敗した
        """

        def get_flow_token(response: curl_requests.Response) -> str:
            try:
                data = response.json()
            except Exception:
                pass
            else:
                if response.status_code < 400:
                    return data['flow_token']
            raise self._get_tweepy_exception(response)

        def get_excepted_subtask(response: curl_requests.Response, subtask_id: str) -> dict[str, Any]:
            try:
                data = response.json()
            except Exception:
                pass
            else:
                if response.status_code < 400:
                    for subtask in data['subtasks']:
                        if subtask['subtask_id'] == subtask_id:
                            return subtask
                    raise tweepy.TweepyException(f'{subtask_id} not found in response')
            raise self._get_tweepy_exception(response)

        # Cookie をクリア
        self._session.cookies.clear()

        # このタイミングで明示的に XClientTransaction インスタンスを初期化する
        ## この処理で Twitter Web App の PWA 用 HTML と ondemand.js が取得され、
        ## 副次的にログインに必要なゲストトークン (Cookie 内の "gt" 値) がセッション Cookie にセットされる
        self._initialize_client_transaction()

        # cuid を生成し、"__cuid" としてセッションの Cookie に保存
        ## cuid は32文字の16進数のランダム文字列で、castle_token の生成に必要らしい (おそらく Castle User ID の略？)
        ## この ID と castle_token が対応しているかを Twitter の API サーバーで判定しているっぽい感じ
        ## Twitter Web App は初回ロード時にこの値を生成して Cookie にセットしているっぽいので、それの挙動を模倣する
        cuid = secrets.token_hex(16)
        self._session.cookies.set('__cuid', cuid, domain='.x.com')

        # CSRF トークンを生成し、"ct0" としてセッションの Cookie に保存
        ## 同時に認証フロー API 用の HTTP リクエストヘッダーにもセット ("ct0" と "x-csrf-token" は同じ値になる)
        csrf_token = self._generate_csrf_token()
        self._session.cookies.set('ct0', csrf_token, domain='.x.com')
        self._AUTH_FLOW_API_HEADERS['x-csrf-token'] = csrf_token

        # まだ取得できていない場合のみ、ゲストトークンを取得し、"gt" としてセッションの Cookie に保存
        ## 通常発生しないはずだが、フォールバックとして一応実装してある（いつまで動作するのかは不明）
        if self._session.cookies.get('gt', default=None) is None:
            guest_token = self._get_guest_token()
            self._session.cookies.set('gt', guest_token, domain='.x.com')

        ## ゲストトークンを認証フロー API 用の HTTP リクエストヘッダーにもセット ("gt" と "x-guest-token" は同じ値になる)
        self._AUTH_FLOW_API_HEADERS['x-guest-token'] = cast(str, self._session.cookies.get('gt'))

        # 極力公式の Twitter Web App に偽装するためのダミーリクエスト
        # HTTP ヘッダーは認証フロー用 API ヘッダーを使うが、CSRF トークンのみ不要なため削除
        hashflags_sso_init_headers = self._AUTH_FLOW_API_HEADERS.copy()
        hashflags_sso_init_headers.pop('x-csrf-token')
        self._session_request(
            method='GET',
            url='https://api.x.com/1.1/hashflags.json',
            headers=hashflags_sso_init_headers,
        )
        self._session_request(
            method='POST',
            url='https://api.x.com/1.1/onboarding/sso_init.json',
            headers=hashflags_sso_init_headers,
            json={'provider': 'apple'},
        )

        # https://api.x.com/1.1/onboarding/task.json?task=login に POST して認証フローを開始
        ## 認証フローを開始するには、Cookie に "ct0" と "gt" がセットされている必要がある
        ## 2025年10月時点の Twitter Web App が送信する JSON パラメータを模倣している
        flow_01_response = self._session_request(
            method='POST',
            url='https://api.x.com/1.1/onboarding/task.json?flow_name=login',
            headers=self._AUTH_FLOW_API_HEADERS,  # 認証フロー用 API ヘッダーを使う
            json={
                'input_flow_data': {
                    'flow_context': {
                        'debug_overrides': {},
                        'start_location': {
                            'location': 'splash_screen',
                        },
                    }
                },
                'subtask_versions': {
                    'action_list': 2,
                    'alert_dialog': 1,
                    'app_download_cta': 1,
                    'check_logged_in_account': 1,
                    'choice_selection': 3,
                    'contacts_live_sync_permission_prompt': 0,
                    'cta': 7,
                    'email_verification': 2,
                    'end_flow': 1,
                    'enter_date': 1,
                    'enter_email': 2,
                    'enter_password': 5,
                    'enter_phone': 2,
                    'enter_recaptcha': 1,
                    'enter_text': 5,
                    'enter_username': 2,
                    'generic_urt': 3,
                    'in_app_notification': 1,
                    'interest_picker': 3,
                    'js_instrumentation': 1,
                    'menu_dialog': 1,
                    'notifications_permission_prompt': 2,
                    'open_account': 2,
                    'open_home_timeline': 1,
                    'open_link': 1,
                    'phone_verification': 4,
                    'privacy_options': 1,
                    'security_key': 3,
                    'select_avatar': 4,
                    'select_banner': 2,
                    'settings_list': 7,
                    'show_code': 1,
                    'sign_up': 2,
                    'sign_up_review': 4,
                    'tweet_selection_urt': 1,
                    'update_users': 1,
                    'upload_media': 1,
                    'user_recommendations_list': 4,
                    'user_recommendations_urt': 1,
                    'wait_spinner': 3,
                    'web_modal': 1,
                },
            },
        )
        if flow_01_response.status_code != 200:
            raise self._get_tweepy_exception(flow_01_response)

        # flow_01 のレスポンスから js_inst の URL を取得
        # subtasks の中に LoginJsInstrumentationSubtask が含まれていない場合、例外を送出する
        js_inst_subtask = get_excepted_subtask(flow_01_response, 'LoginJsInstrumentationSubtask')
        js_inst_url = js_inst_subtask['js_instrumentation']['url']

        # js_inst (難読化された JavaScript で、これの実行結果を認証フローに送信する必要がある) を取得
        js_inst_response = self._session_request(
            method='GET',
            url=js_inst_url,
            headers=self._JS_HEADERS,  # JavaScript 取得用ヘッダーを使う
            add_transaction_id=False,  # JavaScript リソースの取得なので付与不要
        )
        if js_inst_response.status_code != 200:
            raise tweepy.TweepyException('Failed to get js_inst')

        # js_inst の JavaScript を実行し、ui_metrics オブジェクトを取得
        ui_metrics = self._get_ui_metrics(js_inst_response.text)

        # 取得した ui_metrics を認証フローに送信
        flow_02_response = self._session_request(
            method='POST',
            url='https://api.x.com/1.1/onboarding/task.json',
            headers=self._AUTH_FLOW_API_HEADERS,  # 認証フロー用 API ヘッダーを使う
            json={
                'flow_token': get_flow_token(flow_01_response),
                'subtask_inputs': [
                    {
                        'subtask_id': 'LoginJsInstrumentationSubtask',
                        'js_instrumentation': {
                            'response': json.dumps(ui_metrics),
                            'link': 'next_link',
                        },
                    },
                ],
            },
        )
        if flow_02_response.status_code != 200:
            raise self._get_tweepy_exception(flow_02_response)

        # subtasks の中に LoginEnterUserIdentifierSSO が含まれていない場合、例外を送出する
        get_excepted_subtask(flow_02_response, 'LoginEnterUserIdentifierSSO')

        # 極力公式の Twitter Web App に偽装するためのダミーリクエスト
        self._session_request(
            method='POST',
            url='https://api.x.com/1.1/onboarding/sso_init.json',
            headers=hashflags_sso_init_headers,
            json={'provider': 'apple'},
        )

        # 怪しまれないように、2秒～4秒の間にランダムな時間待機
        time.sleep(random.uniform(2.0, 4.0))

        # スクリーンネームを認証フローに送信
        flow_03_response = self._session_request(
            method='POST',
            url='https://api.x.com/1.1/onboarding/task.json',
            headers=self._AUTH_FLOW_API_HEADERS,  # 認証フロー用 API ヘッダーを使う
            json={
                'flow_token': get_flow_token(flow_02_response),
                'subtask_inputs': [
                    {
                        'subtask_id': 'LoginEnterUserIdentifierSSO',
                        'settings_list': {
                            'setting_responses': [
                                {
                                    'key': 'user_identifier',
                                    'response_data': {
                                        'text_data': {
                                            'result': self.screen_name,
                                        }
                                    },
                                },
                            ],
                            'link': 'next_link',
                            # castle_token は generate_castle_token() で生成した値を利用する
                            # cuid には事前に Cookie にセットした値を利用する
                            'castle_token': self.generate_castle_token(cuid),
                        },
                    },
                ],
            },
        )
        if flow_03_response.status_code != 200:
            raise self._get_tweepy_exception(flow_03_response)

        # subtasks の中に LoginEnterPassword が含まれていない場合、例外を送出する
        get_excepted_subtask(flow_03_response, 'LoginEnterPassword')

        # 怪しまれないように、2秒～4秒の間にランダムな時間待機
        time.sleep(random.uniform(2.0, 4.0))

        # パスワードを認証フローに送信
        flow_04_response = self._session_request(
            method='POST',
            url='https://api.x.com/1.1/onboarding/task.json',
            headers=self._AUTH_FLOW_API_HEADERS,  # 認証フロー用 API ヘッダーを使う
            json={
                'flow_token': get_flow_token(flow_03_response),
                'subtask_inputs': [
                    {
                        'subtask_id': 'LoginEnterPassword',
                        'enter_password': {
                            'password': self.password,
                            'link': 'next_link',
                        },
                    },
                ],
            },
        )
        if flow_04_response.status_code != 200:
            raise self._get_tweepy_exception(flow_04_response)

        # ログイン失敗
        if flow_04_response.json()['status'] != 'success':
            raise tweepy.TweepyException(f'Failed to login (status: {flow_04_response.json()["status"]})')

        # subtasks の中に SuccessExit が含まれていない場合、例外を送出する
        get_excepted_subtask(flow_04_response, 'SuccessExit')

        # 最後の最後にファイナライズを行う
        ## このリクエストで、Cookie に auth_token がセットされる
        ## このタイミングで Cookie の "ct0" 値 (CSRF トークン) がクライアント側で生成したものから、サーバー側で生成したものに更新される
        flow_05_response = self._session_request(
            method='POST',
            url='https://api.x.com/1.1/onboarding/task.json',
            headers=self._AUTH_FLOW_API_HEADERS,  # 認証フロー用 API ヘッダーを使う
            json={
                'flow_token': get_flow_token(flow_04_response),
                'subtask_inputs': [],
            },
        )
        if flow_05_response.status_code != 200:
            raise self._get_tweepy_exception(flow_05_response)

        # ここまで来たら、ログインに成功しているはず
        ## Cookie にはログインに必要な情報が入っている
        ## 実際に認証に最低限必要な Cookie は "auth_token" と "ct0" のみ (とはいえそれだけだと怪しまれそうなので、それ以外の値も送る)
        ## ref: https://qiita.com/SNQ-2001/items/182b278e1e8aaaa21a13
