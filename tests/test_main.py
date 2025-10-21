import os
import pickle
from pprint import pprint

import dotenv
import pytest
import tweepy

from tweepy_authlib import CookieSessionUserHandler


try:
    terminal_size = os.get_terminal_size().columns
except OSError:
    terminal_size = 80


def test_validate_arguments_01():
    with pytest.raises(ValueError):
        CookieSessionUserHandler()


def test_validate_arguments_02():
    with pytest.raises(ValueError):
        CookieSessionUserHandler(screen_name='', password='password')


def test_validate_arguments_03():
    with pytest.raises(ValueError):
        CookieSessionUserHandler(screen_name='elonmusk', password='')


def test_login_with_screen_name_and_password():
    # 環境変数に TWITTER_SCREEN_NAME と TWITTER_PASSWORD が設定されている場合のみ実行
    if 'TWITTER_SCREEN_NAME' in os.environ and 'TWITTER_PASSWORD' in os.environ:
        print('=' * terminal_size)
        print(f'Logging in as @{os.environ["TWITTER_SCREEN_NAME"]}.')
        auth_handler = CookieSessionUserHandler(
            screen_name=os.environ['TWITTER_SCREEN_NAME'], password=os.environ['TWITTER_PASSWORD']
        )
        print('-' * terminal_size)
        print(f'Logged in as @{os.environ["TWITTER_SCREEN_NAME"]}.')
        api = tweepy.API(auth_handler)

        print('=' * terminal_size)
        print('Logged in user:')
        print('-' * terminal_size)
        user = api.verify_credentials()
        assert user.screen_name == os.environ['TWITTER_SCREEN_NAME']
        pprint(user._json)
        print('=' * terminal_size)

        with open('cookie.pickle', 'wb') as f:
            pickle.dump(auth_handler.get_cookies(), f)
    else:
        pytest.skip('TWITTER_SCREEN_NAME or TWITTER_PASSWORD is not set.')


def test_login_with_cookies(tweet: bool = False):
    # 環境変数に TWITTER_SCREEN_NAME と TWITTER_PASSWORD が設定されている場合のみ実行
    if 'TWITTER_SCREEN_NAME' in os.environ and 'TWITTER_PASSWORD' in os.environ:
        print('=' * terminal_size)
        print(f'Logging in as @{os.environ["TWITTER_SCREEN_NAME"]}.')
        print('-' * terminal_size)
        with open('cookie.pickle', 'rb') as f:
            jar = pickle.load(f)
            print('Cookie:')
            pprint(jar.get_dict())
            auth_handler = CookieSessionUserHandler(cookies=jar)
        print('-' * terminal_size)
        print(f'Logged in as @{os.environ["TWITTER_SCREEN_NAME"]}.')
        os.unlink('cookie.pickle')
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

        auth_handler.logout()
    else:
        pytest.skip('TWITTER_SCREEN_NAME or TWITTER_PASSWORD is not set.')


if __name__ == '__main__':
    dotenv.load_dotenv()
    test_login_with_screen_name_and_password()
    test_login_with_cookies(tweet=True)
