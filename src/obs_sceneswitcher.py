from twitchAPI.pubsub import PubSub
from twitchAPI.twitch import Twitch
from twitchAPI.types import AuthScope, InvalidRefreshTokenException, CustomRewardRedemptionStatus
from twitchAPI.oauth import UserAuthenticator, refresh_access_token
import simpleobsws
import pyttsx3

from uuid import UUID

import traceback

import re
import json
import os

import yaml
import aiohttp
import asyncio

import queue

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
rq = queue.Queue()
oq = queue.Queue()
obs_ws_queue = []
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

engine = pyttsx3.init()
engine.setProperty('voice', "HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\TTS_MS_DE-DE_HEDDA_11.0")


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
    obs_current_scene = "UNKNOWN"
    obs_streaming = False
    obs_ws_queue = []
    twitch_category = "IRL"


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
            rq.put(tmpDict)
            logger.info("TWITCH - rq has %s elements" % (rq.qsize(),))

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
        #if DEBUG:
        #    print(createdreward)
        reward_created = 1
    except Exception as e:
        logger.info("TWITCH - cannot create reward %s" % (i, ))
        logger.info("TWITCH - Exception is %s" % (e, ))

    if reward_created == 0:
        if DEBUG:
            logger.info("TWITCH - check if reward is still there")

    state.TWITCH_REWARDS = twitch.get_custom_reward(broadcaster_id=user_id)

def construct_rewards(category):

    logger.info("REWARD_CREATOR - preparing for category %s" % (category,))
    for i in config["REWARDS"][category]["TWITCH"]:
        tmpReward = {}
        tmpReward["title"] = config["REWARDS"][category]["TWITCH"][i]['NAME']
        tmpReward[
            "prompt"] = "Schaltet die Kamera auf " + config["REWARDS"][category]["TWITCH"][i]['NAME'] + ". Automatisch erstellt durch " + SCRIPTNAME
        if "COST" in config["REWARDS"][category]["TWITCH"][i]:
            tmpReward["cost"] = config["REWARDS"][category]["TWITCH"][i]["COST"]
        else:
            tmpReward["cost"] = config["REDEEM_SWITCH_COST"]
        tmpReward["is_global_cooldown_enabled"] = config["REDEEM_SWITCH_COOLDOWN_ENABLED"]
        tmpReward["global_cooldown_seconds"] = config["REDEEM_SWITCH_COOLDOWN"]
        logger.info("REWARD_CREATOR - prepared reward %s" % (config["REWARDS"][category]["TWITCH"][i]['NAME'],))
        createreward(user_id, config["REWARDS"][category]["TWITCH"][i]['NAME'], tmpReward)

def redeemListInfo(r, rq, oq, stop):
    logger.info("REDEEM_LISTINFO - entering thread")
    a = -1
    while True:
        if not rq.empty():
            logger.info("REDEEM_LISTINFO - currently waiting redeems %s" % (rq.qsize(), ))
#        else:
#            if oq.empty() or oq.qsize() >=1:
#                # lets update Scene info
#                qe = {"type": "get_scene", }
#                oq.put(qe)
#                time.sleep(2)
        time.sleep(1)
        if stop():
            break
    logger.info("REDEEM_LISTINFO - ending thread")

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

def redeemFulfiller(r, rq, q, engine, stop):
    logger.info("REDEEM_FULFILLER - entering thread")
    while True:
        if not rq.empty():
            a = 1
            #if state.obs_current_scene == config["MAIN_SCENE"]:
            if a == 1:
                #tmpRedeem = r.pop()
                tmpRedeem = rq.get()
                logger.info("REDEEM_FULFILLER - User %s redeemed %s for %s seconds"
                            % (tmpRedeem["username"], tmpRedeem["title"], config["REDEEM_SWITCH_TIME"], ))

                # initiate scene switch here
                # redeemCamSwitch(tmpRedeem)
                fullfilled = 0
                for i in config["REWARDS"][state.twitch_category.upper()]["TWITCH"]:
                    if config["REWARDS"][state.twitch_category.upper()]["TWITCH"][i]["NAME"] == tmpRedeem["title"]:
                        logger.info("REDEEM_FULFILLER - let's gooooo")
                        tmp_obs_job = {}
                        if config["REWARDS"][state.twitch_category.upper()]["TWITCH"][i]["TYPE"] == "scene":
                            tmp_obs_job["type"] = config["REWARDS"][state.twitch_category.upper()]["TWITCH"][i]["TYPE"]
                            tmp_obs_job["targetscene"] = config["REWARDS"][state.twitch_category.upper()]["TWITCH"][i]["SCENE"]
                            tmp_obs_job["mainscene"] = config["REWARDS"][state.twitch_category.upper()]["OBS"]["SCENES"]["MAIN"]
                            tmp_obs_job["duration"] = int(config["REDEEM_SWITCH_TIME"])
                            tmp_obs_job["user"] = tmpRedeem["username"]
                            tmp_obs_job["reward"] = tmpRedeem["title"]
                        elif config["REWARDS"][state.twitch_category.upper()]["TWITCH"][i]["TYPE"] == "speech":
                            engine.say("Der Zuschauer %s wünscht sich %s." % (tmpRedeem["username"], tmpRedeem["title"]))
                            engine.runAndWait()

                            tmp_obs_job["type"] = config["REWARDS"][state.twitch_category.upper()]["TWITCH"][i]["TYPE"]
                            tmp_obs_job["text"] = config["REWARDS"][state.twitch_category.upper()]["TWITCH"][i]["TEXT"]
                            tmp_obs_job["user"] = tmpRedeem["username"]
                            tmp_obs_job["reward"] = tmpRedeem["title"]


                        if "type" in tmp_obs_job:
                            if config["REWARDS"][state.twitch_category.upper()]["TWITCH"][i]["TYPE"] != "speech":
                                q.put(tmp_obs_job)
                            logger.info("REDEEM_FULFILLER - q has %s elements" % (q.qsize(), ))
                            fullfilled = 1
                        else:
                            logger.info("REDEEM_FULFILLER - strange.... no type")
                            fullfilled = 2


                rq.task_done()

                if fullfilled == 1:
                    updateRedeemStatus(tmpRedeem, CustomRewardRedemptionStatus.FULFILLED)
                    logger.info("REDEEM_FULFILLER - Done processing... %s - %s" % (tmpRedeem["username"], tmpRedeem["title"],))
                else:
                    updateRedeemStatus(tmpRedeem, CustomRewardRedemptionStatus.CANCELED)
                    logger.info("REDEEM_FULFILLER - canceled processing... %s - %s" % (tmpRedeem["username"], tmpRedeem["title"],))

            time.sleep(5)

        time.sleep(1)
        if stop():
            break
    logger.info("REDEEM_FULFILLER - ending thread")


def twitchWatcher(stop):
    logger.info("TWITCHWATCHER - entering thread")
    while True:
        try:
            #logger.info("TWITCH - reading stream info")
            result = twitch.get_channel_information(broadcaster_id=state.TWITCHUSERID)
            game_name=result["data"][0]["game_name"]
            if (state.twitch_category != game_name):
                state.twitch_category = game_name
                logger.info("TWITCH - stream category name is: %s" % (state.twitch_category))
            time.sleep(30)
        except Exception as e:
            logger.info("TWITCH - cannot read stream info")
            logger.info("TWITCH - Exception is %s" % (e,))

        if stop():
            break
    logger.info("TWITCHWATCHER - ending thread")

def obsWorker(obs_ws_queue, q, loop, stop):
    logger.info("OBS_WORKER - entering thread")
    a = -1

    while True:
        tmp_worksteps = []
        if not q.empty() and state.obs_current_scene == config["REWARDS"][state.twitch_category.upper()]["OBS"]["SCENES"]["MAIN"]:
            logger.info("OBS_WORKER - currently waiting jobs %s" % (q.qsize(), ))
            #obs_job = obs_ws_queue.pop()
            obs_job = q.get()
            #a = len(obs_ws_queue)
            print(obs_job)
            if obs_job["type"] == "scene":
                logger.info("OBS_WORKER - scene")
                tmp_worksteps.append({"type": "scene", "scene": obs_job["targetscene"]});
                tmp_worksteps.append({"type": "text", "user": obs_job["user"], "reward": obs_job["reward"]});
                tmp_worksteps.append({"type": "pause", "duration": obs_job["duration"]});
                tmp_worksteps.append({"type": "cleartext", });
                tmp_worksteps.append({"type": "scene", "scene": obs_job["mainscene"]});
            elif obs_job["type"] == "speech":
                logger.info("OBS_WORKER - text")
                tmp_worksteps.append({"type": "text", "text": obs_job["text"]});
            else:
                logger.info("OBS_WORKER - get_scene")
                tmp_worksteps.append({"type": "get_scene"});

            logger.info("OBS_WORKER - fire obs executer")
            loop.run_until_complete(obs_executer(tmp_worksteps))
            q.task_done()
            logger.info("OBS_WORKER - currently waiting jobs %s" % (q.qsize(),))
            time.sleep(2)
        else:
            logger.info("OBS_WORKER - else - still alive...")
            time.sleep(5)
            #logger.info("OBS_WORKER - else - currently waiting jobs %s" % (q.qsize(),))

        tmp_worksteps.append({"type": "get_scene"});
        logger.info("OBS_WORKER - fire obs executer")
        loop.run_until_complete(obs_executer(tmp_worksteps))
        time.sleep(5)

        if stop():
            break

    logger.info("OBS_WORKER - leaving  thread")

def obsWatcher(stop):
    never_set = 1
    logger.info("OBS_WATCHER - entering thread")
    while True:
        stream_on = loop1.run_until_complete(stream_status())
        if state.obs_streaming != stream_on or never_set == 1:
            logger.info("OBS_WATCHER - stream status changed to %s" % (stream_on))
            state.obs_streaming = stream_on
            never_set = 0
        state.obs_current_scene = loop1.run_until_complete(get_obs_scene())
        time.sleep(2)
        if stop():
            break
    logger.info("OBS_WATCHER - ending thread")

def rewardCreator(stop):
    logger.info("REWARD_CREATOR - entering thread")
    removerewards()
    rewards_set = 0
    category_list = []
    current_active_category = "none"
    for i in config["REWARDS"]:
        category_list.append(i)
        logger.info("REWARD_CREATOR - added %s to category_list" % (i))

    while True:
        if state.obs_streaming == False and \
                state.twitch_category.upper() != current_active_category:
            if rewards_set == 0 and state.twitch_category.upper() != current_active_category:
                if state.twitch_category.upper() in category_list:
                    if config["REWARDS"][state.twitch_category.upper()]:

                        logger.info("REWARD_CREATOR - will create rewards")
                        construct_rewards(state.twitch_category.upper())
                        rewards_set = 1
                        current_active_category = state.twitch_category.upper()

                    else:

                        logger.info("REWARD_CREATOR - no predefined rewards in config for %s" % (state.twitch_category.upper()))
                        rewards_set = 1
                        current_active_category = state.twitch_category.upper()
            elif rewards_set == 1 and state.twitch_category.upper() != current_active_category:
                logger.info("REWARD_CREATOR - Twitch Category changed to %s." % (state.twitch_category, ))
                logger.info("REWARD_CREATOR - destroying rewards")
                removerewards()
                rewards_set = 0


        else:
            if rewards_set == 1 and state.twitch_category.upper() != current_active_category:
                logger.info("Twitch Category changed to %s." % (state.twitch_category, ))
                logger.info("REWARD_CREATOR - destroying rewards")
                removerewards()
                rewards_set = 0


        time.sleep(2)
        if stop():
            break
    removerewards()
    logger.info("REWARD_CREATOR - ending thread")

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
ws = simpleobsws.obsws(host=config["OBS_WS_IP"], port=config["OBS_WS_PORT"], password=config["OBS_WS_PASS"], loop=loop)

#loop1 = asyncio.get_event_loop()
#loop2 = asyncio.get_event_loop()
#ws1 = simpleobsws.obsws(host=config["OBS_WS_IP"], port=config["OBS_WS_PORT"], password=config["OBS_WS_PASS"], loop=loop1)
#ws2 = simpleobsws.obsws(host=config["OBS_WS_IP"], port=config["OBS_WS_PORT"], password=config["OBS_WS_PASS"], loop=loop2)

async def obs_executer(worksteps):
    #print(worksteps)
    await ws.connect()  # Make the connection to OBS-Websocket
    for _ in range(len(worksteps)):
        step = worksteps.pop(0)
        #print(worksteps)
        #for j in step:
        #logger.info("i=%s j=%s" % (step, j))
        if step["type"] == "scene":
            logger.info("changing scene to %s" % (step["scene"]))
            data = {'scene-name': step["scene"]}
            state.obs_current_scene = step["scene"]
            result = await ws.call('SetCurrentScene', data)
        elif step["type"] == "get_scene":
            result = await ws.call('GetCurrentScene')
            if state.obs_current_scene != result['name']:
                logger.info("scene has changed to %s" % (result['name']))
                state.obs_current_scene = result['name']
        elif step["type"] == "pause":
            logger.info("sleeping for %s seconds" % (step["duration"]))
            await asyncio.sleep(step["duration"])
        elif step["type"] == "text":
            logger.info("setting text for user %s" % (step["user"]))
            data = {'source': config['SHOW_REWARD_SOURCE']}
            # print(data)
            result = await ws.call('GetTextGDIPlusProperties', data)
            # print(result)  # Print the raw json output of the GetVersion request
            data = result
            await asyncio.sleep(1)
            if step["reward"] != '' and step["user"] != '':
                tpl = config['SHOW_REWARD_TEMPLATE']
                tpl = tpl.replace('___REWARD___', step["reward"])
                tpl = tpl.replace('___REQUESTER___', step["user"])
            else:
                tpl = ''
            data['text'] = tpl
            logger.info("setting text to %s" % (tpl))

            # print(data)
            result = await ws.call('SetTextGDIPlusProperties', data)
        elif step["type"] == "cleartext":
            logger.info("cleanup text")
            data = {'source': config['SHOW_REWARD_SOURCE']}
            result = await ws.call('GetTextGDIPlusProperties', data)
            data = result
            await asyncio.sleep(1)
            tpl = ''
            data['text'] = tpl
            result = await ws.call('SetTextGDIPlusProperties', data)

    await ws.disconnect()

#loop = asyncio.get_event_loop()
#ws = simpleobsws.obsws(host=config["OBS_WS_IP"], port=config["OBS_WS_PORT"], password=config["OBS_WS_PASS"], loop=loop2)

#async def on_switchscenes(data):
#    logger.info('Scene switched to "%s".' % (data['scene-name']))
#    state.obs_current_scene = data['scene-name']




#
#
# async def switch_obs_scene(obs_scene_name, obs_main_scene, duration):
#     await ws2.connect() # Make the connection to OBS-Websocket
#     data = {'scene-name':obs_scene_name}
#     state.obs_current_scene = obs_scene_name
#     result = await ws2.call('SetCurrentScene', data) # Make a request with the given data
#     await asyncio.sleep(duration)
#     data = {'scene-name':obs_main_scene}
#     state.obs_current_scene = obs_main_name
#     result = await ws.call('SetCurrentScene', data) # Make a request with the given data
#     await ws2.disconnect() # Clean things up by disconnecting. Only really required in a few specific situations, but good practice if you are done making requests or listening to events.
#
#
# async def stream_status():
#     await ws1.connect() # Make the connection to OBS-Websocket
#     result = await ws1.call('GetStreamingStatus') # Make a request with the given data
#     #print(result)
#     await ws1.disconnect() # Clean things up by disconnecting. Only really required in a few specific situations, but good practice if you are done making requests or listening to events.
#     return result["streaming"]
#
# async def set_name_of_requester(reward, requester):
#     await ws1.connect() # Make the connection to OBS-Websocket
#     data = {'source': config['SHOW_REWARD_SOURCE']}
#     print(data)
#     result = await ws1.call('GetTextGDIPlusProperties', data) # We get the current OBS version. More request data is not required
#     print(result) # Print the raw json output of the GetVersion request
#     data = result
#     await asyncio.sleep(1)
#     if reward != '' and requester != '':
#         tpl = config['SHOW_REWARD_TEMPLATE']
#         tpl = tpl.replace('___REWARD___', reward)
#         tpl = tpl.replace('___REQUESTER___', requester)
#     else:
#         tpl = ''
#     data['text'] = tpl
#     print(data)
#     result = await ws1.call('SetTextGDIPlusProperties', data) # Make a request with the given data
#     print(result)
#     await ws1.disconnect() # Clean things up by disconnecting. Only really required in a few specific situations, but good practice if you are done making requests or listening to events.
#




#loop.run_until_complete(stream_status())
#loop.run_until_complete(get_obs_scene())
#time.sleep(10)
#loop.run_until_complete(switch_obs_scene(config['PAUSE_SCENE']))
#loop.run_until_complete(switch_obs_scene('plasma music req cam main'))
#time.sleep(1)
#loop.run_until_complete(set_name_of_requester('REWARD', 'USER_XYZ'))
#time.sleep(10)
#loop.run_until_complete(set_name_of_requester('', ''))
#loop.run_until_complete(switch_obs_scene(config['MAIN_SCENE']))

async def get_obs_scene():
    await ws.connect()
    result = await ws.call('GetCurrentScene')
    await ws.disconnect()
    state.obs_current_scene = result['name']

loop.run_until_complete(get_obs_scene())


# starting up PubSub
pubsub = PubSub(twitch)
pubsub.start()

# you can either start listening before or after you started pubsub.
uuid = pubsub.listen_channel_points(user_id, callback)

stop_threads = False

obsWatcherThread = Thread(target=obsWorker, args=(obs_ws_queue, oq, loop, lambda: stop_threads, ))
twitchWatcherThread = Thread(target=twitchWatcher, args=( lambda: stop_threads, ))
rewardCreatorThread = Thread(target=rewardCreator, args=( lambda: stop_threads, ))
redeemMonitorThread = Thread(target=redeemListInfo, args=(redeems, rq, oq, lambda: stop_threads, ))
redeemWorkThread = Thread(target=redeemFulfiller, args=(redeems, rq, oq, engine, lambda: stop_threads, ))

obsWatcherThread.start()
twitchWatcherThread.start()
rewardCreatorThread.start()
redeemMonitorThread.start()
redeemWorkThread.start()

#loop2.run_until_complete(ws2.connect())
#ws.register(on_switchscenes, 'SwitchScenes')
#loop.run_forever()

input("any key to end\n")
stop_threads = True

rewardCreatorThread.join()
redeemMonitorThread.join()
redeemWorkThread.join()
twitchWatcherThread.join()
obsWatcherThread.join()


pubsub.unlisten(uuid)
pubsub.stop()
