import datetime as dt
import json
import os
from tarfile import ENCODING
import time

import jwt
import requests
from environs import Env
from telethon.sync import TelegramClient

ENV = Env()

TELEGRAM_APP_ID = 5145344
TELEGRAM_APP_TOKEN = '1a822dccf4c1fe151eceba3cec24958f'
TELEGRAM_BOT_TOKEN = '5600428438:AAFgSPZWK18FSmzMhAHRoeOBhhiy967hDhU'
TELEGRAM_CHANNEL_ID = -1001807612189


def check():
    headers = {
        'Authorization': f'Bearer {get_token()}',
        'User-Agent': 'stepapp/1.0 (com.step.stepapp-ios; build:25; iOS 15.7.0) Alamofire/5.6.1',
        'Accept-Encoding': 'br;q=1.0, gzip;q=0.9, deflate;q=0.8',
    }

    data = {"params":{"skip":0,"sortOrder":"latest","take":10,"network":"avalanche"}}
    resp = requests.post('https://prd-api.step.app/market/selling/shoeBoxes', headers=headers, json=data, verify=False, timeout=5)

    if resp.status_code == 401:
        get_new_token()
        return

    try:
        resp.raise_for_status()
        items = resp.json()['result']['items']
    except Exception:
        print(resp.text)
        raise

    new_items = []

    for item in items:
        if str(item['sellingId']) in _CACHE:
            print('In cache', item)
        else:
            new_items.append(item)

    if new_items:
        new_items.sort(key=lambda x: x['priceFitfi'])
        cache(new_items)
        buy(new_items)
        push(new_items)


def get_token():
    if not os.path.exists('auth.json'):
        return get_new_token()

    with open('auth.json', 'r') as f:
        auth = json.load(f)
        acc_token, rfr_token = auth['access'], auth['refresh']

    token_data = jwt.decode(acc_token, algorithms=['HS256'], options={'verify_signature': False})
    exp = dt.datetime.fromtimestamp(token_data['Exp'])

    if dt.datetime.now() + dt.timedelta(seconds=600) < exp:
        return acc_token
    else:
        return get_new_token()


def get_new_token():
    headers = {
        'User-Agent': 'stepapp/1.0 (com.step.stepapp-ios; build:25; iOS 15.7.0) Alamofire/5.6.1',
        'Accept-Encoding': 'br;q=1.0, gzip;q=0.9, deflate;q=0.8',
    }
    data = {'params':{'email': ENV.str('EMAIL'), 'password': ENV.str('PASSWORD')}}
    resp = requests.post('https://prd-api.step.app/auth/auth/loginWithPassword/', headers=headers, json=data, verify=False, timeout=5)

    try:
        resp.raise_for_status()
        acc_token = resp.json()['result']['accessToken']
        rfr_token = resp.json()['result']['refreshToken']
    except Exception:
        print(resp.text)
        raise

    with open('auth.json', 'w') as f:
        json.dump({'access': acc_token, 'refresh': rfr_token}, f)

    print('Auth success for', ENV.str('EMAIL'))
    print(acc_token)
    print(rfr_token)

    return acc_token


def cache(items):
    global _CACHE

    for item in items:
        _CACHE[str(item['sellingId'])] = item

    with open('cache.json', 'w') as f:
        json.dump(_CACHE, f)


def buy(items):
    for item in items:
        if item['priceFitfi'] < 8000:
            headers = {
                'Authorization': f'Bearer {get_token()}',
                'User-Agent': 'stepapp/1.0 (com.step.stepapp-ios; build:25; iOS 15.7.0) Alamofire/5.6.1',
                'Accept-Encoding': 'br;q=1.0, gzip;q=0.9, deflate;q=0.8',
            }
            data = {'params':{'sellingId': item['sellingId']}}
            resp = requests.post('https://prd-api.step.app/game/1/market/buyShoeBox', headers=headers, json=data, verify=False)
            print('Buy')
            print(item)
            print(resp.status_code)
            print(resp.text)
            print('---')


def push(items):
    with _provide_bot():
        message = '\n'.join(f'{i["priceFitfi"]} FI' for i in items)
        _BOT.send_message(TELEGRAM_CHANNEL_ID, f'New shoeboxes:\n{message}')


def main():
    global _CACHE

    if os.path.exists('auth.json'):
        os.remove('auth.json')

    with open('cache.json', 'r') as f:
        _CACHE = json.load(f)

    while True:
        try:
            check()
        except Exception as e:
            print(e)
            break

        time.sleep(0.5)


_CACHE = {}
_BOT = None


def _provide_bot():
    global _BOT

    if _BOT is None:
        session = os.path.join(os.path.dirname(__file__), 'bot')
        client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
        _BOT = client.start(bot_token=TELEGRAM_BOT_TOKEN)

    return _BOT


if __name__ == '__main__':
    main()
