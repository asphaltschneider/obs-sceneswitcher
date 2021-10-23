from twitchAPI.pubsub import PubSub
from twitchAPI.twitch import Twitch
from twitchAPI.types import AuthScope, InvalidRefreshTokenException, CustomRewardRedemptionStatus
from twitchAPI.oauth import UserAuthenticator, refresh_access_token
from uuid import UUID

import traceback

import re
import json
import os

import yaml
import aiohttp

import time
import random
from threading import Thread

import logging

SCRIPTNAME = "obs-sceneswitcher"
VERSION = "0.01"
CONFIG_FILE = "config.yaml"
secrets_fn = "twitch_secrets.json"
redeem_name_file = "redeem_data/redeem_name.txt"
redeem_user_file = "redeem_data/redeem_user.txt"
redeems = []
DEBUG = False

# initate everything we need for thread safe logging to stdout
logger = logging.getLogger(SCRIPTNAME)
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
# create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# add formatter to ch
ch.setFormatter(formatter)
logger.addHandler(ch)

logger.info("---------------------------------------------")
logger.info("%s" % (SCRIPTNAME, ))
logger.info("Version: %s" % (VERSION))
logger.info("---------------------------------------------")

file_list = os.listdir()
if CONFIG_FILE not in file_list:
    logger.info("There is no config.yaml config file.")
    logger.info("Please copy the config_example.yaml to config.yaml")
    logger.info("and edit it.")
    logger.info("--------------------------------------------------")
    input("Press return key to end!")
    exit(0)
else:
    with open("config.yaml") as fl:
        config = yaml.load(fl, Loader=yaml.FullLoader)


# this is our State class, with some helpful variables
class State:
    ir_connected = False



def update_twitch_secrets(new_data):
    with open(secrets_fn, "w+") as fl:
        fl.write(json.dumps(new_data))


def update_cam_file(camname):
    with open(redeem_cam_file, "w+") as fl:
        fl.write(camname)


def update_username_file(twitch_user):
    with open(redeem_user_file, "w+") as fl:
        fl.write(twitch_user)


def load_twitch_secrets():
    with open(secrets_fn) as fl:
        return json.loads(fl.read())


def callback(uuid: UUID, data: dict) -> None:
    try:
        if data["type"] != "reward-redeemed":
            return

        resp_data = data["data"]["redemption"]
        initiating_user = resp_data["user"]["login"]
        reward_broadcaster_id = resp_data["channel_id"]
        reward_id = resp_data["reward"]["id"]
        reward_prompt = resp_data["reward"]["prompt"]
        redemption_id = resp_data["id"]

        if SCRIPTNAME in reward_prompt:
            logger.info("TWITCH - User %s redeemed %s for %s seconds"
                        % (initiating_user, resp_data["reward"]["title"], config["CAMERA_SWITCH_TIME"]))

            tmpDict = {}
            tmpDict["reward_broadcaster_id"] = reward_broadcaster_id
            tmpDict["username"] = initiating_user
            tmpDict["reward_id"] = reward_id
            tmpDict["redemption_id"] = redemption_id
            tmpDict["title"] = resp_data["reward"]["title"]

            redeems.append(tmpDict)
        else:
            logger.info("TWITCH - User %s redeemed %s but it's not interesting for us."
                        % (initiating_user, resp_data["reward"]["title"], ))


    except Exception as e:
        logger.critical("".join(traceback.TracebackException.from_exception(e).format()))
        pass


async def callback_task(payload):
    try:
        if DEBUG:
            logger.debug("Running callback task...")

        if not twitch.session:
            twitch.session = aiohttp.ClientSession()

        logger.info("callback task")

    except Exception as e:
        logger.critical("".join(traceback.TracebackException.from_exception(e).format()))
        pass

# initialize our State class
state = State()

CLIENT_ID = config["CLIENT_ID"]
CLIENT_SECRET = config["CLIENT_SECRET"]
USERNAME = config["USERNAME"]

twitch_secrets = {
    "TOKEN": None,
    "REFRESH_TOKEN": None,
}

file_list = os.listdir()

if secrets_fn not in file_list:
    update_twitch_secrets(twitch_secrets)
else:
    twitch_secrets = load_twitch_secrets()

TOKEN = twitch_secrets["TOKEN"]
REFRESH_TOKEN = twitch_secrets["REFRESH_TOKEN"]
headers = {"content-type": "application/json"}

twitch = Twitch(CLIENT_ID, CLIENT_SECRET)
twitch.session = None

# setting up Authentication and getting your user id
twitch.authenticate_app([])

target_scope = [
    AuthScope.CHANNEL_READ_REDEMPTIONS,
    AuthScope.CHANNEL_MANAGE_REDEMPTIONS
]

auth = UserAuthenticator(twitch, target_scope, force_verify=True)

if (not TOKEN) or (not REFRESH_TOKEN):
    # this will open your default browser and prompt you with the twitch verification website
    TOKEN, REFRESH_TOKEN = auth.authenticate()
else:
    try:
        TOKEN, REFRESH_TOKEN = refresh_access_token(
            REFRESH_TOKEN, CLIENT_ID, CLIENT_SECRET
        )
    except InvalidRefreshTokenException:
        TOKEN, REFRESH_TOKEN = auth.authenticate()


twitch_secrets["TOKEN"] = TOKEN
twitch_secrets["REFRESH_TOKEN"] = REFRESH_TOKEN
update_twitch_secrets(twitch_secrets)

twitch.set_user_authentication(TOKEN, target_scope, REFRESH_TOKEN)

user_id = twitch.get_users(logins=[USERNAME])["data"][0]["id"]
state.TWITCHUSERID = user_id
