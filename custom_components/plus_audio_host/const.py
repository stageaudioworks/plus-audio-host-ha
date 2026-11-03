DOMAIN = "plus_audio_host"
CONF_TOKEN = "token"
CONF_VERIFY_SSL = "verify_ssl"
SCAN_SECONDS = 5
GROUP_MIN_DB, GROUP_MAX_DB = -40.0, 10.0   # a zone group's level (#81): the slider 0..1 maps to -40..+10 dB
VOL_FLOOR_DB = -60.0        # Home Assistant's volume slider 0..1 maps to -60 dB .. the zone's limit, linear in dB
