import asyncio
import hashlib
import json
import urllib3

import aioredis
import cloudscraper
from environs import Env

import auth


ENV = Env()
REDIS_URL = ENV.str('REDIS_URL')
EMAIL = ENV.str('EMAIL')


async def check_shoeboxes(redis, session):
    data = {"params":{"skip":0,"sortOrder":"latest","take":10,"network":"avalanche"}}
    resp = session.post('https://prd-api.step.app/market/selling/shoeBoxes', json=data)

    if resp.status_code == 401:
        auth.update_auth(session)
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

    def is_allowed(item):
        """
        1 - Coach
        2 - Walker
        3 - Hiker
        4 - Racer
        """
        return item['priceFitfi'] <= ENV.int(f'MAX_PRICE_{item["staticSneakerTypeId"]}', 4000)

    for item in filter(is_allowed, items):
        print(item)
        await redis.publish('shoeboxes:any', json.dumps(item))


async def main():
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
    session = cloudscraper.create_scraper(browser={
        'browser': 'chrome',
        'platform': 'darwin',
        'mobile': False
    })
    data = {'params': {'deviceId': hashlib.md5(EMAIL.encode()).hexdigest()}}
    resp = session.post('https://prd-api.step.app/analytics/seenLogInView', json=data)
    resp.raise_for_status()
    auth.set_auth(session)

    await check_shoeboxes(redis, session)
    await redis.close()


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    asyncio.run(main())
