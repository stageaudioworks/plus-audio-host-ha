# Plus Audio Host for Home Assistant

A custom integration for the Plus Audio Host business music processor. It talks to the box's own API on the venue
network (no cloud), every 5 seconds.

**What you get**, per processor (one device):
- **A media player per zone:** source (the zone's allowed sources, plus Off), volume and mute, and what's playing on
  the music player or radio. Home Assistant's 0–100 % volume maps to −60 dB … the zone's staff limit, so automations
  can't make a zone louder than staff could.
- **Scene** (select): shows the scene that ran last; choosing one runs it.
- **Diagnostics:** audio dropouts (engine xruns), network clock (PTP) state, network inputs with problems.
- **Actions:** `plus_audio_host.announce` (a saved message by name, or text the box speaks, to zones by name or letter)
  and `plus_audio_host.stop_announcements`.

## Install

1. Copy `custom_components/plus_audio_host` into Home Assistant's `config/custom_components/` and restart. (HACS needs
   the integration at the root of its own repository; when it's published, this folder moves to e.g.
   `stageaudioworks/plus-audio-host-ha` with `hacs.json` beside it.)
2. On the processor: Settings → Access tokens → new token, scope **staff** (installer works too, but isn't needed).
3. Settings → Devices & services → Add integration → Plus Audio Host: the processor's address (e.g.
   `http://192.168.1.50`) and the token.

Revoking the token on the processor cuts Home Assistant off; it then asks for a new one.

## Examples

```yaml
# a closing announcement at 21:45 on weekdays, in the bar and patio
- alias: Closing announcement
  triggers: [{trigger: time, at: "21:45:00"}]
  conditions: [{condition: time, weekday: [mon, tue, wed, thu, fri]}]
  actions:
    - action: plus_audio_host.announce
      data: {message: "Closing in 15 minutes", zones: [Bar, Patio]}

# a door contact turns the patio music on and off
- alias: Patio music with the doors
  triggers: [{trigger: state, entity_id: binary_sensor.patio_doors}]
  actions:
    - action: media_player.select_source
      target: {entity_id: media_player.the_grill_house_patio}
      data:
        source: "{{ 'Music player' if trigger.to_state.state == 'on' else 'Off' }}"
```

## Tests

`pytest integrations/homeassistant/tests` with `pytest-homeassistant-custom-component` installed. The tests run Home
Assistant against the real control software (`control/test/harness.py` with the mock engine), not a mock of the API.
