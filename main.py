import asyncio
import datetime as dt
import json
import hashlib
import os
import random
import signal
import sys
import threading
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

EMAIL = ENV.str('EMAIL')
PASSWORD = ENV.str('PASSWORD')
MAX_PRICE = ENV.int('MAX_PRICE')
NEW_ITEMS_PUSH = ENV.bool('NEW_ITEMS_PUSH', False)


def check_shoeboxes(bot, cur_items):
    data = {"params":{"skip":0,"sortOrder":"latest","take":10,"network":"avalanche"}}
    resp = requests.post('https://prd-api.step.app/market/selling/shoeBoxes', headers=get_headers(), json=data, verify=False, timeout=2)

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
        if str(item['sellingId']) in cur_items:
            print('In cache', item)
        else:
            new_items.append(item)
            cur_items[str(item['sellingId'])] = item

    if not new_items:
        return

    new_items.sort(key=lambda x: x['priceFitfi'])

    def is_allowed(item):
        """
        1 - Coach
        2 - Walker
        3 - Hiker
        4 - Racer
        """
        if item['priceFitfi'] > MAX_PRICE:
            return False

        if item['staticSneakerTypeId'] == 4 and item['staticShoeBoxRarityId'] == 1 and item['priceFitfi'] > 4000:
            # Aint buying common racer with price over 4000 FI
            return False

        return True

    for item in new_items:
        if not is_allowed(item):
            continue

        data = {'params': {'sellingId': item['sellingId']}}

        try:
            resp = requests.post('https://prd-api.step.app/game/1/market/buyShoeBox', headers=get_headers(), json=data, verify=False, timeout=2)
            resp.raise_for_status()
        except Exception as e:
            print(e)
        else:
            print('Buy')
            print(item)
            print(resp.status_code)
            print(resp.text)
            print('---')

    if NEW_ITEMS_PUSH:
        message = '\n'.join(f'{i["priceFitfi"]} FI' for i in new_items)
        bot.send_message(TELEGRAM_CHANNEL_ID, f'New shoeboxes:\n{message}')


async def check_sellings(bot, cur_sellings):
    resp = requests.post('https://prd-api.step.app/game/1/user/getCurrent', headers=get_headers(), verify=False)

    try:
        resp.raise_for_status()
        sellings = len(resp.json()['result']['changes']['dynUsers']['updated'][0]['sneakerSellings']['updated'])
    except TypeError:
        # No shoes left for sale
        sellings = 0
    except Exception:
        print(resp.text)
        raise

    if cur_sellings is not None and cur_sellings > sellings:
        await bot.send_message(TELEGRAM_CHANNEL_ID, f'Current sellings ({EMAIL}): {sellings}')

    return sellings


def get_headers(auth=True):
    headers = {
        'User-Agent': 'stepapp/1.0 (com.step.stepapp-ios; build:30; iOS 15.7.0) Alamofire/5.6.1',
        'Accept-Encoding': 'br;q=1.0, gzip;q=0.9, deflate;q=0.8',
        'Accept-Language': 'en-KZ;q=1.0, ru-KZ;q=0.9'
    }

    if auth:
        headers['Authorization'] = f'Bearer {get_token()}'

    return headers


def get_token():
    if not os.path.exists('auth.json'):
        return get_new_token()

    with open('auth.json', 'r') as f:
        auth = json.load(f)
        token = auth.get(EMAIL)
        if not token:
            return get_new_token()

    token_data = jwt.decode(token, algorithms=['HS256'], options={'verify_signature': False})
    exp = dt.datetime.fromtimestamp(token_data['Exp'])

    if dt.datetime.now() + dt.timedelta(seconds=600) < exp:
        return token
    else:
        return get_new_token()


def get_new_token():
    data = {'params':{'email': EMAIL, 'password': PASSWORD}}
    resp = requests.post('https://prd-api.step.app/auth/auth/loginWithPassword/', headers=get_headers(False), json=data, verify=False)

    try:
        resp.raise_for_status()
        token = resp.json()['result']['accessToken']
    except Exception:
        print(resp.text)
        raise

    if os.path.exists('auth.json'):
        with open('auth.json', 'r') as f:
            auth = json.load(f)
    else:
        auth = {}

    auth[EMAIL] = token

    with open('auth.json', 'w') as f:
        json.dump(auth, f)

    print('Auth success for', EMAIL)
    print(token)

    return token


def main():
    def handle_sigterm(*args):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, handle_sigterm)
    stop_event = threading.Event()
    telegram_dir = os.path.join(os.path.dirname(__file__), 'telegram')

    if not os.path.exists(telegram_dir):
        os.makedirs(telegram_dir)

    async def check_loop(bot):
        current_sellings = None

        while True:
            try:
                current_sellings = await check_sellings(bot, current_sellings)
            except Exception as e:
                print(e)

            await asyncio.sleep(60)

    def run_check_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def check_loop_stop():
            session = os.path.join(telegram_dir, f'bot-{hashlib.md5(EMAIL.encode()).hexdigest()}-1')
            client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
            bot = await client.start(bot_token=TELEGRAM_BOT_TOKEN)
            task = loop.create_task(check_loop(bot))

            while True:
                if stop_event.is_set():
                    break

                await asyncio.sleep(1)

            task.cancel()
            await client.disconnect()

        loop.run_until_complete(check_loop_stop())

    thread = threading.Thread(target=run_check_loop)
    thread.start()
    time.sleep(1)  # Sleep to have enough time to get current auth in thread

    session = os.path.join(telegram_dir, f'bot-{hashlib.md5(EMAIL.encode()).hexdigest()}')
    client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
    bot = client.start(bot_token=TELEGRAM_BOT_TOKEN)

    if os.path.exists('cache.json'):
        with open('cache.json', 'r') as f:
            cache = json.load(f)
    else:
        cache = {EMAIL: {'shoeboxes': {}}}

    while True:
        try:
            check_shoeboxes(bot, cache[EMAIL]['shoeboxes'])
        except Exception as e:
            stop_event.set()
            print(e)
            break

        with open('cache.json', 'w') as f:
            json.dump(cache, f)

        time.sleep(random.randint(6, 16) / 10)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
