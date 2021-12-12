import simpleobsws
import traceback
import requests
import socket
import websockets
import websockets.exceptions
import websockets.legacy
import websockets.legacy.client
import websockets.legacy.auth


import re
import json
import os

import yaml
import aiohttp
import asyncio

import queue

import time
import random

import logging
import sys

SCRIPTNAME = "obs-scene-trigger"
VERSION = "0.01"
CONFIG_FILE = "config.yaml"

target_scene = "a dummy scene"
if len(sys.argv) > 1:
    #print(sys.argv[len(sys.argv)-1])
    target_scene = sys.argv[len(sys.argv)-1]

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
    with open("config.yaml", encoding="utf8") as fl:
        config = yaml.load(fl, Loader=yaml.FullLoader)

loop = asyncio.get_event_loop()
ws = simpleobsws.obsws(host=config["OBS_WS_IP"], port=config["OBS_WS_PORT"], password=config["OBS_WS_PASS"], loop=loop)

async def obs_executer(worksteps):
    #print(worksteps)
    try:
        await ws.connect()  # Make the connection to OBS-Websocket
        for _ in range(len(worksteps)):
            step = worksteps.pop(0)
            #print(worksteps)
            #for j in step:
            #logger.info("i=%s j=%s" % (step, j))
            if step["type"] == "scene":
                logger.info("changing scene to %s" % (step["scene"]))
                data = {'scene-name': step["scene"]}
                result = await ws.call('SetCurrentScene', data)

        await ws.disconnect()
    except Exception as e:
        logger.info("OBS_EXCECUTER - caught an exception %s" % (e))

step=[]
step.append({"type": "scene", "scene": target_scene})

loop.run_until_complete(obs_executer(step))