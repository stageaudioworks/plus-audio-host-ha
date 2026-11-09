# Live meters: what the processor offers

For the processor software (plus-audio-bmp). The Home Assistant integration (0.3.0 and newer) uses the first of
these that a processor answers, and checks again ten minutes after a processor said no. Both need the same
`X-BMP-Token` header as the rest of the API, with staff scope or above.

## 1. Push: `GET /api/meters/ws` (websocket)

After the upgrade, the processor sends a text frame on its own at its metering rate (10 to 30 a second is plenty;
the integration drops frames faster than any open card asked for):

```json
{"zones": [
  {"zone": 1, "peak_db": [-12.5, -14.0], "rms_db": [-21.0, -22.4], "active": true},
  {"zone": 3, "peak_db": [-60.0, -60.0], "active": false}
]}
```

- `zone`: the zone number, as in `/api/state`.
- `peak_db`: the peak since the last frame per channel, in dBFS (one value for a mono zone). Silence as -120 or
  `null`.
- `rms_db` (optional): the average level per channel over the same window.
- `active` (optional): whether the zone has signal or is in use.

The integration ignores anything it receives from Home Assistant's side; nothing needs to be sent to the processor.
Frames for zones out of use are ignored. The integration keeps one socket per processor however many dashboards are
open, and closes it when the last one closes.

Answer the upgrade with 401 or 403 for a refused token (the card then shows the error) and 404 where there's no push.

## 2. A light poll: `GET /api/meters`

The same JSON as one push frame, the current levels only, and cheap enough to answer 20 times a second. Peaks
should be "since the last request" or a short window (about 100 ms), not cached for seconds.

## 3. Fallback: `GET /api/status`

What every processor has today: the integration reads `zones[].peak_db` from it. If the status is cached on the
processor (it is for 3 s for what's playing), the meters only move that often; the card says "polled, may lag".
