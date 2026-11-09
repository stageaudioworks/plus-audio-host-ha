# Changelog

## 0.2.0 (9 Nov 2026)

- Own repository (stageaudioworks/plus-audio-host-ha), MIT licence, setup guide.
- Installs from the Home Assistant Marketplace (2026.11+) by link, or HACS on older versions.
- Brand icon and logo, light and dark, shipped with the integration.
- Zones show the artist, title and album cover (or station logo) of the music player and the radio, with play, pause
  and skip, and a media browser of the favourite stations and the music channels.
- New selects for the whole processor: Radio station and Music player channel.
- A zone on the music player or radio now reports playing, paused or idle (before: on). Automations that test for
  `on` should test for `playing` or for "not off".
- Reconfigure: a new address, token or HTTPS setting for the same processor.
- Zone groups: a media player per group (level and mute).
- Amplifiers (Plus Audio AC403 / AC401): power switch, temperature, problem sensor.
- A zone the installer takes out of use shows as unavailable.
- Home Assistant 2024.11 or newer.

## 0.1.0 (1 Nov 2026)

- A media player per zone (source, volume within the staff limit, mute, now playing), Scene select, diagnostics,
  `plus_audio_host.announce` and `plus_audio_host.stop_announcements`. Token re-authentication.
