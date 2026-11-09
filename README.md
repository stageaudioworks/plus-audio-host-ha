# Plus Audio Host for Home Assistant

Control a [Plus Audio](https://plus.audio) Host business music processor from Home Assistant: each zone's source,
volume and mute, scenes, announcements, zone groups and the amplifiers the processor looks after.

The integration talks to the processor directly on the venue network, every 5 seconds. Nothing goes through the
internet or a cloud account.

## What you get

For each processor, one device in Home Assistant with:

| Entity | What it does |
|---|---|
| **A media player per zone** | Source (the zone's allowed sources, plus Off), volume, mute, and what's playing on the music player or radio: artist, title, the album cover or station logo. Play, pause and skip while the zone plays the music player (play and pause on the radio), and a media browser with the favourite radio stations and the music channels. Home Assistant's 0–100 % volume maps to −60 dB … the zone's staff limit, so an automation can never make a zone louder than staff could. A zone the installer took out of use shows as unavailable. |
| **A media player per zone group** | The group's level (−40 … +10 dB) and mute. Groups made later on the processor appear by themselves. |
| **Scene** (select) | Shows the scene that ran last; choosing one runs it. |
| **Radio station** (select) | The internet radio's station, from the processor's favourites. |
| **Music player channel** (select) | The music player's channel: the processor's own music, or a Jamendo channel when Jamendo is set up on the processor. |
| **Audio dropouts**, **Network clock**, **Network inputs with problems** | Diagnostics: engine dropouts, the PTP clock state and AES67 inputs that aren't arriving. |
| **Per amplifier** (Plus Audio AC403 / AC401) | A power switch (on / standby), its temperature, and a problem sensor (not answering, protection, too hot, a short or missing speaker, a load far from normal; the details are in its `problems` attribute). |

And a dashboard card for live levels (below), plus two actions:

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

### From the Marketplace (Home Assistant 2026.11 and newer)

[![Open your Home Assistant and add this repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stageaudioworks&repository=plus-audio-host-ha&category=integration)

1. Press the button above. It opens your Home Assistant at the Marketplace with this repository filled in.
   (Or in the **Marketplace**, choose **Add from link** and paste `https://github.com/stageaudioworks/plus-audio-host-ha`,
   type **Integration**.)
2. The first time, the Marketplace asks you to connect a GitHub account (a code you enter on github.com; it only reads
   public information). It needs this for repositories that aren't in its catalog yet.
3. Accept the community-content notice, open **Plus Audio Host** and press **Install**.
4. Restart Home Assistant if it asks you to.

Updates appear under **Settings → Updates** when a new version is released.

### With HACS (Home Assistant 2026.10 and older)

1. In Home Assistant, open **HACS**.
2. Open the menu (⋮) at the top right → **Custom repositories**.
3. Repository: `https://github.com/stageaudioworks/plus-audio-host-ha`, Type: **Integration** → **Add**.
4. Search HACS for **Plus Audio Host**, open it and press **Download**.
5. Restart Home Assistant (**Settings → System → Restart**).

When you update Home Assistant to 2026.11, HACS becomes the Marketplace and keeps this integration and its updates.

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

# the bar on the radio at 17:00 (Jacaranda FM must be one of the processor's favourite stations)
- alias: Bar radio after work
  triggers:
    - trigger: time
      at: "17:00:00"
  actions:
    - action: media_player.select_source
      target:
        entity_id: media_player.the_grill_house_bar
      data:
        source: Internet radio
    - action: select.select_option
      target:
        entity_id: select.the_grill_house_radio_station
      data:
        option: Jacaranda FM

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

## Live meters

The integration brings its own dashboard card, **Plus Audio meters**: a meter bridge like a console's or Q-SYS's,
with a vertical segmented meter per zone (left and right), a dB scale, a peak-hold marker, a clip light that stays lit
for two seconds, and the level in dB under each zone. Edit a dashboard → **Add card** → search for "Plus Audio", or
in YAML:

```yaml
type: custom:plus-audio-meters-card
title: Levels          # optional
zones: [A, B, Bar]     # optional: letters or numbers; default every zone in use
ballistics: rms        # rms (default): averaged over about 300 ms, like a VU or a Q-SYS RMS meter
                       # ppm: rises at once and falls slowly, like a console's peak meter
                       # fast: the raw levels
peak_hold: 2           # optional: seconds the peak marker holds (0: none)
height: 200            # optional: meter height in pixels
show_values: true      # optional: the level in dB under each zone
rate: 15               # optional: updates a second from the processor, 1 to 20
entry_id: …            # optional: one processor, when you have more than one (default all)
```

Nothing to add under dashboard resources: the integration serves the card and loads it. The levels go from the
processor to Home Assistant and on to the open dashboard over Home Assistant's own connection; the browser never
talks to the processor or sees its token, and nothing is stored in Home Assistant's history. While no dashboard with
the card is open, nothing is fetched.

How live it is depends on the processor's software. The card's top right says which:

| Card says | Means |
|---|---|
| **live** | The processor pushes its levels (`/api/meters/ws`). |
| **live (polled)** | Home Assistant asks the processor for just the levels (`/api/meters`), at the card's rate. |
| **polled, may lag** | Older processor software: the levels come from its full status, which it may only refresh every few seconds. |

[METERS.md](METERS.md) describes the two newer endpoints for the processor's developers.

Zones no longer have a `level_db` attribute (it filled Home Assistant's history with a value every few seconds). Use
the card instead.

## Good to know

- **Limits are the processor's.** Volume can't go over a zone's staff limit, a zone only offers its allowed sources,
  and the processor refuses amplifier standby during a fire alarm. Home Assistant shows the refusal as an error.
- **Announcements and the fire alarm win.** While a zone is paging or the fire alarm is on, the processor keeps the
  zone the way the alarm or announcement needs it, whatever Home Assistant asks.
- **One music player and one radio per processor.** Every zone on the music player hears the same music, and every
  zone on the radio the same station. Skipping a song, pausing or changing the station from any zone (or the
  selects) changes it for all of them, just as on the processor's panels.
- **Stations:** Home Assistant can play the processor's favourite stations (an installer adds them on the processor
  under Music → Internet radio). Searching TuneIn for other stations stays with the installer.
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

Without `BMP_ROOT` those tests are skipped. The live meters' tests use a small fake processor and run anywhere:

```sh
pytest tests_meters
```
 GitHub Actions also runs Home Assistant's `hassfest` and the HACS checks on
every push.

## Licence

MIT, see [LICENSE](LICENSE). Plus Audio and Plus Audio Host are names of Stage Audio Works.
