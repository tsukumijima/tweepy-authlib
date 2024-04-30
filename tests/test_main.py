
import datetime
import dotenv
import os
import pickle
import pytest
import tweepy
from tweepy_authlib import CookieSessionUserHandler


try:
    terminal_size = os.get_terminal_size().columns
except OSError:
    terminal_size = 80

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
    with pytest.raises(tweepy.BadRequest, match=r'.*399 - アカウントが見つかりません。.*'):
        CookieSessionUserHandler(screen_name='not__found__user', password='password')

def test_05():
    with pytest.raises(tweepy.BadRequest, match=r'.*399 - パスワードが正しくありません。.*'):
        CookieSessionUserHandler(screen_name='elonmusk', password='password')

def test_06():

    # 環境変数に TWITTER_SCREEN_NAME と TWITTER_PASSWORD が設定されている場合のみ実行
    if 'TWITTER_SCREEN_NAME' in os.environ and 'TWITTER_PASSWORD' in os.environ:
        print(f'Logging in as @{os.environ["TWITTER_SCREEN_NAME"]}.')
        auth_handler = CookieSessionUserHandler(screen_name=os.environ['TWITTER_SCREEN_NAME'], password=os.environ['TWITTER_PASSWORD'])
        print(f'Logged in as @{os.environ["TWITTER_SCREEN_NAME"]}.')
        api = tweepy.API(auth_handler)
        user = api.verify_credentials()
        print('-' * terminal_size)
        print(user)
        print('-' * terminal_size)
        assert user.screen_name == os.environ['TWITTER_SCREEN_NAME']
        # assert api.user_timeline(screen_name='elonmusk')[0].user.screen_name == 'elonmusk'
        # api.home_timeline()
        with open('cookie.pickle', 'wb') as f:
            pickle.dump(auth_handler.get_cookies(), f)
    else:
        pytest.skip('TWITTER_SCREEN_NAME or TWITTER_PASSWORD is not set.')

def test_07(tweet: bool = False):

    # 環境変数に TWITTER_SCREEN_NAME と TWITTER_PASSWORD が設定されている場合のみ実行
    if 'TWITTER_SCREEN_NAME' in os.environ and 'TWITTER_PASSWORD' in os.environ:
        print(f'Logging in as @{os.environ["TWITTER_SCREEN_NAME"]}.')
        with open('cookie.pickle', 'rb') as f:
            jar = pickle.load(f)
            print('Cookie:')
            print(jar)
            auth_handler = CookieSessionUserHandler(cookies=jar)
        print(f'Logged in as @{os.environ["TWITTER_SCREEN_NAME"]}.')
        os.unlink('cookie.pickle')
        api = tweepy.API(auth_handler)
        user = api.verify_credentials()
        # if tweet is True:
        #     print('-' * terminal_size)
        #     print(api.update_status(f'Hello, Twitter! (API Test Tweet, {datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")})'))
        print('-' * terminal_size)
        print(user)
        print('-' * terminal_size)
        assert user.screen_name == os.environ['TWITTER_SCREEN_NAME']
        # assert api.user_timeline(screen_name='elonmusk')[0].user.screen_name == 'elonmusk'
        # api.home_timeline()
        auth_handler.logout()
    else:
        pytest.skip('TWITTER_SCREEN_NAME or TWITTER_PASSWORD is not set.')


if __name__ == '__main__':
    dotenv.load_dotenv()
    test_06()
    test_07(tweet = True)
