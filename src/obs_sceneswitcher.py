from twitchAPI.pubsub import PubSub
from twitchAPI.twitch import Twitch
from twitchAPI.types import AuthScope, InvalidRefreshTokenException, CustomRewardRedemptionStatus
from twitchAPI.oauth import UserAuthenticator, refresh_access_token
import simpleobsws

from uuid import UUID

import traceback

import re
import json
import os

import yaml
import aiohttp
import asyncio


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
DEBUG = True

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
                        % (initiating_user, resp_data["reward"]["title"], config["REDEEM_SWITCH_TIME"]))

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


def createreward(user_id, i, tmpReward):
    reward_created = 0
    try:
        createdreward = twitch.create_custom_reward(broadcaster_id=user_id,
                                                    title=i,
                                                    prompt=tmpReward["prompt"],
                                                    cost=tmpReward["cost"],
                                                    global_cooldown_seconds=tmpReward["global_cooldown_seconds"],
                                                    is_global_cooldown_enabled=tmpReward["is_global_cooldown_enabled"])
        logger.info('TWITCH - setting up reward %s' % (i, ))
        if DEBUG:
            print(createdreward)
        reward_created = 1
    except Exception as e:
        logger.info("TWITCH - cannot create reward %s" % (i, ))
        logger.info("TWITCH - Exception is %s" % (e, ))

    if reward_created == 0:
        if DEBUG:
            logger.info("TWITCH - check if reward is still there")

    state.TWITCH_REWARDS = twitch.get_custom_reward(broadcaster_id=user_id)

def construct_rewards():
    for i in config["REWARDS"]:
        tmpReward = {}
        tmpReward["title"] = config["REWARDS"][i]['NAME']
        tmpReward[
            "prompt"] = "Schaltet die Kamera auf " + config["REWARDS"][i]['NAME'] + ". Automatisch erstellt durch " + SCRIPTNAME
        tmpReward["cost"] = config["REDEEM_SWITCH_COST"]
        tmpReward["is_global_cooldown_enabled"] = config["REDEEM_SWITCH_COOLDOWN_ENABLED"]
        tmpReward["global_cooldown_seconds"] = config["REDEEM_SWITCH_COOLDOWN"]
        logger.info("prepared reward %s" % (config["REWARDS"][i]['NAME'],))
        createreward(user_id, config["REWARDS"][i]['NAME'], tmpReward)

def redeemListInfo(r, stop):
    a = -1
    while True:
        if not len(r) == a:
            logger.info("Internal - currently waiting redeems %s" % (len(r), ))
            a = len(r)
        time.sleep(1)
        if stop():
            break


def updateRedeemStatus(tmpRedeem, status):
    # trying to update the redeem
    try:
        tmp_redeem_list = [tmpRedeem["redemption_id"], ]
        twitch.update_redemption_status(broadcaster_id=str(state.TWITCHUSERID),
                                        reward_id=tmpRedeem["reward_id"],
                                        redemption_ids=tmp_redeem_list,
                                        status=status)
        return True
    except Exception as e:
        logger.critical("TWITCH - Something went wrong while updating the redeem status: %s" % (e, ))
        return False

def redeemFulfiller(r, stop):
    while True:
        if (len(r) > 0):
            tmpRedeem = r.pop()
            logger.info("Internal - User %s redeemed %s for %s seconds"
                        % (tmpRedeem["username"], tmpRedeem["title"], config["REDEEM_SWITCH_TIME"], ))

            # initiate scene switch here
            # redeemCamSwitch(tmpRedeem)
            updateRedeemStatus(tmpRedeem, CustomRewardRedemptionStatus.FULFILLED)
            #time.sleep(int(config["CAMERA_SWITCH_TIME"]))
            logger.info("Internal - Done processing... %s - %s" % (tmpRedeem["username"], tmpRedeem["title"], ))
        time.sleep(1)
        if stop():
            break

def removerewards():
    all_existing_rewards = twitch.get_custom_reward(broadcaster_id=str(state.TWITCHUSERID))
    for k in all_existing_rewards["data"]:
        if SCRIPTNAME in k["prompt"]:
            twitch.delete_custom_reward(broadcaster_id=str(state.TWITCHUSERID), reward_id=k["id"])
            logger.info('TWITCH - removing reward %s' % (k["title"], ))


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

loop = asyncio.get_event_loop()
ws = simpleobsws.obsws(host=config["OBS_WS_IP"], port=config["OBS_WS_PORT"], password=config["OBS_WS_PASS"], loop=loop) # Every possible argument has been passed, but none are required. See lib code for defaults.



async def make_request():
    await ws.connect() # Make the connection to OBS-Websocket
    result = await ws.call('GetVersion') # We get the current OBS version. More request data is not required
    print(result) # Print the raw json output of the GetVersion request
    await asyncio.sleep(1)
    data = {'source':'test_source', 'volume':0.5}
    result = await ws.call('SetVolume', data) # Make a request with the given data
    print(result)
    await ws.disconnect() # Clean things up by disconnecting. Only really required in a few specific situations, but good practice if you are done making requests or listening to events.

async def switch_obs_scene(obs_scene_name):
    await ws.connect() # Make the connection to OBS-Websocket
    data = {'scene-name':obs_scene_name}
    result = await ws.call('SetCurrentScene', data) # Make a request with the given data
    print(result)
    await ws.disconnect() # Clean things up by disconnecting. Only really required in a few specific situations, but good practice if you are done making requests or listening to events.

async def stream_status():
    await ws.connect() # Make the connection to OBS-Websocket
    result = await ws.call('GetStreamingStatus') # Make a request with the given data
    print(result)
    await ws.disconnect() # Clean things up by disconnecting. Only really required in a few specific situations, but good practice if you are done making requests or listening to events.

async def set_name_of_requester(reward, requester):
    await ws.connect() # Make the connection to OBS-Websocket
    data = {'source': config['SHOW_REWARD_SOURCE']}
    print(data)
    result = await ws.call('GetTextGDIPlusProperties', data) # We get the current OBS version. More request data is not required
    print(result) # Print the raw json output of the GetVersion request
    data = result
    await asyncio.sleep(1)
    if reward != '' and requester != '':
        tpl = config['SHOW_REWARD_TEMPLATE']
        tpl = tpl.replace('___REWARD___', reward)
        tpl = tpl.replace('___REQUESTER___', requester)
    else:
        tpl = ''
    data['text'] = tpl
    print(data)
    result = await ws.call('SetTextGDIPlusProperties', data) # Make a request with the given data
    print(result)
    await ws.disconnect() # Clean things up by disconnecting. Only really required in a few specific situations, but good practice if you are done making requests or listening to events.


#loop.run_until_complete(stream_status())
#time.sleep(10)
#loop.run_until_complete(switch_obs_scene(config['PAUSE_SCENE']))
#loop.run_until_complete(switch_obs_scene('plasma music req cam main'))
#time.sleep(1)
#loop.run_until_complete(set_name_of_requester('REWARD', 'USER_XYZ'))
#time.sleep(10)
#loop.run_until_complete(set_name_of_requester('', ''))
#loop.run_until_complete(switch_obs_scene(config['MAIN_SCENE']))




# starting up PubSub
pubsub = PubSub(twitch)
pubsub.start()

removerewards()
construct_rewards()

# you can either start listening before or after you started pubsub.
uuid = pubsub.listen_channel_points(user_id, callback)

stop_threads = False

redeemMonitorThread = Thread(target=redeemListInfo, args=(redeems, lambda: stop_threads, ))
redeemWorkThread = Thread(target=redeemFulfiller, args=(redeems, lambda: stop_threads, ))

redeemMonitorThread.start()
redeemWorkThread.start()

input("any key to end\n")
stop_threads = True

redeemMonitorThread.join()
redeemWorkThread.join()

removerewards()

pubsub.unlisten(uuid)
pubsub.stop()
