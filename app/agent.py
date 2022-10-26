import asyncio
import datetime as dt
import hashlib
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
from telethon.sync import TelegramClient

import auth


ENV = Env()
REDIS_URL = ENV.str('REDIS_URL')
MAX_PRICE = ENV.int('MAX_PRICE')
EMAIL = ENV.str('EMAIL')

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


def is_allowed(item):
    if item['priceFitfi'] > MAX_PRICE:
        return False

    if item['staticSneakerTypeId'] in [2, 4] and item['staticShoeBoxRarityId'] == 1 and item['priceFitfi'] > 4000:
        # Aint buying common walkers and racers with price over 4000 FI
        return False

    return True


async def buy_shoebox(item, bot):

    def request():
        print(f'BUYING for {EMAIL}', item)
        data = {'params': {'sellingId': item['sellingId']}}
        resp = None

        try:
            resp = requests.post('https://prd-api.step.app/game/1/market/buyShoeBox', headers=auth.get_headers(), json=data, verify=False)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f'BUYING ERROR for {EMAIL}', e)
        finally:
            if resp is not None:
                print(resp.status_code, resp.text)

    success = await asyncio.to_thread(request)

    if success:
        await bot.send_message(TELEGRAM_CHANNEL_ID, f'{EMAIL}\nBought shoebox {TYPES[item["staticSneakerTypeId"]]}')
        # cost_prices = {item['networkTokenId']: item['priceFitfi']}
        # asyncio.create_task(open_shoeboxes_and_sell(cost_prices, bot))


async def open_shoeboxes_and_sell(cost_prices, bot):
    resp = None

    try:
        resp = requests.post('https://prd-api.step.app/game/1/user/getCurrent', headers=auth.get_headers(), verify=False)
        resp.raise_for_status()
        items = list(resp.json()['result']['changes']['dynItems']['updated'])
    except (TypeError, KeyError):
        # No shoeboxes to open
        return
    except Exception:
        raise
    finally:
        if resp is not None:
            print(resp.status_code, 'open_shoeboxes_and_sell', resp.text, '\n---')

    for item in items:
        # cost_prices[item['shoeBox']['networkTokenId']] = 8000

        if item.get('shoeBox') and item['shoeBox']['networkTokenId'] in cost_prices:
            cost_price = cost_prices[item['shoeBox']['networkTokenId']]
            assert cost_price >= 8000
            sneaker = await open_shoebox(item)
            await sell_sneaker(sneaker, cost_price, bot)


async def open_shoebox(shoebox):
    data = {'params': {'shoeBoxDynItemId': shoebox['id']}}
    resp = None

    try:
        resp = requests.post('https://prd-api.step.app/game/1/shoeBox/seen', headers=auth.get_headers(), json=data, verify=False)
        resp.raise_for_status()
        resp = requests.post('https://prd-api.step.app/game/1/shoeBox/open', headers=auth.get_headers(), json=data, verify=False)
        resp.raise_for_status()
        sneaker = resp.json()['result']['changes']['dynSneakers']['updated'][0]
        assert sneaker['networkTokenId'] == shoebox['shoeBox']['networkTokenId']
    except Exception as e:
        print(f'OPEN SHOEBOX ERROR for {EMAIL}', e)
        raise
    finally:
        if resp is not None:
            print(resp.status_code, 'open_shoebox', resp.text, '\n---')

    return sneaker


async def sell_sneaker(sneaker, cost_price, bot):
    price = get_sneaker_price(sneaker, cost_price)

    if not price:
        await bot.send_message(
            TELEGRAM_CHANNEL_ID,
            f'{EMAIL}\nCould not determine price for {TYPES[sneaker["staticSneakerTypeId"]]} {sneaker["networkTokenId"]}'
        )
        return

    data = {'params': {'dynSneakerId': sneaker['id'], 'priceFitfiAmount': str(price)}}
    resp = None

    try:
        resp = requests.post('https://prd-api.step.app/game/1/market/sellSneaker', headers=auth.get_headers(), json=data, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print(f'SELL SNEAKER ERROR for {EMAIL}', e)
        raise
    finally:
        if resp is not None:
            print(resp.status_code, resp.text, '\n---')

    if resp:
        await bot.send_message(
            TELEGRAM_CHANNEL_ID,
            f'{EMAIL}\nNew sneaker for sale:\n{price} FI {TYPES[sneaker["staticSneakerTypeId"]]} {sneaker["networkTokenId"]}'
        )


def get_sneaker_price(sneaker, cost_price):
    """
    1 - Coach
    2 - Walker
    3 - Hiker
    4 - Racer
    """
    if sneaker['staticSneakerRarityId'] != 1 or sneaker['staticSneakerRankId'] != 1:
        return None

    if sneaker['staticSneakerTypeId'] == 1:
        price = (cost_price + 5000) / 0.8
    elif sneaker['staticSneakerTypeId'] in [2, 3]:
        price = (cost_price + 3000) / 0.8
    else:
        price = (cost_price + 1000) / 0.8

    base = sum([sneaker['baseEfficiency'] + sneaker['baseLuck'] + sneaker['baseComfort'] + sneaker['baseResilience']])

    if base <= 30:
        price += 1000
    elif 30 < base <= 35:
        price += 2000
    elif 35 < base <= 40:
        price += 4000
    elif base > 40:
        # price += base * 180
        # price += 6000 + (base - 40) * 300
        return None

    return price + 200


async def check_sellings(cur_sellings, bot):
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
        await bot.send_message(TELEGRAM_CHANNEL_ID, f'{EMAIL}\nCurrent sellings: {sellings}')

    return sellings


async def reader(channel: aioredis.client.PubSub, bot):
    print(f'Reader started for {EMAIL}')

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
                            asyncio.create_task(buy_shoebox(item, bot))
        except asyncio.TimeoutError:
            pass
        finally:
            await asyncio.sleep(0.02)


async def main():
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()

    telegram_dir = os.path.join(os.path.dirname(__file__), '..', 'telegram')
    if not os.path.exists(telegram_dir):
        os.makedirs(telegram_dir)

    session = os.path.join(telegram_dir, f'bot-{hashlib.md5(EMAIL.encode()).hexdigest()}')
    client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
    bot = await client.start(bot_token=TELEGRAM_BOT_TOKEN)

    async def check_sellings_loop(bot):
        current_sellings = None

        while True:
            try:
                current_sellings = await check_sellings(current_sellings, bot)
            except Exception as e:
                print('check_sellings', e)

            await asyncio.sleep(random.randint(30, 60))

    check_sellings_loop_task = asyncio.create_task(check_sellings_loop(bot))

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(30)
            print(f'--- {dt.datetime.now()}')

    heartbeat_loop_task = asyncio.create_task(heartbeat_loop())

    async with pubsub as p:
        await p.subscribe('shoeboxes')
        await reader(p, bot)
        await p.unsubscribe('shoeboxes')

    check_sellings_loop_task.cancel()
    heartbeat_loop_task.cancel()
    await bot.disconnect()
    await pubsub.close()
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


# async def test():
#     telegram_dir = os.path.join(os.path.dirname(__file__), '..', 'telegram')
#     session = os.path.join(telegram_dir, f'bot-{hashlib.md5(EMAIL.encode()).hexdigest()}')
#     client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
#     bot = await client.start(bot_token=TELEGRAM_BOT_TOKEN)
#     await open_shoeboxes_and_sell({}, bot)
#     await bot.disconnect()


# if __name__ == '__main__':
#     asyncio.run(test())
