import asyncio
import datetime as dt
import decimal
import hashlib
import json
import os
import random
import signal
import sys
import urllib3

import aioredis
import cloudscraper
from environs import Env
from telethon.sync import TelegramClient

import auth


ENV = Env()
REDIS_URL = ENV.str('REDIS_URL')
EMAIL = ENV.str('EMAIL')

TELEGRAM_APP_ID = 5145344
TELEGRAM_APP_TOKEN = '1a822dccf4c1fe151eceba3cec24958f'
TELEGRAM_BOT_TOKEN = '5600428438:AAFgSPZWK18FSmzMhAHRoeOBhhiy967hDhU'
TELEGRAM_CHANNEL_ID = -1001807612189

SHOEBOX_TYPES = {
    1: 'Coach',
    2: 'Walker',
    3: 'Hiker',
    4: 'Racer'
}

LOOTBOX_PRICE_GRID = {
    210000: 2500,  # Gen 1-3
    350000: 500,  # Edition 1-2
    410000: 400,  # Edition 3
    490000: 300  # Edition 4
}

async def check_shoeboxes(redis, session, bot, set_aggressive_mode):
    data = {"params":{"skip":0,"sortOrder":"latest","take":10,"network":"avalanche"}}

    def request():
        return session.post('https://prd-api.step.app/market/selling/shoeBoxes', json=data, timeout=5)

    resp = await asyncio.to_thread(request)

    if resp.status_code == 401:
        auth.update_auth(session)
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

    # set_aggressive_mode()

    for item in new_items:
        channel_name = get_shoebox_channel_name(item)
        if channel_name:
            await redis.publish(channel_name, json.dumps(item))

    message = '\n'.join(f'SB {SHOEBOX_TYPES[i["staticSneakerTypeId"]]} {decimal.Decimal(i["priceFitfi"])}FI #{i["networkTokenId"]}' for i in new_items)
    await bot.send_message(TELEGRAM_CHANNEL_ID, f'{message}')


async def check_lootboxes(redis, session, bot, set_aggressive_mode):
    data = {"params":{"skip":0,"force":True,"sortOrder":"latest","take":10,"network":"avalanche"}}

    def request():
        return session.post('https://prd-api.step.app/market/selling/lootBoxes', json=data, timeout=5)

    resp = await asyncio.to_thread(request)

    if resp.status_code == 401:
        auth.update_auth(session)
        return

    try:
        resp.raise_for_status()
        items = resp.json()['result']['items']
    except Exception:
        print(resp.text)
        raise

    new_items = []

    for item in items:
        exists = await redis.exists(f'lootbox:{item["sellingId"]}')

        if exists:
            print('In cache', item)
        else:
            await redis.set(f'lootbox:{item["sellingId"]}', json.dumps(item))
            new_items.append(item)

    new_items.sort(key=lambda x: x['priceFitfi'])

    def is_buyable(item):
        for max_token_id in sorted(LOOTBOX_PRICE_GRID.keys()):
            if item['networkTokenId'] < max_token_id and item['priceFitfi'] <= LOOTBOX_PRICE_GRID[max_token_id]:
                return True

        return False

    for item in filter(is_buyable, new_items):
        item['lootbox'] = True
        await redis.publish('lootboxes', json.dumps(item))

    def is_monitored(item):
        return item['priceFitfi'] <= 3000 and item['networkTokenId'] < sorted(LOOTBOX_PRICE_GRID.keys())[-1]

    def emoji(item):
        return ' \U0001F60D' if is_buyable(item) else ''

    monitored_items = list(filter(is_monitored, new_items))
    message = '\n'.join(f'LB {decimal.Decimal(i["priceFitfi"])}FI #{i["networkTokenId"]}{emoji(i)}' for i in monitored_items)

    if message:
        await bot.send_message(TELEGRAM_CHANNEL_ID, f'{message}')


def get_shoebox_channel_name(item):
    """
    1 - Coach
    2 - Walker
    3 - Hiker
    4 - Racer
    """
    if item['priceFitfi'] <= 4000:
        return 'shoeboxes:any'

    # TODO: limit by some max price
    # if item['staticShoeBoxRarityId'] > 1:
    #     return 'shoeboxes:any'

    if item['priceFitfi'] > ENV.int(f'MAX_PRICE_{item["staticSneakerTypeId"]}', 0):
        return None

    return f'shoeboxes:{item["staticSneakerTypeId"]}'


async def main():
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    telegram_dir = os.path.join(os.path.dirname(__file__), '..', 'telegram')
    if not os.path.exists(telegram_dir):
        os.makedirs(telegram_dir)

    bot_session = os.path.join(telegram_dir, f'bot-watcher')
    client = TelegramClient(bot_session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
    bot = await client.start(bot_token=TELEGRAM_BOT_TOKEN)
    aggressive_mode = asyncio.Event()
    unset_aggresive_mode_tasks = []

    def set_aggressive_mode():
        aggressive_mode.set()

        if unset_aggresive_mode_tasks:
            unset_aggresive_mode_tasks[0].cancel()
            unset_aggresive_mode_tasks.clear()

        unset_aggresive_mode_tasks.append(asyncio.create_task(unset_aggresive_mode()))

    async def unset_aggresive_mode():
        await asyncio.sleep(60)
        aggressive_mode.clear()

    session = cloudscraper.create_scraper(browser={
        'browser': 'chrome',
        'platform': 'darwin',
        'mobile': False
    })

    data = {'params': {'deviceId': hashlib.md5(EMAIL.encode()).hexdigest()}}
    resp = session.post('https://prd-api.step.app/analytics/seenLogInView', json=data)

    if resp.status_code == 403:
        await bot.send_message(TELEGRAM_CHANNEL_ID, 'Forbidden')

    resp.raise_for_status()
    auth.set_auth(session)

    print(f'Watcher started for {EMAIL}')

    async def check_shoeboxes_loop():
        while True:
            try:
                await check_shoeboxes(redis, session, bot, set_aggressive_mode)
            except Exception as e:
                print('check_shoeboxes error', e)
                break

            if aggressive_mode.is_set():
                print(f'--- {dt.datetime.now()} aggressive mode')
                await asyncio.sleep(0.4)
            else:
                print(f'--- {dt.datetime.now()} calm mode')
                await asyncio.sleep(random.randint(6, 8) / 10)

    async def check_lootboxes_loop():
        while True:
            try:
                await check_lootboxes(redis, session, bot, set_aggressive_mode)
            except Exception as e:
                print('check_lootboxes error', e)
                break

            if aggressive_mode.is_set():
                print(f'--- {dt.datetime.now()} aggressive mode')
                await asyncio.sleep(0.4)
            else:
                print(f'--- {dt.datetime.now()} calm mode')
                await asyncio.sleep(random.randint(6, 8) / 10)

    tasks = [
        asyncio.create_task(check_shoeboxes_loop()),
        asyncio.create_task(check_lootboxes_loop())
    ]

    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
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
