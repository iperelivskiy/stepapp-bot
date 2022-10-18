import asyncio
import datetime as dt
import json
import os
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

    for item in new_items:
        if item['priceFitfi'] <= ENV.int('MAX_PRICE'):
            data = {'params':{'sellingId': item['sellingId']}}
            resp = requests.post('https://prd-api.step.app/game/1/market/buyShoeBox', headers=get_headers(), json=data, verify=False)
            print('Buy')
            print(item)
            print(resp.status_code)
            print(resp.text)
            print('---')

    message = '\n'.join(f'{i["priceFitfi"]} FI' for i in new_items)
    bot.send_message(TELEGRAM_CHANNEL_ID, f'New shoeboxes:\n{message}')


async def check_sellings(bot, current_sellings):
    try:
        resp = requests.post('https://prd-api.step.app/game/1/user/getCurrent', headers=get_headers(), verify=False)
        sellings = len(resp.json()['result']['changes']['dynUsers']['updated'][0]['sneakerSellings']['updated'])
    except Exception:
        raise

    if current_sellings is not None and current_sellings > sellings:
        await bot.send_message(TELEGRAM_CHANNEL_ID, f'Current sellings ({ENV.str("EMAIL")}): {sellings}')


def get_headers(auth=True):
    headers = {
        'User-Agent': 'stepapp/1.0 (com.step.stepapp-ios; build:25; iOS 15.7.0) Alamofire/5.6.1',
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
        acc_token, rfr_token = auth['access'], auth['refresh']

    token_data = jwt.decode(acc_token, algorithms=['HS256'], options={'verify_signature': False})
    exp = dt.datetime.fromtimestamp(token_data['Exp'])

    if dt.datetime.now() + dt.timedelta(seconds=600) < exp:
        return acc_token
    else:
        return get_new_token()


def get_new_token():
    data = {'params':{'email': ENV.str('EMAIL'), 'password': ENV.str('PASSWORD')}}
    resp = requests.post('https://prd-api.step.app/auth/auth/loginWithPassword/', headers=get_headers(False), json=data, verify=False, timeout=2)

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


def main():
    if os.path.exists('auth.json'):
        os.remove('auth.json')

    async def check_loop():
        session = os.path.join(os.path.dirname(__file__), 'bot-1')
        client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
        bot = await client.start(bot_token=TELEGRAM_BOT_TOKEN)
        current_sellings = None

        while True:
            try:
                current_sellings = await check_sellings(bot, current_sellings)
            except Exception as e:
                print(e)

            await asyncio.sleep(60)

    loop = asyncio.new_event_loop()
    loop.create_task(check_loop())
    thread = threading.Thread(target=loop.run_forever)
    thread.start()
    time.sleep(1)  # Sleep to have enough time to get current auth in thread

    session = os.path.join(os.path.dirname(__file__), 'bot')
    client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
    bot = client.start(bot_token=TELEGRAM_BOT_TOKEN)

    if os.path.exists('cache.json'):
        with open('cache.json', 'r') as f:
            cache = json.load(f)
    else:
        cache = {'shoeboxes': {}}

    while True:
        try:
            check_shoeboxes(bot, cache['shoeboxes'])
        except Exception as e:
            print(e)
            break

        with open('cache.json', 'w') as f:
            json.dump(cache, f)

        time.sleep(0.6)


if __name__ == '__main__':
    main()
