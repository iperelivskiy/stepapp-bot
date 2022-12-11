import asyncio
import urllib3

import requests
from environs import Env

import auth


ENV = Env()


async def open_lootboxes():
    resp = requests.post('https://prd-api.step.app/game/1/user/getCurrent', headers=auth.get_headers(), verify=False)

    try:
        resp.raise_for_status()
        revision = resp.json()['result']['changes']['dynUsers']['updated'][0]['revision']
        print(revision)
    except Exception:
        print(resp.text)
        raise

    data = {"params": {"lootBoxDynItemId": 47810}}
    resp = requests.post('https://prd-api.step.app/game/1/lootBox/open', headers=auth.get_headers(), json=data, verify=False)

    try:
        resp.raise_for_status()
        print(resp.json())
    except Exception:
        print(resp.text)
        raise


async def main():
    await open_lootboxes()


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    asyncio.run(main())
