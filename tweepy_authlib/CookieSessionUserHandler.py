
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

    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36';
    sec_ch_ua = '"Not_A Brand";v="99", "Google Chrome";v="109", "Chromium";v="109"';


    def __init__(self, cookies: Optional[RequestsCookieJar] = None, screen_name: Optional[str] = None, password: Optional[str] = None) -> None:
        """
        CookieSessionUserHandler を初期化する
        cookies と screen_name, password のどちらかを指定する必要がある

        Args:
            cookies (Optional[RequestsCookieJar], optional): リクエスト時に利用する Cookie. Defaults to None.
            screen_name (Optional[str], optional): Twitter のスクリーンネーム (@は含まない). Defaults to None.
            password (Optional[str], optional): Twitter のパスワード. Defaults to None.
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
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'ja',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'sec-ch-ua': self.sec_ch_ua,
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': self.user_agent,
        }

        # JavaScript 取得時の HTTP リクエストヘッダー
        self._js_headers = self._html_headers.copy()
        self._js_headers['accept'] = '*/*'
        self._js_headers['referer'] = 'https://twitter.com/'
        self._js_headers['sec-fetch-dest'] = 'script'
        self._js_headers['sec-fetch-mode'] = 'no-cors'
        del self._js_headers['sec-fetch-user']

        # 認証フロー API アクセス時の HTTP リクエストヘッダー
        self._auth_flow_api_headers = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'ja',
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'cache-control': 'no-cache',
            'origin': 'https://twitter.com',
            'pragma': 'no-cache',
            'referer': 'https://twitter.com/',
            'sec-ch-ua': self.sec_ch_ua,
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': self.user_agent,
            'x-csrf-token': None,  # ここは後でセットする
            'x-guest-token': None,  # ここは後でセットする
            'x-twitter-active-user': 'yes',
            'x-twitter-client-language': 'ja',
        }

        # TweetDeck API (Twitter API v1.1) アクセス時の HTTP リクエストヘッダー
        self._tweetdeck_api_headers = {
            'accept': 'text/plain, */*; q=0.01',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'ja',
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAAF7aAAAAAAAASCiRjWvh7R5wxaKkFp7MM%2BhYBqM%3DbQ0JPmjU9F6ZoMhDfI4uTNAaQuTDm2uO9x3WFVr2xBZ2nhjdP0',
            'cache-control': 'no-cache',
            'origin': 'https://tweetdeck.twitter.com',
            'pragma': 'no-cache',
            'referer': 'https://tweetdeck.twitter.com/',
            'sec-ch-ua': self.sec_ch_ua,
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': self.user_agent,
            'x-csrf-token': None,  # ここは後でセットする
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-version': 'Twitter-TweetDeck-blackbird-chrome/4.0.220811153004 web/',
        }

        # Cookie ログイン用のセッションを作成
        ## 実際の Twitter API へのリクエストには tweepy.API 側で作成されたセッションが利用される
        ## その際、__call__() で tweepy.API で作成されたセッションのリクエストヘッダーと Cookie を上書きしている
        self._session = requests.Session()

        # API からレスポンスが返ってきた際に自動で CSRF トークンを更新する
        ## 認証に成功したタイミングで、Cookie の "ct0" 値 (CSRF トークン) がクライアント側で生成したものから、サーバー側で生成したものに更新される
        def update_csrf_token(response: requests.Response, *args, **kwargs) -> None:
            csrf_token = response.cookies.get('ct0')
            if csrf_token:
                self._auth_flow_api_headers['x-csrf-token'] = csrf_token
                self._tweetdeck_api_headers['x-csrf-token'] = csrf_token
                self._session.headers['x-csrf-token'] = csrf_token
        self._session.hooks['response'].append(update_csrf_token)

        # Cookie が指定されている場合は、それをセッションにセット (再ログインを省略する)
        if cookies is not None:
            self._session.cookies = cookies

        # Cookie が指定されていない場合は、ログインを試みる
        else:
            self._login()

        # Cookie の "gt" 値 (ゲストトークン) を認証フロー API 用ヘッダーにセット
        guest_token = self._session.cookies.get('gt')
        if guest_token:
            self._auth_flow_api_headers['x-guest-token'] = guest_token

        # Cookie の "ct0" 値 (CSRF トークン) を TweetDeck API 用ヘッダーにセット
        csrf_token = self._session.cookies.get('ct0')
        if csrf_token:
            self._auth_flow_api_headers['x-csrf-token'] = csrf_token
            self._tweetdeck_api_headers['x-csrf-token'] = csrf_token

        # これ以降は基本 TweetDeck API へのアクセスしか行わないので、セッションのヘッダーを TweetDeck API 用のものに差し替える
        self._session.headers.clear()
        self._session.headers.update(self._tweetdeck_api_headers)


    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        """
        requests ライブラリからリクエスト開始時に呼び出されるフック

        Args:
            request (PreparedRequest): PreparedRequest オブジェクト

        Returns:
            PreparedRequest: 認証情報を追加した PreparedRequest オブジェクト
        """

        # リクエストヘッダーを認証用セッションのものに差し替える
        request.headers.update(self._session.headers)  # type: ignore

        # Cookie を認証用セッションのものに差し替える
        request._cookies.update(self._session.cookies)  # type: ignore
        cookie_header = ''
        for key, value in self._session.cookies.get_dict().items():
            cookie_header += f'{key}={value}; '
        request.headers['cookie'] = cookie_header

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
            str: RequestsCookieJar
        """
        return self._session.cookies


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


    def _get_guest_token(self, html: str)  -> str:
        """
        Twitter の HTML からゲストトークン (Cookie 内の "gt" 値) を取得する
        すでに Cookie 内の "gt0" 値がセットされた状態で HTML を取得するとゲストトークンが HTML に埋め込まれないため注意

        Returns:
            str: 取得されたトークン
        """

        # document.cookie = decodeURIComponent("gt=0000000000000000000; Max-Age=10800; Domain=.twitter.com; Path=/; Secure");
        # のようなフォーマットで HTML に埋め込まれているので、正規表現で抽出する
        match = re.search(re.compile(r'document.cookie = decodeURIComponent\("gt=(\d+); Max-Age='), html)
        if match is None:
            raise tweepy.TweepyException('Failed to get guest token')
        return match.group(1)


    def _get_ui_metrics(self, js_inst: str) -> Dict[str, Any]:
        """
        https://twitter.com/i/js_inst?c_name=ui_metrics から出力される難読化された JavaScript から ui_metrics を取得する
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

        # 一度 https://twitter.com/ にアクセスして Cookie をセットさせる
        ## 取得した HTML はゲストトークンを取得するために使う
        html_response = self._session.get('https://twitter.com/i/flow/login', headers=self._html_headers)
        if html_response.status_code != 200:
            raise self._get_tweepy_exception(html_response)

        # CSRF トークンを生成し、"ct0" としてセッションの Cookie に保存
        ## 同時に認証フロー API 用の HTTP リクエストヘッダーにもセット ("ct0" と "x-csrf-token" は同じ値になる)
        csrf_token = self._generate_csrf_token()
        self._session.cookies.set('ct0', csrf_token, domain='.twitter.com')
        self._auth_flow_api_headers['x-csrf-token'] = csrf_token

        # ゲストトークンを取得し、"gt" としてセッションの Cookie に保存
        ## 同時に認証フロー API 用の HTTP リクエストヘッダーにもセット ("gt" と "x-guest-token" は同じ値になる)
        guest_token = self._get_guest_token(html_response.text)
        self._session.cookies.set('gt', guest_token, domain='.twitter.com')
        self._auth_flow_api_headers['x-guest-token'] = guest_token

        # これ以降は基本認証フロー API へのアクセスしか行わないので、セッションのヘッダーを認証フロー API 用のものに差し替える
        self._session.headers.clear()
        self._session.headers.update(self._auth_flow_api_headers)

        # 極力公式の Twitter Web App に偽装するためのダミーリクエスト
        ## https://api.twitter.com/1.1/attribution/event.json に関してはもしかすると意味があるかも
        self._session.get('https://api.twitter.com/1.1/hashflags.json',)
        self._session.post('https://api.twitter.com/1.1/attribution/event.json', json={'event': 'open'})

        # https://api.twitter.com/1.1/onboarding/task.json?task=login に POST して認証フローを開始
        ## 認証フローを開始するには、Cookie に "ct0" と "gt" がセットされている必要がある
        flow_01_response = self._session.post('https://api.twitter.com/1.1/onboarding/task.json?flow_name=login', json={
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

        # 極力公式の Twitter Web App に偽装するためのダミーリクエスト
        self._session.post('https://api.twitter.com/1.1/branch/init.json', json={})

        # js_inst (難読化された JavaScript で、これの実行結果を認証フローに送信する必要があるらしい) を取得
        js_inst_response = self._session.get('https://twitter.com/i/js_inst?c_name=ui_metrics')
        if js_inst_response.status_code != 200:
            raise tweepy.TweepyException('Failed to get js_inst')

        # js_inst の JavaScript を実行し、ui_metrics オブジェクトを取得
        ui_metrics = self._get_ui_metrics(js_inst_response.text)

        # 取得した ui_metrics を認証フローに送信
        flow_02_response = self._session.post('https://api.twitter.com/1.1/onboarding/task.json', json={
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
        self._session.post('https://api.twitter.com/1.1/onboarding/sso_init.json', json={'provider': 'apple'})

        # 怪しまれないように、2秒～4秒の間にランダムな時間待機
        time.sleep(random.uniform(2.0, 4.0))

        # スクリーンネームを認証フローに送信
        flow_03_response = self._session.post('https://api.twitter.com/1.1/onboarding/task.json', json={
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
        flow_04_response = self._session.post('https://api.twitter.com/1.1/onboarding/task.json', json={
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
        flow_05_response = self._session.post('https://api.twitter.com/1.1/onboarding/task.json', json={
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
        flow_06_response = self._session.post('https://api.twitter.com/1.1/onboarding/task.json', json={
            'flow_token': get_flow_token(flow_05_response),
            'subtask_inputs': [],
        })
        if flow_06_response.status_code != 200:
            raise self._get_tweepy_exception(flow_06_response)

        # ここまで来たら、ログインに成功しているはず
        ## Cookie にはログインに必要な情報が入っている
        ## 実際に認証に最低限必要な Cookie は "auth_token" と "ct0" のみ (とはいえそれだけだと怪しまれそうなので、それ以外の値も送る)
        ## ref: https://qiita.com/SNQ-2001/items/182b278e1e8aaaa21a13
