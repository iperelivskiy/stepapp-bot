import asyncio
import datetime as dt
import json
import os
import random
import signal
import sys
import time
import urllib3

import aioredis
import requests
from environs import Env
from telethon.sync import TelegramClient

import auth


ENV = Env()
REDIS_URL = ENV.str('REDIS_URL')
EMAIL = ENV.str('EMAIL')
MAX_PRICE = ENV.int('MAX_PRICE')

TELEGRAM_APP_ID = 5145344
TELEGRAM_APP_TOKEN = '1a822dccf4c1fe151eceba3cec24958f'
TELEGRAM_BOT_TOKEN = '5600428438:AAFgSPZWK18FSmzMhAHRoeOBhhiy967hDhU'
TELEGRAM_CHANNEL_ID = -1001807612189

TYPES = {
    1: 'Coach',
    2: 'Walker',
    3: 'Hiker',
    4: 'Racer'
}


async def check_shoeboxes(redis, bot, set_aggressive_mode):
    data = {"params":{"skip":0,"sortOrder":"latest","take":10,"network":"avalanche"}}
    resp = requests.post('https://prd-api.step.app/market/selling/shoeBoxes', headers=auth.get_headers(), json=data, verify=False, timeout=2)

    if resp.status_code == 401:
        auth.get_new_token()
        return

    try:
        resp.raise_for_status()
        items = resp.json()['result']['items']
    except Exception:
        print(resp.text)
        raise

    new_items = []

    for item in items:
        exists = await redis.exists(f'shoebox:{item["sellingId"]}')

        if exists:
            print('In cache', item)
        else:
            await redis.set(f'shoebox:{item["sellingId"]}', json.dumps(item))
            new_items.append(item)

    if not new_items:
        return

    new_items.sort(key=lambda x: x['priceFitfi'])

    if new_items[0]['priceFitfi'] <= MAX_PRICE:
        set_aggressive_mode()

    for item in filter(is_allowed, new_items):
        await redis.publish('shoeboxes', json.dumps(item))

    message = '\n'.join(f'{i["priceFitfi"]}FI {TYPES[i["staticSneakerTypeId"]]}' for i in new_items)
    await bot.send_message(TELEGRAM_CHANNEL_ID, f'New shoeboxes:\n{message}')


def is_allowed(item):
    """
    1 - Coach
    2 - Walker
    3 - Hiker
    4 - Racer
    """
    if item['priceFitfi'] > MAX_PRICE:
        return False

    # if item['staticSneakerTypeId'] in [2, 4] and item['staticShoeBoxRarityId'] == 1 and item['priceFitfi'] > 4000:
    #     # Aint buying common walkers and racers with price over 4000 FI
    #     return False

    if item['staticSneakerTypeId'] not in [1]:
        return False

    return True


async def main():
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    telegram_dir = os.path.join(os.path.dirname(__file__), '..', 'telegram')
    if not os.path.exists(telegram_dir):
        os.makedirs(telegram_dir)

    session = os.path.join(telegram_dir, f'bot-watcher')
    client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
    bot = await client.start(bot_token=TELEGRAM_BOT_TOKEN)
    aggressive_mode = asyncio.Event()

    def set_aggressive_mode():
        aggressive_mode.set()
        asyncio.create_task(unset_aggresive_mode_later())

    async def unset_aggresive_mode_later():
        await asyncio.sleep(15 * 60)
        aggressive_mode.clear()

    print(f'Watcher started for {EMAIL}')

    while True:
        try:
            await check_shoeboxes(redis, bot, set_aggressive_mode)
        except Exception as e:
            print('check_shoeboxes', e)
            break

        if aggressive_mode.is_set():
            print(f'--- {dt.datetime.now()} aggressive mode')
            await asyncio.sleep(0.4)
        else:
            print(f'--- {dt.datetime.now()} calm mode')
            await asyncio.sleep(random.randint(20, 50) / 10)

    await bot.disconnect()
    await redis.close()


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def handle_sigterm(*args):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, handle_sigterm)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
