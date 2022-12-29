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
TELEGRAM_MARKET_CHANNEL_ID = -1001807612189
TELEGRAM_STATE_CHANNEL_ID = -1001696370716

SHOEBOX_TYPES = {
    1: 'Coach',
    2: 'Walker',
    3: 'Hiker',
    4: 'Racer'
}

LOOTBOX_PRICE_GRID = {
    150000: 3000,  # Gen 1-2
    210000: 2000,  # Gen 3
    410000: 600,  # Ed 1-3
    490000: 450,  # Ed 4
    550000: 300,  # Ed 5
}


async def main():
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    telegram_dir = os.path.join(os.path.dirname(__file__), '..', 'telegram')
    if not os.path.exists(telegram_dir):
        os.makedirs(telegram_dir)

    tg_session = os.path.join(telegram_dir, f'bot-watcher')
    tg_client = TelegramClient(tg_session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
    tg = await tg_client.start(bot_token=TELEGRAM_BOT_TOKEN)
    session = cloudscraper.create_scraper(browser={
        'browser': 'chrome',
        'platform': 'darwin',
        'mobile': False
    })

    data = {'params': {'deviceId': hashlib.md5(EMAIL.encode()).hexdigest()}}
    resp = session.post('https://prd-api.step.app/analytics/seenLogInView', json=data)

    if resp.status_code == 403:
        await tg.send_message(TELEGRAM_STATE_CHANNEL_ID, 'Forbidden')

    resp.raise_for_status()
    auth.set_auth(session)

    tasks = [
        asyncio.create_task(check_shoeboxes_loop(redis, session, tg)),
        asyncio.create_task(check_lootboxes_loop(redis, session, tg))
    ]

    print(f'Watcher started for {EMAIL}')

    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    await tg.disconnect()
    await redis.close()


async def check_shoeboxes_loop(redis, session, tg):
    aggressive_mode, set_aggressive_mode = _setup_aggressive_mode()

    while True:
        try:
            await check_shoeboxes(redis, session, tg, set_aggressive_mode)
        except Exception as e:
            print('check_shoeboxes error', e)
            break

        if aggressive_mode.is_set():
            print(f'--- {dt.datetime.now()} aggressive mode')
            await asyncio.sleep(0.25)
        else:
            print(f'--- {dt.datetime.now()} calm mode')
            await asyncio.sleep(random.randint(10, 20) / 10)


async def check_lootboxes_loop(redis, session, tg):
    aggressive_mode, set_aggressive_mode = _setup_aggressive_mode()

    while True:
        try:
            await check_lootboxes(redis, session, tg, set_aggressive_mode)
        except Exception as e:
            print('check_lootboxes error', e)
            break

        if aggressive_mode.is_set():
            print(f'--- {dt.datetime.now()} aggressive mode')
            await asyncio.sleep(0.25)
        else:
            print(f'--- {dt.datetime.now()} calm mode')
            await asyncio.sleep(random.randint(5, 10) / 10)


async def check_shoeboxes(redis, session, tg, set_aggressive_mode):
    data = {"params":{"skip":0,"sortOrder":"latest","take":10,"network":"avalanche"}}

    def request():
        return session.post('https://prd-api.step.app/market/selling/shoeBoxes', json=data, timeout=5)

    resp = await asyncio.to_thread(request)

    if resp.status_code == 401:
        auth.update_auth(session)
        resp = await asyncio.to_thread(request)

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

    def get_channel_name(item):
        """
        1 - Coach
        2 - Walker
        3 - Hiker
        4 - Racer
        """
        if item['priceFitfi'] <= 3000:
            # Super price
            return 'shoeboxes:any'

        # TODO: limit by some max price
        # if item['staticShoeBoxRarityId'] > 1:
        #     return 'shoeboxes:any'

        if item['priceFitfi'] > ENV.int(f'MAX_PRICE_{item["staticSneakerTypeId"]}', 0):
            return None

        return f'shoeboxes:{item["staticSneakerTypeId"]}'

    def is_buyable(item):
        return bool(get_channel_name(item))

    new_items.sort(key=lambda x: x['priceFitfi'])
    buyable_items = list(filter(is_buyable, new_items))

    if buyable_items:
        set_aggressive_mode()

    for item, channel_name in zip(buyable_items, map(get_channel_name, buyable_items)):
        await redis.publish(channel_name, json.dumps(item))

    message = '\n'.join(
        f'SB {SHOEBOX_TYPES[i["staticSneakerTypeId"]]} {decimal.Decimal(i["priceFitfi"])}FI #{i["networkTokenId"]}'
        for i in new_items
    )

    if message:
        asyncio.create_task(tg.send_message(TELEGRAM_MARKET_CHANNEL_ID, f'{message}'))


async def check_lootboxes(redis, session, tg, set_aggressive_mode):
    data = {"params":{"skip":0,"force":True,"sortOrder":"latest","take":10,"network":"avalanche"}}

    def request():
        return session.post('https://prd-api.step.app/market/selling/lootBoxes', json=data, timeout=5)

    resp = await asyncio.to_thread(request)

    if resp.status_code == 401:
        auth.update_auth(session)
        resp = await asyncio.to_thread(request)

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

    def is_buyable(item):
        if item['priceFitfi'] <= 100:
            # Super price
            return True

        for max_token_id in sorted(LOOTBOX_PRICE_GRID.keys()):
            if item['networkTokenId'] < max_token_id and item['priceFitfi'] <= LOOTBOX_PRICE_GRID[max_token_id]:
                return True

        return False

    def emoji(item):
        return ' \U0001F60D' if is_buyable(item) else ''

    new_items.sort(key=lambda x: x['priceFitfi'])
    buyable_items = list(filter(is_buyable, new_items))

    if buyable_items:
        set_aggressive_mode()

    for item in buyable_items:
        item['lootbox'] = True
        await redis.publish('lootboxes', json.dumps(item))

    message = '\n'.join(
        f'LB {decimal.Decimal(i["priceFitfi"])}FI #{i["networkTokenId"]}{emoji(i)}'
        for i in buyable_items
    )

    if message:
        asyncio.create_task(tg.send_message(TELEGRAM_STATE_CHANNEL_ID, f'{message}'))

    def is_monitored(item):
        return item['priceFitfi'] <= 3000 and item['networkTokenId'] < sorted(LOOTBOX_PRICE_GRID.keys())[-1]

    message = '\n'.join(
        f'LB {decimal.Decimal(i["priceFitfi"])}FI #{i["networkTokenId"]}{emoji(i)}'
        for i in filter(is_monitored, new_items)
    )

    if message:
        asyncio.create_task(tg.send_message(TELEGRAM_MARKET_CHANNEL_ID, f'{message}'))


def _setup_aggressive_mode():
    aggressive_mode = asyncio.Event()
    unset_aggresive_mode_tasks = []

    def set_aggressive_mode():
        for task in unset_aggresive_mode_tasks:
            task.cancel()

        aggressive_mode.set()
        unset_aggresive_mode_tasks[:] = [asyncio.create_task(unset_aggresive_mode())]

    async def unset_aggresive_mode():
        await asyncio.sleep(60)
        aggressive_mode.clear()

    return aggressive_mode, set_aggressive_mode


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
