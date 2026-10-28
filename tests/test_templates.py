"""Template analysis uses Jinja's own parser."""

import pytest

from ha_config_doctor.templates import analyse

from .conftest import automation_config, codes


@pytest.mark.parametrize("template,expected", [
    ("{{ states('sensor.x') | float }}", ["| float"]),
    ("{{ states('sensor.x') | float(0) }}", []),
    ("{{ states('sensor.x') | float(default=0) }}", []),
    ("{{ float(states('sensor.x')) }}", ["float()"]),
    ("{{ float(states('sensor.x'), 0) }}", []),
    ("{{ states('sensor.x') | int }}", ["| int"]),
    ("{{ trigger.to_state.state | int }}", ["| int"]),
    ("{{ now().hour | int }}", []),
    ("{{ repeat.index | int }}", []),
    ("{{ states('sensor.x') | round(1) }}", ["| round"]),
    ("{{ states('sensor.x') | float(0) | round(1) }}", []),
    ("{{ as_timestamp(states('sensor.next_alarm')) }}", ["as_timestamp()"]),
    ("{{ as_timestamp(now()) }}", []),
    ("{{ states('sensor.t') | as_timestamp }}", ["| as_timestamp"]),
])
def test_missing_defaults(template, expected):
    assert analyse(template).no_default == expected


def test_text_compared_with_numbers():
    assert analyse("{{ states('sensor.t') > 20 }}").text_number_compare
    assert analyse("{{ 20 < states.sensor.t.state }}").text_number_compare
    assert analyse("{{ states('sensor.t') == 5 }}").text_number_compare
    assert not analyse("{{ states('sensor.t') | float(0) > 20 }}").text_number_compare
    assert not analyse("{{ states('sensor.t') == 'on' }}").text_number_compare


def test_entity_references_and_direct_state_access():
    info = analyse("{{ is_state('light.a', 'on') and states.sensor.b.state == 'x' and state_attr('climate.c', 'temperature') "
                   "and states['switch.d'] and expand(['group.e']) and 'cover.f' }}")
    found = {entity for entity, _ in info.entity_refs}
    assert {"light.a", "sensor.b", "climate.c", "switch.d", "group.e", "cover.f"} <= found
    assert info.direct_state == ["sensor.b"]


def test_syntax_errors_and_ha_extensions():
    assert analyse("{{ states('x') | float( }}").syntax_error is not None
    assert analyse("{% for x in y %}{% if x %}{% break %}{% endif %}{% endfor %}").syntax_error is None
    assert analyse("{% set n = namespace(a=1) %}{% do n.a %}").syntax_error is None


def test_trigger_variables_and_guards():
    assert analyse("{{ trigger.to_state.state }}").trigger_attrs == {"to_state"}
    assert analyse("{{ trigger.to_state.state if trigger.platform == 'state' }}").trigger_guarded


def test_forecast_attribute():
    assert analyse("{{ state_attr('weather.home', 'forecast') }}").forecast_attribute
    assert analyse("{{ states.weather.home.attributes.forecast }}").forecast_attribute


def test_templates_everywhere_are_checked(run):
    files = automation_config("[]\n")
    files["configuration.yaml"] += "template:\n  - sensor:\n      - name: Bad\n        state: \"{{ states('sensor.x') | float }}\"\n"
    assert "template-no-default" in codes(run(files))


def test_syntax_error_line_inside_block_template(run):
    text = ("- id: a\n  alias: A\n  triggers: []\n  actions:\n    - action: notify.notify\n      data:\n        message: |\n"
            "          first line\n          {{ broken( }}\n")
    finding = [f for f in run(automation_config(text)).findings.items if f.code == "template-syntax-error"][0]
    assert finding.line == 9
