# Releasing and publishing

**A release:** raise `version` in `custom_components/plus_audio_host/manifest.json`, add it to `CHANGELOG.md`, and
publish a GitHub release tagged `vX.Y.Z`. HACS offers the newest release to users.

**HACS default list** (so it appears in HACS without adding a custom repository), in this order:

1. This repository public, with a description and topics (`home-assistant`, `hacs`, `integration`), issues on.
2. The icon and logo in [home-assistant/brands](https://github.com/home-assistant/brands): a pull request adding
   `custom_integrations/plus_audio_host/icon.png` (256x256) and `icon@2x.png` (512x512), and `logo.png` if wanted.
   Then remove `ignore: brands` from `.github/workflows/validate.yml`.
3. At least one full release (not a pre-release).
4. A pull request to [hacs/default](https://github.com/hacs/default) adding `stageaudioworks/plus-audio-host-ha` to
   the `integration` file, with the hassfest and HACS actions passing here.

**Home Assistant core** (built in, no HACS) is a later step: a rewrite to the core rules (a PyPI client library, full
test coverage, the quality scale) and a review by the Home Assistant team.

**Tests:** see the README (Development). They run against the processor's control software, so a change to its API
should be checked here before a processor release.
