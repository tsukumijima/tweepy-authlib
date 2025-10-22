# 以下の twikit のフォークで実装されていたモジュールをほぼそのまま移植した
# ref: https://github.com/keatonLiu/twikit/blob/main/twikit/xpff/xpffGenerator.py
# 元のソースコードはおそらく以下が出典
# ref: https://github.com/dsekz/twitter-x-xp-forwarded-for-header

import binascii
import hashlib
import json
import time

from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes


class XPFFHeaderGenerator:
    def __init__(
        self,
        user_agent: str,
        base_key: str = '0e6be1f1e21ffc33590b888fd4dc81b19713e570e805d4e5df80a493c9571a05',
    ):
        self.base_key = base_key
        self.user_agent = user_agent

    def _derive_xpff_key(self, guest_id: str) -> bytes:
        combined = self.base_key + guest_id
        return hashlib.sha256(combined.encode()).digest()

    def generate_xpff(self, plaintext: str, guest_id: str) -> str:
        key = self._derive_xpff_key(guest_id)
        nonce = get_random_bytes(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode())
        return binascii.hexlify(nonce + ciphertext + tag).decode()

    def decode_xpff(self, hex_string: str, guest_id: str) -> str:
        key = self._derive_xpff_key(guest_id)
        raw = binascii.unhexlify(hex_string)
        nonce = raw[:12]
        ciphertext = raw[12:-16]
        tag = raw[-16:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return plaintext.decode()

    def generate(self, guest_id: str) -> str:
        xpff_plain = {
            'navigator_properties': {'hasBeenActive': 'true', 'userAgent': self.user_agent, 'webdriver': 'false'},
            'created_at': int(time.time() * 1000),
        }
        xpff_plain = json.dumps(xpff_plain, ensure_ascii=False, separators=(',', ':'))
        return self.generate_xpff(xpff_plain, guest_id)


if __name__ == '__main__':
    from tweepy_authlib.CookieSessionUserHandler import CookieSessionUserHandler

    # ブラウザ上の実際の guest_id と X-XP-Forwarded-For ヘッダーの値を設定して復号できること、
    # また復号した平文に書かれている JSON の構造が一致する状態が続く限りは、まだこのロジックが有効であると考えられる
    xpff = XPFFHeaderGenerator(user_agent=CookieSessionUserHandler.USER_AGENT)
    guest_id = 'v1%3A175609135281804827'
    encrypted = xpff.generate(guest_id)
    print('Encrypted:', encrypted)
    decrypted = xpff.decode_xpff(encrypted, guest_id)
    print('Decrypted:', decrypted)
