import asyncio
import json
import os
import signal
import sys

import aioredis
import async_timeout
from environs import Env


ENV = Env()
REDIS_URL = ENV.str('REDIS_URL')


async def buy(item):
    print(f"(Reader) Message Received: {item}")


async def reader(channel: aioredis.client.PubSub):
    print('Start reader')
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
                        asyncio.create_task(buy(item))

                    # if message["data"] == STOPWORD:
                    #     print("(Reader) STOP")
                    #     break
                await asyncio.sleep(0.05)
        except asyncio.TimeoutError:
            pass


async def main():
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()

    async with pubsub as p:
        await p.subscribe('shoeboxes')
        await reader(p)
        await p.unsubscribe('shoeboxes')

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
