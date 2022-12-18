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

ALLOWED_SHOEBOX_TYPES = ENV.list('ALLOWED_SHOEBOXES', [1, 2, 3, 4])


TYPES = {
    1: 'Coach',
    2: 'Walker',
    3: 'Hiker',
    4: 'Racer'
}


async def buy_shoebox(item, session, bot, set_cooldown):

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
        await bot.send_message(TELEGRAM_CHANNEL_ID, f'{EMAIL}\nBought shoebox {TYPES[item["staticSneakerTypeId"]]} #{item["networkTokenId"]}')
        # cost_prices = {item['networkTokenId']: item['priceFitfi']}
        # asyncio.create_task(open_shoeboxes_and_sell(cost_prices, bot))


async def buy_lootbox(item, session, bot, set_cooldown):

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
        await bot.send_message(TELEGRAM_CHANNEL_ID, f'{EMAIL}\nBought lootbox #{item["networkTokenId"]}')


async def check_sellings(cur_sellings, session, bot):
    resp = session.post('https://prd-api.step.app/game/1/user/getCurrent', timeout=5)

    if resp.status_code == 401:
        auth.update_auth(session)
        return await check_sellings(cur_sellings, session, bot)

    sellings = 0

    try:
        resp.raise_for_status()
        sneaker_sellings = resp.json()['result']['changes']['dynUsers']['updated'][0]['sneakerSellings']
        sellings += len(sneaker_sellings['updated']) if sneaker_sellings else 0
        lootbox_sellings = resp.json()['result']['changes']['dynUsers']['updated'][0]['lootBoxSellings']
        sellings += len(lootbox_sellings['updated']) if lootbox_sellings else 0
    except Exception:
        print(resp.text)
        raise

    if cur_sellings is not None and cur_sellings > sellings:
        await bot.send_message(TELEGRAM_CHANNEL_ID, f'{EMAIL}\nCurrent sellings: {sellings}')

    return sellings


async def reader(channel: aioredis.client.PubSub, session, bot, lock):
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
                            asyncio.create_task(buy_lootbox(item, session, bot, set_cooldown))
                        else:
                            asyncio.create_task(buy_shoebox(item, session, bot, set_cooldown))
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

    bot_session = os.path.join(telegram_dir, f'bot-{hashlib.md5(EMAIL.encode()).hexdigest()}')
    client = TelegramClient(bot_session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
    bot = await client.start(bot_token=TELEGRAM_BOT_TOKEN)

    session = cloudscraper.create_scraper(browser={
        'browser': 'chrome',
        'platform': 'darwin',
        'mobile': False
    })

    data = {'params': {'deviceId': hashlib.md5(EMAIL.encode()).hexdigest()}}
    resp = session.post('https://prd-api.step.app/analytics/seenLogInView', json=data)
    resp.raise_for_status()
    auth.set_auth(session)
    lock = asyncio.Lock()

    async def check_sellings_loop(session, bot):
        current_sellings = None

        while True:
            try:
                current_sellings = await check_sellings(current_sellings, session, bot)
            except Exception as e:
                print('check_sellings', e)

            print(f'--- {dt.datetime.now()}{["", " cooldown"][lock.locked()]}')
            await asyncio.sleep(random.randint(30, 60))

    check_sellings_loop_task = asyncio.create_task(check_sellings_loop(session, bot))

    async with pubsub as p:
        channels = [f'shoeboxes:{ast}' for ast in ALLOWED_SHOEBOX_TYPES]
        channels.append('shoeboxes:any')

        if ENV.bool('LOOTBOXES_ALLOWED', False):
            channels.append('lootboxes')

        await p.subscribe(*channels)
        await reader(p, session, bot, lock)
        await p.unsubscribe(*channels)

    check_sellings_loop_task.cancel()
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


async def open_shoeboxes_and_sell(session, cost_prices, bot):
    resp = None

    try:
        resp = session.post('https://prd-api.step.app/game/1/user/getCurrent')
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


async def open_shoebox(session, shoebox):
    data = {'params': {'shoeBoxDynItemId': shoebox['id']}}
    resp = None

    try:
        resp = session.post('https://prd-api.step.app/game/1/shoeBox/seen', json=data)
        resp.raise_for_status()
        resp = session.post('https://prd-api.step.app/game/1/shoeBox/open', json=data)
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


async def sell_sneaker(session, sneaker, cost_price, bot):
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
        resp = session.post('https://prd-api.step.app/game/1/market/sellSneaker', json=data)
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


# async def test():
#     telegram_dir = os.path.join(os.path.dirname(__file__), '..', 'telegram')
#     session = os.path.join(telegram_dir, f'bot-{hashlib.md5(EMAIL.encode()).hexdigest()}')
#     client = TelegramClient(session, TELEGRAM_APP_ID, TELEGRAM_APP_TOKEN)
#     bot = await client.start(bot_token=TELEGRAM_BOT_TOKEN)
#     await open_shoeboxes_and_sell({}, bot)
#     await bot.disconnect()


# if __name__ == '__main__':
#     asyncio.run(test())
