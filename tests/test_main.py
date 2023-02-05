
import os
import pickle
import pytest
import tweepy
from tweepy.errors import BadRequest
from tweepy_authlib import CookieSessionUserHandler


def test_01():
    with pytest.raises(ValueError):
        CookieSessionUserHandler()

def test_02():
    with pytest.raises(ValueError):
        CookieSessionUserHandler(screen_name='', password='password')

def test_03():
    with pytest.raises(ValueError):
        CookieSessionUserHandler(screen_name='elonmusk', password='')

def test_04():
    with pytest.raises(BadRequest, match=r'.*399 - アカウントが見つかりません。.*'):
        CookieSessionUserHandler(screen_name='not__found__user', password='password')

def test_05():
    with pytest.raises(BadRequest, match=r'.*399 - パスワードが正しくありません。.*'):
        CookieSessionUserHandler(screen_name='elonmusk', password='password')

def test_06():

    # 環境変数に TWITTER_SCREEN_NAME と TWITTER_PASSWORD が設定されている場合のみ実行
    if 'TWITTER_SCREEN_NAME' in os.environ and 'TWITTER_PASSWORD' in os.environ:
        auth_handler = CookieSessionUserHandler(screen_name=os.environ['TWITTER_SCREEN_NAME'], password=os.environ['TWITTER_PASSWORD'])
        with open('cookie.pickle', 'wb') as f:
            pickle.dump(auth_handler.get_cookies(), f)
        api = tweepy.API(auth_handler)
        assert api.verify_credentials().screen_name == os.environ['TWITTER_SCREEN_NAME']
        assert api.user_timeline(screen_name='elonmusk')[0].user.screen_name == 'elonmusk'
        api.home_timeline()
    else:
        pytest.skip('TWITTER_SCREEN_NAME or TWITTER_PASSWORD is not set.')

def test_07():

    # 環境変数に TWITTER_SCREEN_NAME と TWITTER_PASSWORD が設定されている場合のみ実行
    if 'TWITTER_SCREEN_NAME' in os.environ and 'TWITTER_PASSWORD' in os.environ:
        with open('cookie.pickle', 'rb') as f:
            auth_handler = CookieSessionUserHandler(cookies=pickle.load(f))
        os.unlink('cookie.pickle')
        api = tweepy.API(auth_handler)
        assert api.verify_credentials().screen_name == os.environ['TWITTER_SCREEN_NAME']
        assert api.user_timeline(screen_name='elonmusk')[0].user.screen_name == 'elonmusk'
        api.home_timeline()
    else:
        pytest.skip('TWITTER_SCREEN_NAME or TWITTER_PASSWORD is not set.')
