# Changelog

All notable changes to ha-config-doctor are listed here, newest first.
Version numbers follow the usual pattern: the first number changes for big changes, the last for small fixes.

## 1.1.0 — 2026-10-28

Corrections after the owner pointed out that the built-in knowledge of removed features was out of date
for their system (Home Assistant OS 18.4, Core 2026.10.4).

### Changed

- **Every fact about removed, retired and changed features now lives in `data/ha_rules.yaml`**, not in
  the program. Each rule records the version where it was marked for retirement, the version where it
  was removed (or changed), a plain-English explanation and fix, an official source page, the date it
  was reviewed, whether it has been verified, and where the information came from. A test fails if a
  retired feature's name is written into the code instead.
- **Findings depend on your Home Assistant version**, read from the config folder's `.HA_VERSION` file or
  given with `--ha-version`: a removed feature is an Error, one marked for retirement is a Warning, a
  behaviour change is a Warning where it matters, and anything that only happens in a later version is a
  Tidy-up. If no version is found, the newest one the rules cover (2026.10) is assumed and the report
  says so.
- **Old-style template entities** (`platform: template` for alarm_control_panel, binary_sensor, cover,
  fan, light, lock, sensor, switch, vacuum and weather) are now **Errors from 2026.6**, each with a
  suggested replacement written the current way (`template:` with `name`, `unique_id`,
  `default_entity_id`, `state` and so on). Automations, templates and conditions that still use those
  entities are reported too, because the entities no longer exist.
- The report's summary shows the Home Assistant version used and how many rules are unverified; each
  rule-based finding shows the affected versions, the official source and its verification status.
- Check codes `removed-integration`, `deprecated-integration` and `deprecated-option` are replaced by
  `retired-integration`, `retired-setting`, `retired-action` and `behaviour-change`.

### Added

- Rules for: `device_tracker.see` being retired (from 2026.5, removal planned for 2027.5) with template
  device trackers as the replacement (template device trackers are now recognised as entities);
  `mqtt.publish`, `mqtt.dump`, `synology_dsm.reboot` and `synology_dsm.shutdown` needing an administrator
  from 2026.10 (reported in scripts, which people can run from dashboards); integrations removed in
  2026.10 (Dublin Bus, Etherscan, Melnor RainCloud, Orange and Rockland Utility, Sigfox, SolarEdge Local,
  Travis-CI, Zestimate) and switched off in 2026.10 (Linode, Tank Utility); VLC removed in 2026.9;
  InfluxDB YAML connection settings removed in 2026.9; light `color_temp` (mireds) and `kelvin` removed
  in 2026.3; Snapcast's own grouping actions removed in 2026.3.
- A "still supported" list in the rules file: trigger IDs written in YAML keep working in 2026.10, and a
  test makes sure they are never reported.
- `list-rules` command, and `--ha-version` and `--rules` options.
- GitHub Actions workflow running the tests on Windows and Ubuntu (Python 3.10 and 3.13), plus the
  README's Windows commands exactly as written in Windows PowerShell 5.1.

### Fixed

- Tests now write their sample files byte for byte, so Windows doesn't change their line endings, and
  `.gitattributes` keeps every checkout's line endings the same as on the Raspberry Pi.

### Not verified

- home-assistant.io could not be reached while these rules were written, so **every rule is marked
  "unverified"**. Rules from the owner are marked as such; the 2026.1–2026.10 rules beyond those come
  from web-search summaries, and older ones from the author's memory (see `docs/CHECKS.md`).

## 1.0.0 — 2026-10-28

First release, written for Home Assistant OS / Core 2026.10.

### Added

- **`check` command**: reads a copy of a Home Assistant configuration folder (never changing it) and
  writes a report as `report.html` and `report.md`, starting with a one-page summary and then listing
  every finding grouped by severity (Error, Warning, Tidy-up), with the file and line number, a
  plain-English explanation and a suggested fix.
- **99 checks** (listed in `docs/CHECKS.md`), covering:
  - files and includes: layout mistakes, files that aren't UTF-8, duplicate settings, missing or
    wrongly-capitalised `!include` targets, include loops, `.yml` files that include folders ignore,
    `!secret` names missing from `secrets.yaml`, `!env_var`, unknown `!` tags, `!input` outside
    blueprints, passwords typed into files, unused YAML files, `automations.yaml`/`scripts.yaml`/
    `scenes.yaml` not connected;
  - blueprints: missing blueprint files, settings not filled in, unknown settings, undeclared and unused
    `!input` names;
  - automations: missing or duplicate ids and aliases, unknown settings, both old and new key names,
    no triggers or actions, invalid modes, `max:` with no effect, `initial_state: false`, automations
    switched off;
  - old syntax: `trigger`/`condition`/`action` → plural, `platform:` → `trigger:`, `service:` →
    `action:`, `data_template`/`service_template`; retired integrations, platforms and options
    (including legacy template entities, `platform: mqtt`, `weather.get_forecast`, the weather
    `forecast` attribute, `white_value`, `color_temp`, `hide_entity`, `http: base_url` and more);
  - timing: waits and delays in `single` mode that drop re-triggers, waits without timeouts, queue and
    restart storms, self-triggering loops, very busy triggers with no conditions, triggers on
    `unavailable`/`unknown`, triggers that fire when a device reconnects, repeat loops with no pause,
    time triggers that clash, and sunrise/sunset times that swap order with fixed times during the year;
  - things that can never happen: unquoted `on`/`off`/`yes`/`no`, unquoted times read as numbers,
    impossible numeric ranges, number checks on on/off entities, identical `from`/`to`,
    "after sunset and before sunrise", contradictory conditions, all triggers disabled, static template
    triggers, templates where none are allowed, unknown trigger ids, impossible times, time patterns and
    durations, badly written entity names, unknown trigger/condition/step types, `trigger.to_state` with
    triggers that don't have it, trigger times outside the time condition, duplicate triggers;
  - clashes: automations that switch the same entity on and off from the same trigger, and on-then-off
    with no pause;
  - templates: typing mistakes (using Jinja's own parser), `float`/`int`/`round`/`as_timestamp` and
    similar without a default, text compared with numbers, `states.x.y.state`, and templates that look
    at entities that don't exist;
  - references: missing scripts, scenes, helpers, automations, `shell_command`/`rest_command`/
    `python_script` actions, entities and devices; disabled, deleted and orphaned entities; unused
    helpers;
  - size: very long automations, deep nesting, near-identical automations (blueprint candidates) and
    repeated groups of steps (script candidates).
- **Entity cross-check** against `.storage/core.entity_registry`, `core.device_registry` and
  `core.restore_state` (read-only), with "did you mean …?" suggestions.
- **`tidy` command**: writes corrected copies to a new folder, keeping comments, with a change log
  (`CHANGES.html` and `CHANGES.md`) explaining each change and why. Every tidied file is re-read with
  Home Assistant's rules and compared with the original; if the meaning or comments would change, the
  change is not made. Uncertain problems are only reported.
- **`list-checks` command**.
- **Privacy**: values in `secrets.yaml` are never read (only names); `.storage` login files are never
  opened; passwords, tokens, e-mail addresses, phone numbers and network addresses are hidden in every
  report; the program never uses the internet.
- Made-up `samples/` that set off every check, a healthy sample that sets off none, a full pytest suite
  and a plain-English README with copy-and-paste steps for Windows 11.
