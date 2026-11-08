# Plus Audio Host for Home Assistant

Control a [Plus Audio](https://plus.audio) Host business music processor from Home Assistant: each zone's source,
volume and mute, scenes, announcements, zone groups and the amplifiers the processor looks after.

The integration talks to the processor directly on the venue network, every 5 seconds. Nothing goes through the
internet or a cloud account.

## What you get

For each processor, one device in Home Assistant with:

| Entity | What it does |
|---|---|
| **A media player per zone** | Source (the zone's allowed sources, plus Off), volume, mute, and what's playing on the music player or radio. Home Assistant's 0–100 % volume maps to −60 dB … the zone's staff limit, so an automation can never make a zone louder than staff could. A zone the installer took out of use shows as unavailable. |
| **A media player per zone group** | The group's level (−40 … +10 dB) and mute. Groups made later on the processor appear by themselves. |
| **Scene** (select) | Shows the scene that ran last; choosing one runs it. |
| **Audio dropouts**, **Network clock**, **Network inputs with problems** | Diagnostics: engine dropouts, the PTP clock state and AES67 inputs that aren't arriving. |
| **Per amplifier** (Plus Audio AC403 / AC401) | A power switch (on / standby), its temperature, and a problem sensor (not answering, protection, too hot, a short or missing speaker, a load far from normal; the details are in its `problems` attribute). |

And two actions:

- `plus_audio_host.announce`: play a saved message by name, or have the processor speak some text, in chosen zones.
- `plus_audio_host.stop_announcements`: stop what's playing and clear the queue.

## Before you start

- A Plus Audio Host on the same network as Home Assistant, with its address (for example `http://192.168.1.50`).
  A fixed address (a DHCP reservation on the router) saves trouble later.
- The processor's **installer PIN**, to make an access token. You only need it once.
- Home Assistant 2024.11 or newer.

## 1. Make an access token on the processor

1. Open the processor's address in a browser and sign in with the installer PIN.
2. Go to **Settings → Access tokens and AI assistants**.
3. Type a name (for example `Home Assistant`), choose **Staff**, and press **Create token**.
4. Press **Copy**. The token starts with `bmp_` and is only shown once; if you lose it, revoke it and make a new one.

**Staff** is enough for everything this integration does, and it keeps Home Assistant within the same limits as the
venue staff (zone volume limits, allowed sources). **Installer** works too but isn't needed.

## 2. Install the integration

### With HACS (recommended)

1. In Home Assistant, open **HACS**.
2. Open the menu (⋮) at the top right → **Custom repositories**.
3. Repository: `https://github.com/stageaudioworks/plus-audio-host-ha`, Type: **Integration** → **Add**.
4. Search HACS for **Plus Audio Host**, open it and press **Download**.
5. Restart Home Assistant (**Settings → System → Restart**).

HACS will offer updates when a new version is released.

### By hand

1. Download this repository (Code → Download ZIP) and unzip it.
2. Copy the `custom_components/plus_audio_host` folder into your Home Assistant `config/custom_components/` folder
   (make `custom_components` if it isn't there), so you have `config/custom_components/plus_audio_host/manifest.json`.
3. Restart Home Assistant.

## 3. Add the processor

1. **Settings → Devices & services → Add integration**, search for **Plus Audio Host**.
2. Address: the processor's address, for example `http://192.168.1.50` (or `https://…` if you've turned HTTPS on).
3. Access token: paste the `bmp_…` token.
4. Leave **Check the HTTPS certificate** off unless the processor has a certificate your network trusts (the
   processor's own certificate is self-signed).
5. Press **Submit**. The processor appears as a device, named as it is on the processor, with its zones.

Add more processors the same way; each is its own device.

## Using it

Zones are ordinary media players, so they work on dashboards, with voice assistants and in automations.

```yaml
# a closing announcement at 21:45 on weekdays, in the bar and patio
- alias: Closing announcement
  triggers:
    - trigger: time
      at: "21:45:00"
  conditions:
    - condition: time
      weekday: [mon, tue, wed, thu, fri]
  actions:
    - action: plus_audio_host.announce
      data:
        message: Closing in 15 minutes
        zones: [Bar, Patio]

# the patio music follows the patio doors
- alias: Patio music with the doors
  triggers:
    - trigger: state
      entity_id: binary_sensor.patio_doors
  actions:
    - action: media_player.select_source
      target:
        entity_id: media_player.the_grill_house_patio
      data:
        source: "{{ 'Music player' if trigger.to_state.state == 'on' else 'Off' }}"

# run the "Evening" scene at sunset
- alias: Evening music
  triggers:
    - trigger: sun
      event: sunset
  actions:
    - action: select.select_option
      target:
        entity_id: select.the_grill_house_scene
      data:
        option: Evening
```

`plus_audio_host.announce` takes:

| Field | |
|---|---|
| `message` | The name of a message saved on the processor. |
| `text` | Words for the processor to speak, when no saved message is given. |
| `zones` | Zone names or letters (`Bar`, `B`); leave it out for every zone that takes announcements. |
| `chime` | Play the chime first (default: the processor's own setting). |
| `config_entry_id` | Which processor, when you have more than one (default: all of them). |

## Good to know

- **Limits are the processor's.** Volume can't go over a zone's staff limit, a zone only offers its allowed sources,
  and the processor refuses amplifier standby during a fire alarm. Home Assistant shows the refusal as an error.
- **Announcements and the fire alarm win.** While a zone is paging or the fire alarm is on, the processor keeps the
  zone the way the alarm or announcement needs it, whatever Home Assistant asks.
- **Amplifiers** wake by themselves for announcements; you don't need to switch them on first.
- **Revoking the token** on the processor cuts Home Assistant off straight away. Home Assistant then asks for a new
  one (a notice under **Settings → Devices & services**); make a new token and paste it there.
- **A new address or token** for the same processor: **Settings → Devices & services → Plus Audio Host → ⋮ →
  Reconfigure**.

## Troubleshooting

| What you see | What to do |
|---|---|
| "Can't reach the processor at that address" | Check the address opens in a browser on the same network as Home Assistant; include `http://`. |
| "The processor refused that token" | The token was mistyped, revoked, or made on another processor. Make a new one (step 1). |
| "That address doesn't answer like a Plus Audio Host" | The address points at another device; check the processor's address on its screen or in your router. |
| Entities unavailable after a while | The processor is off, restarting (about a minute, for example after an update) or has a new address. Change the address with the integration's **Reconfigure**. |
| A zone is unavailable | The installer took it out of use on the processor. |

To see what the integration is doing, add this to `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.plus_audio_host: debug
```

Problems and ideas: [open an issue](https://github.com/stageaudioworks/plus-audio-host-ha/issues). For the processor
itself, contact Plus Audio support: support@stageaudioworks.com, +27 11 791 7829.

## Removing it

**Settings → Devices & services → Plus Audio Host → ⋮ → Delete**, then revoke its token on the processor
(Settings → Access tokens and AI assistants → Revoke).

## Development

The tests run Home Assistant against the processor's real control software (with a simulated audio engine), not a
mock of its API. They need a checkout of the processor software:

```sh
pip install pytest-homeassistant-custom-component
BMP_ROOT=/path/to/plus-audio-bmp pytest tests
```

Without `BMP_ROOT` the tests are skipped. GitHub Actions also runs Home Assistant's `hassfest` and the HACS checks on
every push.

## Licence

MIT, see [LICENSE](LICENSE). Plus Audio and Plus Audio Host are names of Stage Audio Works.
