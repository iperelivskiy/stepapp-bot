import asyncio
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

TELEGRAM_APP_ID = 5145344
TELEGRAM_APP_TOKEN = '1a822dccf4c1fe151eceba3cec24958f'
TELEGRAM_BOT_TOKEN = '5600428438:AAFgSPZWK18FSmzMhAHRoeOBhhiy967hDhU'
TELEGRAM_CHANNEL_ID = -1001807612189


async def check_shoeboxes(bot, redis):
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

    for item in new_items:
        await redis.publish('shoeboxes', json.dumps(item))

    message = '\n'.join(f'{i["priceFitfi"]} FI' for i in new_items)
    await bot.send_message(TELEGRAM_CHANNEL_ID, f'New shoeboxes:\n{message}')


async def check_sellings(bot, cur_sellings):
    resp = requests.post('https://prd-api.step.app/game/1/user/getCurrent', headers=auth.get_headers(), verify=False, timeout=2)

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


async def main():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    telegram_dir = os.path.join(os.path.dirname(__file__), '..', 'telegram')
    if not os.path.exists(telegram_dir):
        os.makedirs(telegram_dir)

    session = os.path.join(telegram_dir, f'bot-watcher')
    client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
    bot = await client.start(bot_token=TELEGRAM_BOT_TOKEN)

    async def check_sellings_loop(bot):
        current_sellings = None

        while True:
            try:
                current_sellings = await check_sellings(bot, current_sellings)
            except Exception as e:
                print('check_sellings', e)

            await asyncio.sleep(60)

    task = asyncio.create_task(check_sellings_loop(bot))

    while True:
        try:
            await check_shoeboxes(bot, redis)
        except Exception as e:
            print('check_shoeboxes', e)
            break

        time.sleep(random.randint(6, 12) / 10)

    task.cancel()
    await bot.disconnect()
    await redis.close()


if __name__ == '__main__':
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
