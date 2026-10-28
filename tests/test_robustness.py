"""Odd but possible shapes of automation must never crash the doctor."""

import pytest

from .conftest import automation_config

ODD = [
    "- id: a\n  alias: A\n  trigger:\n    platform: state\n    entity_id: light.a\n  action:\n    service: light.turn_on\n",
    "- id: b\n  alias: 42\n  triggers: \"{{ true }}\"\n  conditions: \"{{ is_state('light.a', 'on') }}\"\n  actions: \"{{ 1 }}\"\n",
    "- id: c\n  alias: C\n  triggers:\n    - null\n    - 5\n    - [1, 2]\n  conditions:\n    - null\n    - [x]\n  actions:\n    - null\n    - 7\n    - [a]\n",
    "- id: d\n  alias: D\n  mode: [single]\n  max: lots\n  triggers:\n    - trigger: time\n      at:\n        entity_id: sensor.alarm\n        offset: \"-00:10:00\"\n  actions:\n    - delay:\n        minutes: \"{{ 5 }}\"\n    - repeat:\n        count: 3\n        sequence: \"{{ x }}\"\n",
    "- id: e\n  alias: E\n  triggers:\n    - trigger: numeric_state\n      entity_id: [sensor.a, 5, null]\n      above: input_number.low\n      below: sensor.high\n  actions:\n    - choose: \"{{ x }}\"\n    - if: []\n    - parallel:\n        - sequence: [{action: light.toggle}]\n        - action: light.toggle\n",
    "- id: f\n  alias: F\n  triggers:\n    - triggers:\n        - trigger: state\n          entity_id: light.a\n  actions:\n    - wait_for_trigger: {trigger: state, entity_id: light.a}\n    - action: \"{{ 'light.turn_' ~ 'on' }}\"\n      target: \"{{ {'entity_id': 'light.a'} }}\"\n",
    "- {}\n- []\n- just text\n- null\n",
    "{}\n",
    "",
    "- id: g\n  alias: G\n  use_blueprint: nonsense\n",
    "- id: h\n  alias: H\n  use_blueprint:\n    path: 5\n    input: [1]\n",
    "- id: i\n  alias: I\n  variables: [1]\n  triggers:\n    - trigger: time_pattern\n      minutes: [1]\n      seconds: \"/x\"\n  actions:\n    - condition: and\n      conditions: \"{{ true }}\"\n    - condition: or\n    - not: [null]\n",
]


@pytest.mark.parametrize("text", ODD)
def test_odd_automations_do_not_crash(run, text):
    result = run(automation_config(text, storage=["light.a"]))
    assert result.unfinished == []


def test_odd_scripts_and_sections_do_not_crash(run):
    files = automation_config("[]\n")
    files["scripts.yaml"] = "a: null\nb: [1]\nc:\n  sequence: \"{{ x }}\"\nd:\n  sequence:\n    - null\n"
    files["configuration.yaml"] += ("sensor: [1, null, {platform: template, sensors: [x]}]\ntemplate: {sensor: 1}\n"
                                    "input_boolean: [x]\ngroup: 5\nmqtt: [1]\nscene: {name: x}\nzone: 3\nperson: [x]\n")
    assert run(files).unfinished == []
