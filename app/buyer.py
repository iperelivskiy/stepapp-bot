import asyncio
import datetime as dt
import json
import os
import random
import signal
import sys
import urllib3

import aioredis
import async_timeout
import requests
from environs import Env

import auth


ENV = Env()
REDIS_URL = ENV.str('REDIS_URL')
MAX_PRICE = ENV.int('MAX_PRICE')
EMAIL = ENV.str('EMAIL')


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


def buy(item):
    print(f'{EMAIL} BUYING', item)
    data = {'params': {'sellingId': item['sellingId']}}

    try:
        resp = requests.post('https://prd-api.step.app/game/1/market/buyShoeBox', headers=auth.get_headers(), json=data, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print(f'{EMAIL} BUYING ERROR', e)
    else:
        print(resp.status_code)
        print(resp.text)

    print('---')


async def reader(channel: aioredis.client.PubSub):
    print(f'{EMAIL} reader started')
    while True:
        try:
            async with async_timeout.timeout(1):
                message = await channel.get_message(ignore_subscribe_messages=True)
                if message is not None:
                    try:
                        item = json.loads(message['data'])
                    except Exception:
                        pass
                    else:
                        if is_allowed(item):
                            asyncio.create_task(asyncio.to_thread(buy, item))
        except asyncio.TimeoutError:
            pass
        finally:
            await asyncio.sleep(0.05)


async def main():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()

    async def check_auth_loop():
        while True:
            try:
                resp = requests.post('https://prd-api.step.app/game/1/user/getCurrent', headers=auth.get_headers(), verify=False, timeout=2)
                if resp.status_code == 401:
                    auth.get_new_token()
            except Exception as e:
                print(e)

            await asyncio.sleep(60 * random.randint(5, 15))

    check_auth_loop_task = asyncio.create_task(check_auth_loop())

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(30)
            print(f'Heartbeat {dt.datetime.now()}')

    heartbeat_loop_task = asyncio.create_task(heartbeat_loop())

    async with pubsub as p:
        await p.subscribe('shoeboxes')
        await reader(p)
        await p.unsubscribe('shoeboxes')

    check_auth_loop_task.cancel()
    heartbeat_loop_task.cancel()
    await pubsub.close()


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
