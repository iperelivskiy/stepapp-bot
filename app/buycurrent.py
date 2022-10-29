import asyncio
import json
import urllib3

import aioredis
import requests
from environs import Env

import auth


ENV = Env()
REDIS_URL = ENV.str('REDIS_URL')
MAX_PRICE = ENV.int('MAX_PRICE')


async def check_shoeboxes(redis):
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

    if not items:
        return

    for item in items:
        await redis.set(f'shoebox:{item["sellingId"]}', json.dumps(item))

    items.sort(key=lambda x: x['priceFitfi'])

    for item in filter(is_allowed, items):
        print(item)
        await redis.publish('shoeboxes', json.dumps(item))


def is_allowed(item):
    """
    1 - Coach
    2 - Walker
    3 - Hiker
    4 - Racer
    """
    if item['priceFitfi'] > MAX_PRICE:
        return False

    if item['staticSneakerTypeId'] in [4]:
        return False

    return True


async def main():
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await check_shoeboxes(redis)
    await redis.close()


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    asyncio.run(main())
