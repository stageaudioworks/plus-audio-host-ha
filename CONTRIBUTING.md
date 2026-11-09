# Releasing and publishing

Since Home Assistant 2026.11, HACS is built into Home Assistant as the **Marketplace**. It reads the same catalog
([hacs/default](https://github.com/hacs/default)) and the same `hacs.json`, so one repository serves both the
Marketplace and HACS on Home Assistant 2026.10 and older. Publisher docs:
[contributors.home-assistant.io/marketplace](https://contributors.home-assistant.io/marketplace/how-it-works/).

## A release

1. Raise `version` in `custom_components/plus_audio_host/manifest.json` and add it to `CHANGELOG.md`.
2. If the release needs a newer Home Assistant, raise `homeassistant` in `hacs.json` (users on older versions are then
   not offered it).
3. Publish a GitHub **release** (a bare tag doesn't count) whose tag is exactly the manifest version, for example `0.3.0`.
   The release text is what users see under **Settings → Updates**: put anything they must do at the top.
4. Keep old releases published; users can go back to them from the repository's menu.

A pre-release on GitHub reaches only users who turned on the repository's **Pre-release** switch.

## Brand images

The icon and logo ship in `custom_components/plus_audio_host/brand/` (Home Assistant 2026.3+ reads them from there; no
pull request to home-assistant/brands is needed): `icon.png` 256×256, `icon@2x.png` 512×512, `logo.png` /
`logo@2x.png`, and `dark_` versions of each, transparent PNG. They are made from the Plus Audio wordmark.

## The Marketplace catalog

Without the catalog, anyone can add the repository by link (see the README). To appear in the Marketplace search:

1. The repository is public, with a description, topics and issues on, and at least one full release.
2. The `Validate` workflow passes here with nothing ignored (HACS action and hassfest).
3. Fork [hacs/default](https://github.com/hacs/default), branch from `master`, add `stageaudioworks/plus-audio-host-ha`
   to the `integration` file in alphabetical order, and open the pull request **from a personal GitHub account**
   (not the organisation), filling in the template with links to the latest release and to passing HACS and hassfest
   runs. An incomplete template is closed without notice; don't request reviews from people.
4. Review takes months. After it merges, the Marketplace picks it up within a day.

## Home Assistant core

Built in, with no Marketplace step, is a later choice: a rewrite to the core rules (a PyPI client library, full test
coverage, the quality scale) and a review by the Home Assistant team. The `brand/` folder then moves to
home-assistant/brands.

## Tests

See the README (Development). They run against the processor's control software, so a change to its API should be
checked here before a processor release.
