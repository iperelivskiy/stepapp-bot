import datetime as dt
import json
import os
import pathlib

import jwt
from environs import Env


ENV = Env()
EMAIL = ENV.str('EMAIL')
PASSWORD = ENV.str('PASSWORD')

AUTH_PATH = os.path.join(os.path.dirname(__file__), '..', 'auth.json')


def set_auth(session):
    auth = _load_auth()
    token = auth.get(EMAIL)

    if not token:
        return update_auth(session)

    token_data = jwt.decode(token, algorithms=['HS256'], options={'verify_signature': False})
    exp = dt.datetime.fromtimestamp(token_data['Exp'])

    if dt.datetime.now() + dt.timedelta(seconds=60 * 10) < exp:
        session.headers['Authorization'] = f'Bearer {token}'
        return token
    else:
        return update_auth(session)


def update_auth(session):
    data = {'params':{'email': EMAIL, 'password': PASSWORD}}
    resp = session.post('https://prd-api.step.app/auth/auth/loginWithPassword/', json=data)

    try:
        resp.raise_for_status()
        token = resp.json()['result']['accessToken']
    except Exception:
        print(resp.text)
        raise

    session.headers['Authorization'] = f'Bearer {token}'
    auth = _load_auth()
    auth[EMAIL] = token
    _save_auth(auth)

    print('Auth success for', EMAIL)
    print(token)

    return token


def _load_auth():
    if not os.path.exists(AUTH_PATH):
        pathlib.Path(AUTH_PATH).touch()

    with open(AUTH_PATH, 'r') as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def _save_auth(auth):
    cur_auth = _load_auth()
    cur_auth.update(auth)

    with open(AUTH_PATH, 'w') as f:
        json.dump(cur_auth, f)
