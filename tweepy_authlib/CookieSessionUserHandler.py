
import binascii
import js2py
import json
import random
import re
import requests
import time
import tweepy
from js2py.base import JsObjectWrapper
from requests.auth import AuthBase
from requests.cookies import RequestsCookieJar
from requests.models import PreparedRequest
from typing import Any, cast, Dict, Optional, TypeVar


Self = TypeVar("Self", bound="CookieSessionUserHandler")

class CookieSessionUserHandler(AuthBase):
    """
    Twitter Web App の内部 API を使い、Cookie ログインで Twitter API を利用するための認証ハンドラー

    認証フローは2023年2月現在の Twitter Web App (Chrome Desktop) の挙動に極力合わせたもの
    requests.auth.AuthBase を継承しているので、tweepy.API の auth パラメーターに渡すことができる

    ref: https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/twitter.py
    ref: https://github.com/fa0311/TwitterFrontendFlow/blob/master/TwitterFrontendFlow/TwitterFrontendFlow.py
    """

    # User-Agent と Sec-CH-UA を Chrome 127 に偽装
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'
    SEC_CH_UA = '"Chromium";v="127", "Google Chrome";v="127", "Not-A.Brand";v="99"'

    # Twitter Web App (GraphQL API) の Bearer トークン
    TWITTER_WEB_APP_BEARER_TOKEN = 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'

    # 旧 TweetDeck (Twitter API v1.1) の Bearer トークン
    TWEETDECK_BEARER_TOKEN = 'Bearer AAAAAAAAAAAAAAAAAAAAAFQODgEAAAAAVHTp76lzh3rFzcHbmHVvQxYYpTw%3DckAlMINMjmCwxUcaXbAN4XqJVdgMJaHqNOFgPMK0zN1qLqLQCF'


    def __init__(self, cookies: Optional[RequestsCookieJar] = None, screen_name: Optional[str] = None, password: Optional[str] = None) -> None:
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
        self._html_headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-encoding': 'gzip, deflate, br',
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
        self._js_headers = self._html_headers.copy()
        self._js_headers['accept'] = '*/*'
        self._js_headers['referer'] = 'https://x.com/'
        self._js_headers['sec-fetch-dest'] = 'script'
        self._js_headers['sec-fetch-mode'] = 'no-cors'
        del self._js_headers['sec-fetch-user']

        # 認証フロー API アクセス時の HTTP リクエストヘッダー
        self._auth_flow_api_headers = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'ja',
            'authorization': self.TWITTER_WEB_APP_BEARER_TOKEN,
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
            'x-csrf-token': None,  # ここは後でセットする
            'x-guest-token': None,  # ここは後でセットする
            'x-twitter-active-user': 'yes',
            'x-twitter-client-language': 'ja',
        }

        # GraphQL API (Twitter Web App API) アクセス時の HTTP リクエストヘッダー
        ## GraphQL API は https://x.com/i/api/graphql/ 配下にあり同一ドメインのため、origin と referer は意図的に省略している
        self._graphql_api_headers = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'ja',
            'authorization': self.TWITTER_WEB_APP_BEARER_TOKEN,
            'content-type': 'application/json',
            'sec-ch-ua': self.SEC_CH_UA,
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': self.USER_AGENT,
            'x-csrf-token': None,  # ここは後でセットする
            'x-twitter-active-user': 'yes',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'ja',
        }

        # Cookie ログイン用のセッションを作成
        ## 実際の Twitter API へのリクエストには tweepy.API 側で作成されたセッションが利用される
        ## その際、__call__() で tweepy.API で作成されたセッションのリクエストヘッダーと Cookie を上書きしている
        self._session = requests.Session()

        # API からレスポンスが返ってきた際に自動で CSRF トークンを更新する
        ## 認証に成功したタイミングで、Cookie の "ct0" 値 (CSRF トークン) がクライアント側で生成したものから、サーバー側で生成したものに更新される
        self._session.hooks['response'].append(self._on_response_received)

        # Cookie が指定されている場合は、それをセッションにセット (再ログインを省略する)
        if cookies is not None:
            self._session.cookies = cookies

        # Cookie が指定されていない場合は、ログインを試みる
        else:
            self._login()

        # Cookie から auth_token または ct0 が取得できなかった場合
        ## auth_token と ct0 はいずれも認証に最低限必要な Cookie のため、取得できなかった場合は認証に失敗したものとみなす
        if self._session.cookies.get('auth_token', default=None) is None or self._session.cookies.get('ct0', default=None) is None:
            raise tweepy.TweepyException('Failed to get auth_token or ct0 from Cookie')

        # Cookie の "gt" 値 (ゲストトークン) を認証フロー API 用ヘッダーにセット
        guest_token = self._session.cookies.get('gt')
        if guest_token:
            self._auth_flow_api_headers['x-guest-token'] = guest_token

        # Cookie の "ct0" 値 (CSRF トークン) を GraphQL API 用ヘッダーにセット
        csrf_token = self._session.cookies.get('ct0')
        if csrf_token:
            self._auth_flow_api_headers['x-csrf-token'] = csrf_token
            self._graphql_api_headers['x-csrf-token'] = csrf_token

        # セッションのヘッダーを GraphQL API 用のものに差し替える
        ## 以前は旧 TweetDeck API 用ヘッダーに差し替えていたが、旧 TweetDeck が完全廃止されたことで
        ## 逆に怪しまれる可能性があるため GraphQL API 用ヘッダーに変更した
        ## cross_origin=True を指定して、x.com から api.x.com にクロスオリジンリクエストを送信した際のヘッダーを模倣する
        self._session.headers.clear()
        self._session.headers.update(self.get_graphql_api_headers(cross_origin=True))


    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        """
        requests ライブラリからリクエスト開始時に呼び出されるフック

        Args:
            request (PreparedRequest): PreparedRequest オブジェクト

        Returns:
            PreparedRequest: 認証情報を追加した PreparedRequest オブジェクト
        """

        # リクエストヘッダーを認証用セッションのものに差し替える
        # content-type を上書きしないよう、content-type を控えておいてから差し替える
        content_type = request.headers.get('content-type', None)
        request.headers.update(self._session.headers)  # type: ignore
        if content_type is not None:
            request.headers['content-type'] = content_type  # 元の content-type に戻す

        # リクエストがまだ *.twitter.com に対して行われている場合は、*.x.com に差し替える
        ## サードパーティー向け API は互換性のため引き続き api.twitter.com でアクセスできるはずだが、
        ## tweepy-authlib でアクセスしている API は内部 API のため、api.twitter.com のままアクセスしていると怪しまれる可能性がある
        assert request.url is not None
        request.url = request.url.replace('twitter.com/', 'x.com/')

        # Twitter API v1.1 の一部 API には旧 TweetDeck 用の Bearer トークンでないとアクセスできないため、
        # 該当の API のみ旧 TweetDeck 用の Bearer トークンに差し替える
        # それ以外の API ではそのまま Twitter Web App の Bearer トークンを使い続けることで、不審判定される可能性を下げる
        ## OldTweetDeck の interception.js に記載の API のうち、明示的に PUBLIC_TOKEN[1] が設定されている API が対象
        ## ref: https://github.com/dimdenGD/OldTweetDeck/blob/main/src/interception.js
        TWEETDECK_BEARER_TOKEN_REQUIRED_APIS = [
            '/1.1/statuses/home_timeline.json',
            '/1.1/lists/statuses.json',
            '/1.1/activity/about_me.json',
            '/1.1/statuses/mentions_timeline.json',
            '/1.1/favorites/',
            '/1.1/collections/',
        ]
        if any(api_url in request.url for api_url in TWEETDECK_BEARER_TOKEN_REQUIRED_APIS):
            request.headers['authorization'] = self.TWEETDECK_BEARER_TOKEN

        # upload.twitter.com or upload.x.com 以下の API のみ、Twitter Web App の挙動に合わせいくつかのヘッダーを削除する
        if 'upload.twitter.com' in request.url or 'upload.x.com' in request.url:
            request.headers.pop('x-client-transaction-id', None)  # 未実装だが将来的に実装した時のため
            request.headers.pop('x-twitter-active-user', None)
            request.headers.pop('x-twitter-client-language', None)

        # Cookie を認証用セッションのものに差し替える
        request._cookies.update(self._session.cookies)  # type: ignore
        cookie_header = ''
        for key, value in self._session.cookies.get_dict().items():
            cookie_header += f'{key}={value}; '
        request.headers['cookie'] = cookie_header.rstrip('; ')

        # API からレスポンスが返ってきた際に自動で CSRF トークンを更新する
        ## やらなくても大丈夫かもしれないけど、念のため
        request.hooks['response'].append(self._on_response_received)

        # 認証情報を追加した PreparedRequest オブジェクトを返す
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

        return self._session.cookies


    def get_cookies_as_dict(self) -> Dict[str, str]:
        """
        現在のログインセッションの Cookie を dict として取得する
        返される dict を保存しておくことで、再ログインせずにセッションを継続できる

        Returns:
            Dict[str, str]: Cookie
        """

        return self._session.cookies.get_dict()


    def get_html_headers(self) -> Dict[str, str]:
        """
        Twitter Web App の HTML アクセス用の HTTP リクエストヘッダーを取得する
        Cookie やトークン類の取得のために HTML ページに HTTP リクエストを送る際の利用を想定している

        Returns:
            Dict[str, str]: HTML アクセス用の HTTP リクエストヘッダー
        """

        return self._html_headers.copy()


    def get_graphql_api_headers(self, cross_origin: bool = False) -> Dict[str, str]:
        """
        GraphQL API (Twitter Web App API) アクセス用の HTTP リクエストヘッダーを取得する
        このリクエストヘッダーを使い独自に API リクエストを行う際は、
        必ず x-csrf-token ヘッダーの値を常に Cookie 内の "ct0" と一致させるように実装しなければならない
        Twitter API v1.1 に使う場合は cross_origin=True を指定すること (api.x.com が x.com から見て cross-origin になるため)
        逆に GraphQL API に使う場合は cross_origin=False でなければならない (GraphQL API は x.com から見て same-origin になるため)

        Args:
            cross_origin (bool, optional): 返すヘッダーを x.com 以外のオリジンに送信するかどうか. Defaults to False.

        Returns:
            Dict[str, str]: GraphQL API (Twitter Web App API) アクセス用の HTTP リクエストヘッダー
        """

        headers = self._graphql_api_headers.copy()

        # クロスオリジン用に origin と referer を追加
        # Twitter Web App から api.x.com にクロスオリジンリクエストを送信する際のヘッダーを模倣する
        if cross_origin is True:
            headers['origin'] = 'https://x.com'
            headers['referer'] = 'https://x.com/'

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
        logout_headers = self._graphql_api_headers.copy()
        logout_headers['content-type'] = 'application/x-www-form-urlencoded'

        # ログアウト API にログアウトすることを伝える
        ## この API を実行すると、サーバー側でセッションが切断され、今まで持っていたほとんどの Cookie が消去される
        logout_api_response = self._session.post('https://api.x.com/1.1/account/logout.json', headers=logout_headers, data={
            'redirectAfterLogout': 'https://x.com/account/switch',
        })
        if logout_api_response.status_code != 200:
            raise self._get_tweepy_exception(logout_api_response)

        # 基本固定値のようなので不要だが、念のためステータスチェック
        try:
            status = logout_api_response.json()['status']
        except:
            raise tweepy.TweepyException('Failed to logout (failed to parse response)')
        if status != 'ok':
            raise tweepy.TweepyException(f'Failed to logout (status: {status})')


    def _on_response_received(self, response: requests.Response, *args, **kwargs) -> None:
        """
        レスポンスが返ってきた際に自動的に CSRF トークンを更新するコールバック

        Args:
            response (requests.Response): レスポンス
        """

        csrf_token = response.cookies.get('ct0')
        if csrf_token:
            if self._session.cookies.get('ct0') != csrf_token:
                self._session.cookies.set('ct0', csrf_token, domain='.x.com')
            self._auth_flow_api_headers['x-csrf-token'] = csrf_token
            self._graphql_api_headers['x-csrf-token'] = csrf_token
            self._session.headers['x-csrf-token'] = csrf_token


    def _get_tweepy_exception(self, response: requests.Response) -> tweepy.TweepyException:
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


    def _generate_csrf_token(self, size: int = 16) -> str:
        """
        Twitter の CSRF トークン (Cookie 内の "ct0" 値) を生成する

        Args:
            size (int, optional): トークンサイズ. Defaults to 16.

        Returns:
            str: 生成されたトークン
        """

        data = random.getrandbits(size * 8).to_bytes(size, "big")
        return binascii.hexlify(data).decode()


    def _get_guest_token(self) -> str:
        """
        ゲストトークン (Cookie 内の "gt" 値) を取得する

        Returns:
            str: 取得されたトークン
        """

        # HTTP ヘッダーは基本的に認証用セッションのものを使う
        headers = self._auth_flow_api_headers.copy()
        headers.pop('x-csrf-token')
        headers.pop('x-guest-token')

        # API からゲストトークンを取得する
        # ref: https://github.com/fa0311/TwitterFrontendFlow/blob/master/TwitterFrontendFlow/TwitterFrontendFlow.py#L26-L36
        guest_token_response = self._session.post('https://api.x.com/1.1/guest/activate.json', headers=headers)
        if guest_token_response.status_code != 200:
            raise self._get_tweepy_exception(guest_token_response)
        try:
            guest_token = guest_token_response.json()['guest_token']
        except:
            raise tweepy.TweepyException('Failed to get guest token')

        return guest_token


    def _get_ui_metrics(self, js_inst: str) -> Dict[str, Any]:
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
        js_inst_function_name = re.search(re.compile(r'function [a-zA-Z]+'), js_inst_function).group().replace('function ', '')  # type: ignore

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
        js_context = js2py.EvalJs()
        js_context.execute(js_dom_mock)
        js_context.execute(js_inst_function)
        js_context.execute(f'var ui_metrics = {js_inst_function_name}()')

        # ui_metrics を取得
        ui_metrics = cast(JsObjectWrapper, js_context.ui_metrics)
        return cast(Dict[str, Any], ui_metrics.to_dict())


    def _login(self) -> None:
        """
        スクリーンネームとパスワードを使って認証し、ログインする

        Raises:
            tweepy.BadRequest: スクリーンネームまたはパスワードが間違っている
            tweepy.HTTPException: サーバーエラーなどの問題でログインに失敗した
            tweepy.TweepyException: 認証フローの途中でエラーが発生し、ログインに失敗した
        """

        def get_flow_token(response: requests.Response) -> str:
            try:
                data = response.json()
            except ValueError:
                pass
            else:
                if response.status_code < 400:
                    return data['flow_token']
            raise self._get_tweepy_exception(response)

        # Cookie をクリア
        self._session.cookies.clear()

        # 一度 https://x.com/ にアクセスして Cookie をセットさせる
        ## 取得した HTML はゲストトークンを取得するために使う
        html_response = self._session.get('https://x.com/i/flow/login', headers=self._html_headers)
        if html_response.status_code != 200:
            raise self._get_tweepy_exception(html_response)

        # CSRF トークンを生成し、"ct0" としてセッションの Cookie に保存
        ## 同時に認証フロー API 用の HTTP リクエストヘッダーにもセット ("ct0" と "x-csrf-token" は同じ値になる)
        csrf_token = self._generate_csrf_token()
        self._session.cookies.set('ct0', csrf_token, domain='.x.com')
        self._auth_flow_api_headers['x-csrf-token'] = csrf_token

        # まだ取得できていない場合のみ、ゲストトークンを取得し、"gt" としてセッションの Cookie に保存
        if self._session.cookies.get('gt', default=None) is None:
            guest_token = self._get_guest_token()
            self._session.cookies.set('gt', guest_token, domain='.x.com')

        ## ゲストトークンを認証フロー API 用の HTTP リクエストヘッダーにもセット ("gt" と "x-guest-token" は同じ値になる)
        self._auth_flow_api_headers['x-guest-token'] = self._session.cookies.get('gt')

        # これ以降は基本認証フロー API へのアクセスしか行わないので、セッションのヘッダーを認証フロー API 用のものに差し替える
        self._session.headers.clear()
        self._session.headers.update(self._auth_flow_api_headers)

        # 極力公式の Twitter Web App に偽装するためのダミーリクエスト
        self._session.get('https://api.x.com/1.1/hashflags.json')

        # https://api.x.com/1.1/onboarding/task.json?task=login に POST して認証フローを開始
        ## 認証フローを開始するには、Cookie に "ct0" と "gt" がセットされている必要がある
        ## 2024年5月時点の Twitter Web App が送信する JSON パラメータを模倣している
        flow_01_response = self._session.post('https://api.x.com/1.1/onboarding/task.json?flow_name=login', json={
            'input_flow_data': {
                'flow_context': {
                    'debug_overrides': {},
                    'start_location': {
                        'location': 'manual_link',
                    }
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
            }
        })
        if flow_01_response.status_code != 200:
            raise self._get_tweepy_exception(flow_01_response)

        # js_inst (難読化された JavaScript で、これの実行結果を認証フローに送信する必要があるらしい) を取得
        ## 2024/05/18 時点の Twitter Web App では js_inst のみ x.com ではなく twitter.com から取得されているが、
        ## 将来的なことを考慮しあえて x.com から取得している
        js_inst_response = self._session.get('https://x.com/i/js_inst?c_name=ui_metrics', headers=self._js_headers)
        if js_inst_response.status_code != 200:
            raise tweepy.TweepyException('Failed to get js_inst')

        # js_inst の JavaScript を実行し、ui_metrics オブジェクトを取得
        ui_metrics = self._get_ui_metrics(js_inst_response.text)

        # 取得した ui_metrics を認証フローに送信
        flow_02_response = self._session.post('https://api.x.com/1.1/onboarding/task.json', json={
            'flow_token': get_flow_token(flow_01_response),
            'subtask_inputs': [
                {
                    'subtask_id': 'LoginJsInstrumentationSubtask',
                    'js_instrumentation': {
                        'response': json.dumps(ui_metrics),
                        'link': 'next_link',
                    }
                },
            ]
        })
        if flow_02_response.status_code != 200:
            raise self._get_tweepy_exception(flow_02_response)

        # 極力公式の Twitter Web App に偽装するためのダミーリクエスト
        self._session.post('https://api.x.com/1.1/onboarding/sso_init.json', json={'provider': 'apple'})

        # 怪しまれないように、2秒～4秒の間にランダムな時間待機
        time.sleep(random.uniform(2.0, 4.0))

        # スクリーンネームを認証フローに送信
        flow_03_response = self._session.post('https://api.x.com/1.1/onboarding/task.json', json={
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
                                }
                            },
                        ],
                        'link': 'next_link',
                    }
                },
            ]
        })
        if flow_03_response.status_code != 200:
            raise self._get_tweepy_exception(flow_03_response)

        # 怪しまれないように、2秒～4秒の間にランダムな時間待機
        time.sleep(random.uniform(2.0, 4.0))

        # パスワードを認証フローに送信
        flow_04_response = self._session.post('https://api.x.com/1.1/onboarding/task.json', json={
            'flow_token': get_flow_token(flow_03_response),
            'subtask_inputs': [
                {
                    'subtask_id': 'LoginEnterPassword',
                    'enter_password': {
                        'password': self.password,
                        'link': 'next_link',
                    }
                },
            ]
        })
        if flow_04_response.status_code != 200:
            raise self._get_tweepy_exception(flow_04_response)

        # ログイン失敗
        if flow_04_response.json()['status'] != 'success':
            raise tweepy.TweepyException(f'Failed to login (status: {flow_04_response.json()["status"]})')

        # 最後におまじないを認証フローに送信 (アカウント重複チェック…？)
        ## このリクエストで、Cookie に auth_token がセットされる
        flow_05_response = self._session.post('https://api.x.com/1.1/onboarding/task.json', json={
            'flow_token': get_flow_token(flow_04_response),
            'subtask_inputs': [
                {
                    'subtask_id': 'AccountDuplicationCheck',
                    'check_logged_in_account': {
                        'link': 'AccountDuplicationCheck_false',
                    }
                },
            ]
        })
        if flow_05_response.status_code != 200:
            raise self._get_tweepy_exception(flow_05_response)

        # 最後の最後にファイナライズを行う
        ## たぶんなくても動くけど、念のため
        ## このタイミングで Cookie の "ct0" 値 (CSRF トークン) がクライアント側で生成したものから、サーバー側で生成したものに更新される
        flow_06_response = self._session.post('https://api.x.com/1.1/onboarding/task.json', json={
            'flow_token': get_flow_token(flow_05_response),
            'subtask_inputs': [],
        })
        if flow_06_response.status_code != 200:
            raise self._get_tweepy_exception(flow_06_response)

        # ここまで来たら、ログインに成功しているはず
        ## Cookie にはログインに必要な情報が入っている
        ## 実際に認証に最低限必要な Cookie は "auth_token" と "ct0" のみ (とはいえそれだけだと怪しまれそうなので、それ以外の値も送る)
        ## ref: https://qiita.com/SNQ-2001/items/182b278e1e8aaaa21a13
