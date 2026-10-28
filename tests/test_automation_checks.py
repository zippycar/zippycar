"""Each automation check, with a small example that should trigger it and one that shouldn't."""

import pytest

from .conftest import automation_config, codes, findings_for

GOOD_TRIGGER = """
    - trigger: state
      entity_id: binary_sensor.door
      from: "off"
      to: "on"
"""


def auto(body: str, alias: str = "Test", auto_id: str = "t1") -> str:
    return f"- id: {auto_id}\n  alias: {alias}\n" + "\n".join("  " + line for line in body.strip("\n").splitlines()) + "\n"


SIMPLE_ACTION = """actions:
  - action: light.turn_on
    target:
      entity_id: light.hall
"""

CASES = [
    # (code, bad automations.yaml, good automations.yaml)
    ("missing-id", "- alias: No id\n  triggers: []\n  actions: []\n", auto("triggers: []\nactions: []")),
    ("missing-alias", "- id: a\n  triggers: []\n  actions: []\n", auto("triggers: []\nactions: []")),
    ("duplicate-id", auto(SIMPLE_ACTION, "A", "same") + auto(SIMPLE_ACTION, "B", "same"),
     auto(SIMPLE_ACTION, "A", "one") + auto(SIMPLE_ACTION, "B", "two")),
    ("duplicate-alias", auto(SIMPLE_ACTION, "Same", "a") + auto(SIMPLE_ACTION, "Same", "b"),
     auto(SIMPLE_ACTION, "One", "a") + auto(SIMPLE_ACTION, "Two", "b")),
    ("unknown-automation-key", auto("triggerz: []\n" + SIMPLE_ACTION), auto("triggers: []\n" + SIMPLE_ACTION)),
    ("both-old-and-new-keys", auto("trigger: []\ntriggers: []\n" + SIMPLE_ACTION), auto("triggers: []\n" + SIMPLE_ACTION)),
    ("no-triggers", auto("triggers: []\n" + SIMPLE_ACTION), auto("triggers:\n" + GOOD_TRIGGER + SIMPLE_ACTION)),
    ("no-actions", auto("triggers:\n" + GOOD_TRIGGER + "actions: []"), auto("triggers:\n" + GOOD_TRIGGER + SIMPLE_ACTION)),
    ("invalid-mode", auto("mode: paralel\ntriggers: []\n" + SIMPLE_ACTION), auto("mode: parallel\ntriggers: []\n" + SIMPLE_ACTION)),
    ("max-ignored", auto("mode: single\nmax: 4\ntriggers: []\n" + SIMPLE_ACTION), auto("mode: queued\nmax: 4\ntriggers: []\n" + SIMPLE_ACTION)),
    ("initial-state-off", auto("initial_state: false\ntriggers: []\n" + SIMPLE_ACTION), auto("initial_state: true\ntriggers: []\n" + SIMPLE_ACTION)),
    ("old-plural-keys", auto("trigger: []\n" + SIMPLE_ACTION), auto("triggers: []\n" + SIMPLE_ACTION)),
    ("old-platform-key", auto("triggers:\n  - platform: state\n    entity_id: binary_sensor.door\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: state\n    entity_id: binary_sensor.door\n" + SIMPLE_ACTION)),
    ("old-service-key", auto("triggers: []\nactions:\n  - service: light.turn_on\n"),
     auto("triggers: []\nactions:\n  - action: light.turn_on\n")),
    ("old-data-template", auto("triggers: []\nactions:\n  - action: light.turn_on\n    data_template:\n      brightness: 3\n"),
     auto("triggers: []\nactions:\n  - action: light.turn_on\n    data:\n      brightness: 3\n")),
    ("single-mode-wait", auto("triggers:\n" + GOOD_TRIGGER + "actions:\n  - delay: 60\n"),
     auto("mode: restart\ntriggers:\n" + GOOD_TRIGGER + "actions:\n  - delay: 60\n")),
    ("wait-without-timeout", auto("mode: restart\ntriggers:\n" + GOOD_TRIGGER + "actions:\n  - wait_template: \"{{ is_state('light.a', 'on') }}\"\n"),
     auto("mode: restart\ntriggers:\n" + GOOD_TRIGGER + "actions:\n  - wait_template: \"{{ is_state('light.a', 'on') }}\"\n    timeout: 60\n")),
    ("queue-storm", auto("mode: queued\nmax: 100\ntriggers:\n" + GOOD_TRIGGER + SIMPLE_ACTION),
     auto("mode: queued\nmax: 5\ntriggers:\n" + GOOD_TRIGGER + SIMPLE_ACTION)),
    ("restart-storm", auto("mode: restart\ntriggers:\n  - trigger: state\n    entity_id: sensor.kitchen_power\nactions:\n  - delay: 30\n"),
     auto("mode: restart\ntriggers:\n" + GOOD_TRIGGER + "actions:\n  - delay: 30\n")),
    ("self-trigger-loop", auto("triggers:\n  - trigger: state\n    entity_id: light.hall\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: state\n    entity_id: light.hall\n    to: \"on\"\n" + SIMPLE_ACTION)),
    ("chatty-trigger", auto("triggers:\n  - trigger: state\n    entity_id: sensor.outdoor_temperature\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: numeric_state\n    entity_id: sensor.outdoor_temperature\n    below: 5\n" + SIMPLE_ACTION)),
    ("trigger-on-unavailable", auto("triggers:\n  - trigger: state\n    entity_id: light.hall\n    to: unavailable\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: state\n    entity_id: light.hall\n    to: unavailable\n    for: \"00:05:00\"\n" + SIMPLE_ACTION)),
    ("reconnect-false-trigger", auto("triggers:\n  - trigger: state\n    entity_id: binary_sensor.door\n    to: \"on\"\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: state\n    entity_id: binary_sensor.door\n    to: \"on\"\n    not_from: [unavailable, unknown]\n" + SIMPLE_ACTION)),
    ("repeat-no-pause", auto("triggers: []\nactions:\n  - repeat:\n      while: \"{{ true }}\"\n      sequence:\n        - action: light.toggle\n"),
     auto("triggers: []\nactions:\n  - repeat:\n      while: \"{{ true }}\"\n      sequence:\n        - action: light.toggle\n        - delay: 5\n")),
    ("yaml-boolean-state", auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    to: on\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    to: \"on\"\n" + SIMPLE_ACTION)),
    ("yaml-number-time", auto("triggers:\n  - trigger: time\n    at: 7:30\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: time\n    at: \"07:30\"\n" + SIMPLE_ACTION)),
    ("impossible-range", auto("triggers:\n  - trigger: numeric_state\n    entity_id: sensor.t\n    above: 20\n    below: 10\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: numeric_state\n    entity_id: sensor.t\n    above: 10\n    below: 20\n" + SIMPLE_ACTION)),
    ("numeric-on-non-numeric", auto("triggers:\n  - trigger: numeric_state\n    entity_id: switch.pump\n    above: 1\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: numeric_state\n    entity_id: switch.pump\n    attribute: power\n    above: 1\n" + SIMPLE_ACTION)),
    ("same-from-to", auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    from: \"on\"\n    to: \"on\"\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    from: \"off\"\n    to: \"on\"\n" + SIMPLE_ACTION)),
    ("sun-condition-never", auto("triggers: []\nconditions:\n  - condition: sun\n    after: sunset\n    before: sunrise\n" + SIMPLE_ACTION),
     auto("triggers: []\nconditions:\n  - condition: state\n    entity_id: sun.sun\n    state: below_horizon\n" + SIMPLE_ACTION)),
    ("contradictory-conditions",
     auto("triggers: []\nconditions:\n  - condition: state\n    entity_id: light.a\n    state: \"on\"\n  - condition: state\n    entity_id: light.a\n    state: \"off\"\n" + SIMPLE_ACTION),
     auto("triggers: []\nconditions:\n  - condition: state\n    entity_id: light.a\n    state: \"on\"\n  - condition: state\n    entity_id: light.b\n    state: \"off\"\n" + SIMPLE_ACTION)),
    ("all-triggers-disabled", auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    to: \"on\"\n    enabled: false\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    to: \"on\"\n" + SIMPLE_ACTION)),
    ("template-trigger-static", auto("triggers:\n  - trigger: template\n    value_template: \"true\"\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: template\n    value_template: \"{{ is_state('light.a', 'on') }}\"\n" + SIMPLE_ACTION)),
    ("template-not-allowed", auto("triggers:\n  - trigger: state\n    entity_id: \"{{ 'light.a' }}\"\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    to: \"on\"\n" + SIMPLE_ACTION)),
    ("unknown-trigger-id",
     auto("triggers:\n  - trigger: time\n    at: \"07:00\"\n    id: morning\nactions:\n  - choose:\n      - conditions:\n          - condition: trigger\n            id: evening\n        sequence: []\n"),
     auto("triggers:\n  - trigger: time\n    at: \"07:00\"\n    id: morning\nactions:\n  - choose:\n      - conditions:\n          - condition: trigger\n            id: morning\n        sequence: []\n")),
    ("invalid-time", auto("triggers:\n  - trigger: time\n    at: \"24:30\"\n" + SIMPLE_ACTION), auto("triggers:\n  - trigger: time\n    at: \"23:30\"\n" + SIMPLE_ACTION)),
    ("invalid-time-pattern", auto("triggers:\n  - trigger: time_pattern\n    hours: 30\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: time_pattern\n    hours: \"/2\"\n" + SIMPLE_ACTION)),
    ("invalid-duration", auto("mode: restart\ntriggers: []\nactions:\n  - delay: ten minutes\n"),
     auto("mode: restart\ntriggers: []\nactions:\n  - delay:\n      minutes: 10\n")),
    ("invalid-entity-id", auto("triggers:\n  - trigger: state\n    entity_id: Light.Hall\n    to: \"on\"\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: state\n    entity_id: light.hall\n    to: \"on\"\n" + SIMPLE_ACTION)),
    ("unknown-trigger-type", auto("triggers:\n  - trigger: stat\n    entity_id: light.a\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: zwave_js.value_updated\n    entity_id: light.a\n" + SIMPLE_ACTION)),
    ("unknown-condition-type", auto("triggers: []\nconditions:\n  - condition: stat\n" + SIMPLE_ACTION),
     auto("triggers: []\nconditions:\n  - condition: state\n    entity_id: light.a\n    state: \"on\"\n" + SIMPLE_ACTION)),
    ("unknown-action-type", auto("triggers: []\nactions:\n  - servce: light.turn_on\n"), auto("triggers: []\nactions:\n  - action: light.turn_on\n")),
    ("trigger-data-mismatch",
     auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    to: \"on\"\n  - trigger: time\n    at: \"07:00\"\nactions:\n  - action: notify.notify\n    data:\n      message: \"{{ trigger.to_state.name }}\"\n"),
     auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    to: \"on\"\n  - trigger: time\n    at: \"07:00\"\nactions:\n  - action: notify.notify\n    data:\n      message: \"{{ trigger.to_state.name if trigger.platform == 'state' else 'time' }}\"\n")),
    ("trigger-outside-condition",
     auto("triggers:\n  - trigger: time\n    at: \"06:00\"\nconditions:\n  - condition: time\n    after: \"07:00\"\n    before: \"09:00\"\n" + SIMPLE_ACTION),
     auto("triggers:\n  - trigger: time\n    at: \"23:00\"\nconditions:\n  - condition: time\n    after: \"22:00\"\n    before: \"06:00\"\n" + SIMPLE_ACTION)),
    ("duplicate-trigger", auto("triggers:\n" + GOOD_TRIGGER + GOOD_TRIGGER + SIMPLE_ACTION), auto("triggers:\n" + GOOD_TRIGGER + SIMPLE_ACTION)),
    ("on-off-same-moment",
     auto("triggers: []\nactions:\n  - action: light.turn_on\n    target:\n      entity_id: light.a\n  - action: light.turn_off\n    target:\n      entity_id: light.a\n"),
     auto("triggers: []\nactions:\n  - action: light.turn_on\n    target:\n      entity_id: light.a\n  - delay: 2\n  - action: light.turn_off\n    target:\n      entity_id: light.a\n")),
    ("deep-nesting",
     auto("triggers: []\nactions:\n  - if: \"{{ true }}\"\n    then:\n      - if: \"{{ true }}\"\n        then:\n          - if: \"{{ true }}\"\n            then:\n              - if: \"{{ true }}\"\n                then:\n                  - action: light.toggle\n"),
     auto("triggers: []\nactions:\n  - if: \"{{ true }}\"\n    then:\n      - action: light.toggle\n")),
    ("long-automation", auto("triggers: []\nactions:\n" + "  - action: light.toggle\n" * 31), auto("triggers: []\nactions:\n" + "  - action: light.toggle\n" * 5)),
]


@pytest.mark.parametrize("code,bad,good", CASES, ids=[c[0] for c in CASES])
def test_check_fires_on_bad_and_not_on_good(run, code, bad, good):
    assert code in codes(run(automation_config(bad))), f"{code} should be reported"
    assert code not in codes(run(automation_config(good))), f"{code} should not be reported"


def test_findings_point_at_the_right_line(run):
    text = auto("triggers:\n  - trigger: state\n    entity_id: light.a\n    to: on\n" + SIMPLE_ACTION)
    finding = findings_for(run(automation_config(text)), "yaml-boolean-state")[0]
    assert (finding.file, finding.line) == ("automations.yaml", 6)  # the "to: on" line


def test_sexagesimal_delay_is_a_warning_not_an_error(run):
    result = run(automation_config(auto("mode: restart\ntriggers: []\nactions:\n  - delay: 1:30\n")))
    finding = findings_for(result, "yaml-number-time")[0]
    assert finding.severity == "Warning" and "90 seconds" in finding.detail


def test_max_exceeded_silent_means_dropping_is_deliberate(run):
    result = run(automation_config(auto("max_exceeded: silent\ntriggers:\n" + GOOD_TRIGGER + "actions:\n  - delay: 60\n")))
    assert "single-mode-wait" not in codes(result)


def test_contradictory_automations_same_trigger(run):
    on = auto("triggers:\n" + GOOD_TRIGGER + "actions:\n  - action: light.turn_on\n    target:\n      entity_id: light.porch\n", "On", "a")
    off = auto("triggers:\n" + GOOD_TRIGGER.replace("trigger: state", "platform: state") +
               "actions:\n  - action: light.turn_off\n    target:\n      entity_id: light.porch\n", "Off", "b")
    result = run(automation_config(on + off))
    finding = findings_for(result, "contradictory-automations")[0]
    assert finding.severity == "Error"
    guarded = off.replace("  actions:", "  conditions:\n    - condition: state\n      entity_id: input_boolean.away\n      state: \"on\"\n  actions:")
    finding = findings_for(run(automation_config(on + guarded)), "contradictory-automations")[0]
    assert finding.severity == "Warning"


def test_time_clash_and_sun_overlap(run):
    def timed(alias, at, service, light="light.garden"):
        return auto(f"triggers:\n  - trigger: time\n    at: \"{at}\"\nactions:\n  - action: {service}\n    target:\n      entity_id: {light}\n", alias, alias.lower().replace(" ", "_"))
    sunset = auto("triggers:\n  - trigger: sun\n    event: sunset\nactions:\n  - action: light.turn_on\n    target:\n      entity_id: light.garden\n", "Sunset on", "sun_on")
    result = run(automation_config(timed("Off", "22:00:00", "light.turn_off") + timed("On", "22:00:30", "light.turn_on")))
    assert "time-clash" in codes(result)
    result = run(automation_config(sunset + timed("Off at eight", "20:00:00", "light.turn_off")))
    assert "sun-time-overlap" in codes(result)
    result = run(automation_config(sunset + timed("Off late", "23:45:00", "light.turn_off")))
    assert "sun-time-overlap" not in codes(result)


def test_similar_automations_and_repeated_steps(run):
    text = ""
    for n, room in enumerate(["hall", "landing", "kitchen"]):
        text += auto(f"triggers:\n  - trigger: state\n    entity_id: binary_sensor.{room}_motion\n    to: \"on\"\n"
                     f"actions:\n  - action: light.turn_on\n    target:\n      entity_id: light.{room}\n", room, f"m{n}")
    assert "similar-automations" in codes(run(automation_config(text)))
    steps = "".join(f"  - action: light.turn_off\n    target:\n      entity_id: light.{r}\n" for r in ("a", "b", "c"))
    files = automation_config(auto("triggers: []\nactions:\n" + steps))
    files["scripts.yaml"] = "night:\n  sequence:\n" + "".join("  " + line + "\n" for line in steps.splitlines())
    assert "repeated-steps" in codes(run(files))


def test_scripts_get_step_checks(run):
    files = automation_config("[]\n")
    files["scripts.yaml"] = "bad:\n  sequence:\n    - service: light.turn_on\n    - wait_template: \"{{ false }}\"\nempty:\n  alias: x\n"
    result = run(files)
    assert {"old-service-key", "wait-without-timeout", "script-no-sequence"} <= codes(result)


def test_blueprint_use(run):
    blueprint = """
        blueprint:
          name: Test
          domain: automation
          input:
            needed:
              name: Needed
            optional:
              name: Optional
              default: 1
            unused:
              name: Unused
              default: 2
        triggers:
          - trigger: state
            entity_id: !input needed
        actions:
          - delay: !input optional
          - delay: !input undeclared
    """
    uses = ("- id: a\n  alias: Uses it\n  use_blueprint:\n    path: test/bp.yaml\n    input:\n      optinal: 3\n"
            "- id: b\n  alias: Missing\n  use_blueprint:\n    path: test/nope.yaml\n    input: {}\n")
    result = run(automation_config(uses, {"blueprints/automation/test/bp.yaml": blueprint}))
    assert {"blueprint-input-missing", "blueprint-input-unknown", "blueprint-missing",
            "blueprint-input-undeclared", "blueprint-input-unused"} <= codes(result)
    unknown = findings_for(result, "blueprint-input-unknown")[0]
    assert 'Did you mean "optional"' in unknown.detail
