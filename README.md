# obs_sceneswitcher
OBS scene switches initiated by Twitch Channel Points

## About...

Depending on the selected category (eg. Music), obs_sceneswitcher creates rewards and 
watches for redeems and tries to fulfill them.

currently supported actions for rewards are:
- scene changes
- sources
- german joke tts
- change text of a text source

You can also define the length a reward should be active plus things like cooldowns.

If you change the category while streaming, existing previous created rewards will be cleaned
and replaced by rewards for the new category/game if defined in the config.

If you have an Elgato Stream Deck or comparable device, you can use the script 
obs_scene_trigger to switch to a scene on your remote stream pc.

## Requirements

In your OBS Studio, you need to install the obs-websocket plugin.

You can find it here: https://github.com/obsproject/obs-websocket

You need to create a dummy twitch extension for beeing able to work with the Twitch API.
Please fill in your channel name, the Client ID and Client Secret into the config file.

