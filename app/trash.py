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
