import datetime as dt
import json
import os

import jwt
import requests
from environs import Env


ENV = Env()
EMAIL = ENV.str('EMAIL')
PASSWORD = ENV.str('PASSWORD')

AUTH_PATH = os.path.join(os.path.dirname(__file__), '..', 'auth.json')


def get_headers(auth=True):
    headers = {
        'User-Agent': 'stepapp/1.0 (com.step.stepapp-ios; build:30; iOS 15.7.0) Alamofire/5.6.1',
        'Accept-Encoding': 'br;q=1.0, gzip;q=0.9, deflate;q=0.8',
        'Accept-Language': 'en-KZ;q=1.0, ru-KZ;q=0.9'
    }

    if auth:
        headers['Authorization'] = f'Bearer {get_token()}'

    return headers


def get_token():
    if not os.path.exists(AUTH_PATH):
        return get_new_token()

    with open(AUTH_PATH, 'r') as f:
        auth = json.load(f)
        token = auth.get(EMAIL)
        if not token:
            return get_new_token()

    token_data = jwt.decode(token, algorithms=['HS256'], options={'verify_signature': False})
    exp = dt.datetime.fromtimestamp(token_data['Exp'])

    if dt.datetime.now() + dt.timedelta(seconds=60 * 10) < exp:
        return token
    else:
        return get_new_token()


def get_new_token():
    data = {'params':{'email': EMAIL, 'password': PASSWORD}}
    resp = requests.post('https://prd-api.step.app/auth/auth/loginWithPassword/', headers=get_headers(False), json=data, verify=False)

    try:
        resp.raise_for_status()
        token = resp.json()['result']['accessToken']
    except Exception:
        print(resp.text)
        raise

    if os.path.exists(AUTH_PATH):
        with open(AUTH_PATH, 'r') as f:
            auth = json.load(f)
    else:
        auth = {}

    auth[EMAIL] = token

    with open(AUTH_PATH, 'w') as f:
        json.dump(auth, f)

    print('Auth success for', EMAIL)
    print(token)

    return token
