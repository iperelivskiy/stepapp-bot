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
import async_timeout
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
TELEGRAM_STATE_CHANNEL_ID = -1001696370716

ALLOWED_SHOEBOX_TYPES = ENV.list('ALLOWED_SHOEBOXES', [1, 2, 3, 4])


TYPES = {
    1: 'Coach',
    2: 'Walker',
    3: 'Hiker',
    4: 'Racer'
}


async def main():
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()

    telegram_dir = os.path.join(os.path.dirname(__file__), '..', 'telegram')
    if not os.path.exists(telegram_dir):
        os.makedirs(telegram_dir)

    tg_session = os.path.join(telegram_dir, f'bot-{hashlib.md5(EMAIL.encode()).hexdigest()}')
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
    lock = asyncio.Lock()

    async def check_state_loop():
        state = {
            'sellings': None,
            'balance': None
        }

        while True:
            try:
                await check_state(state, session, tg)
            except Exception as e:
                print('Check state error:', e)
            else:
                print(f'--- {dt.datetime.now()}{["", " cooldown"][lock.locked()]}')
                await asyncio.sleep(random.randint(20, 40))

    async def reader_loop():
        channels = [f'shoeboxes:{ast}' for ast in ALLOWED_SHOEBOX_TYPES]
        channels.append('shoeboxes:any')

        if ENV.bool('LOOTBOXES_ALLOWED', False):
            channels.append('lootboxes')

        async with pubsub as p:
            try:
                await p.subscribe(*channels)
                await reader(p, session, tg, lock)
                await p.unsubscribe(*channels)
            except Exception as e:
                print('Reader error:', e)

    tasks = [
        asyncio.create_task(check_state_loop()),
        asyncio.create_task(reader_loop())
    ]

    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    await tg.disconnect()
    await pubsub.close()
    await redis.close()


async def check_state(state, session, tg):
    def request():
        return session.post('https://prd-api.step.app/game/1/user/getCurrent', timeout=5)

    resp = await asyncio.to_thread(request)

    if resp.status_code == 401:
        auth.update_auth(session)
        resp = await asyncio.to_thread(request)

    try:
        resp.raise_for_status()
        data = resp.json()['result']['changes']
    except Exception:
        print(resp.text)
        raise

    sellings = 0

    if data['dynUsers'] and 'updated' in data['dynUsers']:
        sneaker_sellings = data['dynUsers']['updated'][0]['sneakerSellings']
        sellings += len(sneaker_sellings['updated']) if sneaker_sellings else 0
        lootbox_sellings = data['dynUsers']['updated'][0]['lootBoxSellings']
        sellings += len(lootbox_sellings['updated']) if lootbox_sellings else 0

    if data['dynItems'] and 'updated' in data['dynItems']:
        for item in data['dynItems']['updated']:
            if item.get('staticItemId') == 100519998:
                state['balance'] = decimal.Decimal(item['count']) / 1000

    if state['sellings'] is not None and state['sellings'] > sellings:
        asyncio.create_task(
            tg.send_message(TELEGRAM_STATE_CHANNEL_ID, f'{EMAIL}\nCurrent sellings: {sellings}\nCurrent balance: {state["balance"]}')
        )

    state['sellings'] = sellings


async def reader(channel: aioredis.client.PubSub, session, tg, lock):
    print(f'Agent started for {EMAIL}, channels: {list(channel.channels.keys())}')

    async def set_cooldown():
        await lock.acquire()
        asyncio.create_task(unset_cooldown_later())

    async def unset_cooldown_later():
        await asyncio.sleep(10 * 60)
        lock.release()

    while True:
        try:
            async with async_timeout.timeout(1):
                message = await channel.get_message(ignore_subscribe_messages=True)

                if lock.locked():
                    # Cooldown...
                    # TODO: sleep is called?
                    continue

                if message is not None:
                    try:
                        item = json.loads(message['data'])
                    except Exception:
                        pass
                    else:
                        if item.get('lootbox'):
                            asyncio.create_task(buy_lootbox(item, session, tg, set_cooldown))
                        else:
                            asyncio.create_task(buy_shoebox(item, session, tg, set_cooldown))
        except asyncio.TimeoutError:
            pass
        finally:
            await asyncio.sleep(0.01)


async def buy_shoebox(item, session, tg, set_cooldown):

    def request():
        print(f'BUYING shoebox for {EMAIL}', item)
        data = {'params': {'sellingId': item['sellingId']}}
        resp = None

        try:
            resp = session.post('https://prd-api.step.app/game/1/market/buyShoeBox', json=data)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f'BUYING ERROR for {EMAIL}', e)
        finally:
            if resp is not None:
                print(resp.status_code, resp.text)

    success = await asyncio.to_thread(request)

    if success:
        # await set_cooldown()
        asyncio.create_task(
            tg.send_message(TELEGRAM_STATE_CHANNEL_ID, f'{EMAIL}\nBought shoebox {TYPES[item["staticSneakerTypeId"]]} #{item["networkTokenId"]}')
        )
        # cost_prices = {item['networkTokenId']: item['priceFitfi']}
        # asyncio.create_task(open_shoeboxes_and_sell(cost_prices, tg))


async def buy_lootbox(item, session, tg, set_cooldown):

    def request():
        print(f'BUYING lootbox for {EMAIL}', item)
        data = {'params': {'sellingId': item['sellingId']}}
        resp = None

        try:
            resp = session.post('https://prd-api.step.app/game/1/market/buyLootBox', json=data)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f'BUYING ERROR for {EMAIL}', e)
        finally:
            if resp is not None:
                print(resp.status_code, resp.text)

    success = await asyncio.to_thread(request)

    if success:
        asyncio.create_task(
            tg.send_message(TELEGRAM_STATE_CHANNEL_ID, f'{EMAIL}\nBought lootbox #{item["networkTokenId"]}')
        )


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
