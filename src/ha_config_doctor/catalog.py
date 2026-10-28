"""Every check the doctor knows about, written in plain English.

Each check has a code (used in the report and tests), a severity, a short
title, an explanation of *why it matters*, and a suggested fix. Individual
findings add the specific details (which automation, which entity, …).
"""

from __future__ import annotations

from dataclasses import dataclass

from .redact import redact_text

ERROR = "Error"
WARNING = "Warning"
TIDY = "Tidy-up"
SEVERITIES = (ERROR, WARNING, TIDY)
SEVERITY_ORDER = {ERROR: 0, WARNING: 1, TIDY: 2}
SEVERITY_MEANING = {
    ERROR: "Something is broken, or will not work the way it looks like it should. Fix these first.",
    WARNING: "Probably works, but is likely to misbehave sometimes, or is a trap waiting to go off.",
    TIDY: "Works today. Tidying it makes things easier to look after and ready for future versions.",
}


@dataclass(frozen=True)
class Check:
    code: str
    severity: str  # the usual severity; a finding may raise or lower it
    group: str
    title: str
    why: str
    fix: str
    tidy_fixes: bool = False  # True when "tidy" mode corrects this automatically


CHECKS: dict[str, Check] = {}


def _check(code: str, severity: str, group: str, title: str, why: str, fix: str, tidy_fixes: bool = False) -> None:
    assert code not in CHECKS, code
    CHECKS[code] = Check(code, severity, group, title, why, fix, tidy_fixes)


FILES = "Files and settings"
AUTOS = "Automations"
TIMING = "Timing and repeats"
LOGIC = "Things that can never happen"
CLASH = "Automations that fight each other"
TEMPL = "Templates (the bits in {{ }})"
REFS = "Names that point at nothing"
OLD = "Old or retired features"
SIZE = "Size and structure"
# Most serious first: problems that stop files loading, then things that can never work, and so on.
GROUP_ORDER = {name: index for index, name in enumerate((FILES, LOGIC, REFS, AUTOS, CLASH, TEMPL, OLD, TIMING, SIZE))}

# ---------------------------------------------------------------- files
_check("no-configuration-yaml", ERROR, FILES, "No configuration.yaml in this folder",
       "Every Home Assistant configuration folder has a file called configuration.yaml. Without it, this probably isn't the right folder, and very little can be checked.",
       "Point the doctor at the folder that contains configuration.yaml (on the Raspberry Pi this is the \"config\" folder).")
_check("yaml-syntax-error", ERROR, FILES, "A file can't be read because of a layout mistake",
       "Home Assistant can't understand this file because something in its layout (the spaces, colons, dashes and quotes) breaks the rules. Everything in the file is ignored until it is fixed, and if it is configuration.yaml Home Assistant may start in \"safe mode\".",
       "Look at the line shown and the line just above it. Common causes: a missing space after a colon, a TAB instead of spaces, or text containing a colon that needs quotes around it.")
_check("file-not-utf8", ERROR, FILES, "A file isn't saved as ordinary text (UTF-8)",
       "Home Assistant expects every YAML file to be saved as UTF-8 text. This one contains characters in another format, so Home Assistant will refuse to read it.",
       "Open the file in Notepad, choose File > Save As, set Encoding to UTF-8 and save.")
_check("duplicate-key", WARNING, FILES, "The same setting appears twice",
       "When the same name appears twice in one block, Home Assistant silently uses the last one and throws the first away. This is almost always a copy-and-paste slip, and it means some of what you wrote is being ignored.",
       "Delete or merge the duplicate so the setting appears only once.")
_check("include-missing", ERROR, FILES, "An !include points at something that isn't there",
       "An !include line tells Home Assistant to read another file or folder. The one named here doesn't exist (or its capital letters don't match — the Raspberry Pi cares about capitals even though Windows doesn't), so Home Assistant will report a configuration error.",
       "Correct the name in the !include line, or create the missing file or folder.")
_check("include-outside-folder", ERROR, FILES, "An !include points outside the config folder",
       "This !include reaches outside the configuration folder. On the Raspberry Pi that location almost certainly doesn't exist, and the doctor deliberately doesn't look outside the folder you gave it.",
       "Move the file into the config folder and change the !include to a name relative to the file that includes it.")
_check("include-loop", ERROR, FILES, "Files include each other in a circle",
       "File A includes file B, which (directly or through others) includes file A again. Home Assistant can't load a circle like this.",
       "Remove one of the !include lines that closes the circle.")
_check("include-wrong-content", WARNING, FILES, "A file in an include folder is silently skipped",
       "!include_dir_merge_list only takes files that contain a list (lines starting with -), and !include_dir_merge_named only takes files that contain named blocks. A file of the wrong kind is skipped without any error message.",
       "Make the file the same shape as the others in that folder.")
_check("yml-ignored", WARNING, FILES, "A .yml file in an include folder is ignored",
       "The !include_dir_… commands only read files whose names end in .yaml. A file ending in .yml in the same folder is silently ignored, so anything in it does nothing.",
       "Rename the file so it ends in .yaml.")
_check("wrong-include-type", ERROR, FILES, "A section has the wrong shape",
       "Some sections must be a list (automations, scenes) and others a set of named blocks (scripts, helpers). This one is the other shape, often because the wrong !include_dir_… command was used.",
       "For automations use !include automations.yaml, !include_dir_list or !include_dir_merge_list. For scripts use !include scripts.yaml, !include_dir_named or !include_dir_merge_named.")
_check("secret-missing", ERROR, FILES, "A !secret name isn't in secrets.yaml",
       "The file asks for a value from secrets.yaml by name, but secrets.yaml has no entry with that name. Home Assistant will refuse to load this part of the configuration.",
       "Add the missing name to secrets.yaml (the doctor never reads the values there — only the names), or correct the spelling.")
_check("secrets-file-missing", ERROR, FILES, "!secret is used but there is no secrets.yaml",
       "!secret takes a value from a file called secrets.yaml, but there isn't one in this folder.",
       "Create secrets.yaml in the config folder, or copy it across if your copy of the folder is missing it.")
_check("secrets-included", WARNING, FILES, "secrets.yaml is read with !include",
       "secrets.yaml is meant to be used only through !secret. Including it directly mixes your passwords into the rest of the configuration. The doctor has not read it.",
       "Remove the !include of secrets.yaml and use !secret name for each value instead.")
_check("env-var-used", WARNING, FILES, "!env_var is used",
       "!env_var reads a value from the computer's environment. On Home Assistant OS (the Raspberry Pi set-up) you can't set these, so without a default value this fails.",
       "Put the value in secrets.yaml and use !secret instead.")
_check("unknown-tag", ERROR, FILES, "An unknown ! command is used",
       "Words starting with ! are special commands. Home Assistant only knows !include, !include_dir_list, !include_dir_named, !include_dir_merge_list, !include_dir_merge_named, !secret, !input and !env_var. Anything else stops the file loading.",
       "Check the spelling of the ! command.")
_check("input-outside-blueprint", ERROR, FILES, "!input is used outside a blueprint",
       "!input only works inside blueprint files (in the blueprints folder). Anywhere else Home Assistant can't fill it in.",
       "Replace the !input with the real value.")
_check("inline-secret", WARNING, FILES, "A password or key is typed straight into a file",
       "This looks like a password, token or private key typed directly into the file. Anyone you share the file with (for example when asking for help on a forum) will see it. The doctor has hidden the value in this report.",
       "Move the value into secrets.yaml and write !secret some_name here instead.")
_check("file-not-used", TIDY, FILES, "A YAML file isn't used by Home Assistant",
       "Nothing in configuration.yaml includes this file, so Home Assistant never reads it. It may be an old copy, or something you meant to switch on.",
       "If you still need it, add an !include for it. If not, you can move it out of the config folder.")
_check("ui-file-not-included", WARNING, FILES, "A file the editor uses isn't connected",
       "Automations, scripts and scenes you make in the Home Assistant screens are saved in automations.yaml, scripts.yaml and scenes.yaml. configuration.yaml must include these files or what you make in the editor won't load.",
       "Add the line shown in the details to configuration.yaml.")

# ---------------------------------------------------------------- blueprints
_check("blueprint-missing", ERROR, FILES, "An automation uses a blueprint that isn't there",
       "This automation is built from a blueprint file that can't be found in the blueprints folder, so the automation can't be created.",
       "Re-import the blueprint (Settings > Automations & scenes > Blueprints) or correct the path.")
_check("blueprint-input-missing", ERROR, FILES, "A blueprint setting hasn't been filled in",
       "The blueprint needs this setting and has no default, but the automation doesn't provide it, so Home Assistant can't create the automation.",
       "Open the automation in the editor and fill in the missing setting.")
_check("blueprint-input-unknown", WARNING, FILES, "An automation fills in a blueprint setting that doesn't exist",
       "The automation provides a setting the blueprint doesn't have — usually a spelling slip, or the blueprint was updated and the setting renamed. The value is ignored.",
       "Open the automation in the editor and check its settings.")
_check("blueprint-input-undeclared", ERROR, FILES, "A blueprint uses a setting it never lists",
       "The blueprint uses !input with a name that isn't listed in its input section, so Home Assistant rejects the blueprint.",
       "Add the setting to the blueprint's input list, or correct the name.")
_check("blueprint-input-unused", TIDY, FILES, "A blueprint lists a setting it never uses",
       "The blueprint asks for this setting but never uses it, so filling it in does nothing.",
       "Remove the setting from the blueprint, or use it.")

# ---------------------------------------------------------------- automation basics
_check("missing-id", WARNING, AUTOS, "An automation has no id",
       "Without an id, an automation can't be opened in the automation editor and Home Assistant keeps no traces (the step-by-step record you use to find out why it did or didn't run).",
       "Add a line such as   id: \"hall_light_motion\"   with a name not used by any other automation.")
_check("duplicate-id", ERROR, AUTOS, "Two items share the same id",
       "Every automation (and every scene) must have its own id. When two share one, Home Assistant mixes them up: editing one can overwrite the other, and one of them may not load at all.",
       "Give one of them a new, unique id.")
_check("missing-alias", TIDY, AUTOS, "An automation has no name (alias)",
       "Without an alias the automation shows up with a meaningless name, which makes it hard to find in lists and logs.",
       "Add a line such as   alias: \"Hall light on when motion\".")
_check("duplicate-alias", WARNING, AUTOS, "Two automations have the same name",
       "Two automations with the same alias look identical in lists and logs, and Home Assistant has to add _2 to the end of one's entity name. It's easy to edit or switch off the wrong one.",
       "Give each automation its own name.")
_check("unknown-automation-key", ERROR, AUTOS, "An automation has a setting Home Assistant doesn't recognise",
       "Home Assistant checks every setting in an automation and rejects the whole automation if it finds one it doesn't know. This is usually a spelling slip.",
       "Correct the spelling (the details suggest the closest known setting) or remove the line.")
_check("both-old-and-new-keys", ERROR, AUTOS, "Both the old and the new name for the same part are used",
       "The automation has, for example, both trigger: and triggers:. Home Assistant won't accept both at once.",
       "Merge the two lists under the new name (triggers:, conditions:, actions:).")
_check("no-triggers", ERROR, AUTOS, "An automation has no triggers",
       "Triggers are what start an automation. With none, it never runs by itself.",
       "Add a trigger, or if you only ever run it by hand, make it a script instead.")
_check("no-actions", ERROR, AUTOS, "An automation has no actions",
       "Actions are what the automation does. With none, it does nothing (and Home Assistant may reject it).",
       "Add the actions, or delete the automation.")
_check("invalid-mode", ERROR, AUTOS, "An automation or script has an unknown mode",
       "mode must be one of single, restart, queued or parallel. Anything else is rejected.",
       "Correct the mode.")
_check("max-ignored", TIDY, AUTOS, "max: is set but has no effect",
       "max: only matters when mode is queued or parallel. With single or restart it is ignored.",
       "Remove the max: line, or change the mode if you meant queued or parallel.")
_check("initial-state-off", WARNING, AUTOS, "An automation is switched off every time Home Assistant starts",
       "initial_state: false switches the automation off at every restart, whatever you set in the screens. People often forget it is there.",
       "Remove the initial_state line unless you really want this.")
_check("automation-switched-off", TIDY, AUTOS, "An automation is switched off",
       "Home Assistant's saved state shows this automation is turned off, so it never runs.",
       "If you no longer need it, delete it; otherwise switch it back on.")
_check("script-no-sequence", ERROR, AUTOS, "A script has no steps",
       "Every script needs a sequence: list of steps. Without one Home Assistant rejects the script.",
       "Add the steps under sequence:.")

# ---------------------------------------------------------------- old syntax (tidy fixes)
_check("old-plural-keys", TIDY, OLD, "Old names: trigger / condition / action",
       "Since Home Assistant 2024.10 the three main parts of an automation are called triggers:, conditions: and actions:. The old singular names still work, but the editor and the documentation now use the new ones.",
       "Rename them. Tidy mode does this for you.", tidy_fixes=True)
_check("old-platform-key", TIDY, OLD, "Old name: platform: inside a trigger",
       "Since Home Assistant 2024.10, each trigger starts with trigger: (for example trigger: state) instead of platform:. The old name still works for now.",
       "Rename platform: to trigger:. Tidy mode does this for you.", tidy_fixes=True)
_check("old-service-key", TIDY, OLD, "Old name: service: in an action",
       "Since Home Assistant 2024.8, an action that does something (like light.turn_on) is written action: instead of service:. The old name still works for now.",
       "Rename service: to action:. Tidy mode does this for you.", tidy_fixes=True)
_check("old-data-template", TIDY, OLD, "Old names: data_template / service_template",
       "Templates have been allowed directly in data: and action: for years, so data_template: and service_template: are no longer needed.",
       "Rename data_template: to data: and service_template: to action:. Tidy mode does this for you.", tidy_fixes=True)
_check("removed-integration", ERROR, OLD, "An integration that no longer exists",
       "This section of configuration.yaml sets up something that has been removed from Home Assistant. It does nothing now and may show an error.",
       "Follow the suggestion in the details, then delete the section.")
_check("deprecated-integration", WARNING, OLD, "Set up the old way",
       "This is set up in YAML in a way Home Assistant has retired or is retiring. It may already have been moved into the Home Assistant screens for you, or it may stop working in a future update.",
       "Follow the suggestion in the details.")
_check("deprecated-option", WARNING, OLD, "An old or retired setting",
       "This setting has been renamed or retired in recent versions of Home Assistant.",
       "Follow the suggestion in the details.")
_check("legacy-template-entity", ERROR, OLD, "Template sensor written the old way (platform: template)",
       "The old style of template sensor (platform: template under sensor:, binary_sensor: and so on) was marked for retirement in late 2025 and is due to stop working during 2026. On Home Assistant 2026.10 these entities may already have disappeared.",
       "Move it into the template: section, written the new way. The Home Assistant documentation for \"Template\" shows both styles side by side.")

# ---------------------------------------------------------------- timing and repeats
_check("single-mode-wait", WARNING, TIMING, "A wait or delay in a \"single\" automation drops new triggers",
       "In mode: single (the default), while the automation is waiting, any new trigger is thrown away (Home Assistant only writes \"Already running\" in the log). A classic example: a motion light with a 5-minute delay won't restart its timer when you walk past again, so the light goes off while you're still there.",
       "Use mode: restart if each new trigger should start again (good for motion lights), or mode: queued if every trigger must be handled. If dropping them is what you want, add max_exceeded: silent to say so.")
_check("wait-without-timeout", WARNING, TIMING, "A wait has no time limit",
       "A wait_template or wait_for_trigger without timeout: waits forever if the thing never happens. While it waits, an automation in single mode ignores every new trigger.",
       "Add timeout: (for example timeout: \"00:30:00\") and, if needed, continue_on_timeout: false.")
_check("queue-storm", WARNING, TIMING, "Risk of a pile-up of runs",
       "In queued or parallel mode every trigger starts (or lines up) another run. With a trigger that fires very often, or a long wait, or a very high max:, runs can pile up, slow Home Assistant down and carry on long after you expect.",
       "Use mode: restart or single, add a condition, lower max:, or trigger on something that changes less often.")
_check("restart-storm", WARNING, TIMING, "Restart mode with a busy trigger may never finish",
       "In restart mode each new trigger stops the run and starts again. If the trigger fires more often than the actions take, the actions after the wait or delay may never be reached.",
       "Use a trigger that changes less often (for example with to: and for:), or use mode: single or queued.")
_check("self-trigger-loop", WARNING, TIMING, "An automation changes the thing that triggers it",
       "The automation is triggered by an entity and then changes that same entity. That change can trigger the automation again — and again — creating a loop.",
       "Add a condition, trigger only on specific changes (to: / from:), or watch a different entity.")
_check("chatty-trigger", WARNING, TIMING, "Triggers on something that changes all the time, with no conditions",
       "This trigger fires on every small change of a busy sensor (for example every power or temperature reading, or every attribute update), and the automation has no conditions to filter them. It may run hundreds of times a day.",
       "Trigger on specific values instead (numeric_state with above:/below:, or state with to:), or add a condition.")
_check("trigger-on-unavailable", WARNING, TIMING, "Triggers when a device goes offline or comes back",
       "This trigger fires on the special states \"unavailable\" or \"unknown\". These happen whenever a device drops off the network and every time Home Assistant restarts, so the automation may run when nothing real has happened.",
       "If you want to know when a device goes offline, add for: \"00:05:00\" so short blips and restarts are ignored. Otherwise use not_from: / not_to: [\"unavailable\", \"unknown\"].")
_check("reconnect-false-trigger", TIDY, TIMING, "May fire when a device reconnects",
       "This trigger fires when the entity changes to the given state from anything — including from \"unavailable\" when the device reconnects or Home Assistant restarts. That can look like a real event when it isn't.",
       "Add   not_from: [\"unavailable\", \"unknown\"]   to the trigger.")
_check("repeat-no-pause", WARNING, TIMING, "A repeat loop has no pause",
       "This repeat (while/until) has no delay or wait inside, so it loops as fast as it can until the condition changes. That can make Home Assistant sluggish.",
       "Add a short delay inside the repeat, for example delay: \"00:00:05\".")
_check("time-clash", WARNING, CLASH, "Two automations act on the same thing at almost the same time",
       "These automations are timed within a minute of each other and do opposite things to the same entity. The result depends on which happens to run last.",
       "Move one of the times, or combine them into one automation.")
_check("sun-time-overlap", WARNING, CLASH, "A sunset/sunrise time and a clock time swap order during the year",
       "One automation uses sunrise or sunset, which moves through the year, and another uses a fixed clock time, and they do opposite things to the same entity. At some times of year the fixed time comes first, so (for example) a light switched on at sunset is never switched off, or the other way round.",
       "Use a time condition, or base both on the sun, or combine them into one automation with a check of the time.")

# ---------------------------------------------------------------- logic: can never happen
_check("yaml-boolean-state", ERROR, LOGIC, "on / off / yes / no without quotes",
       "YAML (the file format) turns an unquoted on, off, yes or no into true or false. Home Assistant states are text such as \"on\", so this either gets rejected or never matches — the automation never fires or the condition never passes.",
       "Put quotes around it: \"on\" or \"off\".")
_check("yaml-number-time", ERROR, LOGIC, "A time without quotes is read as a number",
       "YAML (the file format) reads an unquoted time such as 7:30 or 12:30:00 as a number (7:30 becomes 450). Home Assistant then rejects it or reads it as a number of seconds.",
       "Put quotes around times: \"07:30:00\".")
_check("impossible-range", ERROR, LOGIC, "above and below can never both be true",
       "The value must be above the first number and below the second at the same time, but the first is not smaller than the second, so this can never be true.",
       "Swap the numbers, or split it into two triggers/conditions if you meant \"either\".")
_check("numeric-on-non-numeric", ERROR, LOGIC, "A number check on something that isn't a number",
       "numeric_state compares numbers, but this entity's state is a word such as on/off, so it never fires.",
       "Use a state trigger/condition instead, or add attribute: if you meant to watch a number attribute.")
_check("same-from-to", ERROR, LOGIC, "from: and to: are the same",
       "A trigger with the same from: and to: values waits for a change from a state to itself, which never happens.",
       "Correct one of the values.")
_check("sun-condition-never", ERROR, LOGIC, "\"After sunset and before sunrise\" can never be true",
       "A single sun condition only looks at one day, midnight to midnight, so \"after sunset AND before sunrise\" is never true. It's a well-known trap.",
       "Use   condition: state, entity_id: sun.sun, state: \"below_horizon\"   or an \"or\" of two sun conditions.")
_check("contradictory-conditions", ERROR, LOGIC, "Conditions that contradict each other",
       "All of an automation's conditions must be true together, but these two can't both be true at once (for example the same light both \"on\" and \"off\"). The actions never run.",
       "Remove one condition, or use condition: or if either is enough.")
_check("all-triggers-disabled", ERROR, LOGIC, "All of the triggers are switched off",
       "Every trigger in this automation has enabled: false, so nothing can start it.",
       "Switch at least one trigger back on, or delete the automation.")
_check("template-trigger-static", ERROR, LOGIC, "A template trigger that never changes",
       "A template trigger fires when its result changes from false to true. This one has no template code in {{ }}, so its result never changes and it never fires.",
       "Write the test inside {{ }}, or use a state trigger.")
_check("template-not-allowed", ERROR, LOGIC, "A template where Home Assistant doesn't allow one",
       "This setting doesn't accept {{ }} templates, so Home Assistant either rejects it or treats the template text literally, and it never matches.",
       "Use a template trigger or template condition instead, or type the value directly.")
_check("unknown-trigger-id", WARNING, LOGIC, "A check for a trigger id that no trigger has",
       "A condition checks which trigger started the automation, using an id that none of its triggers has. That branch never runs.",
       "Correct the id, or add id: to the trigger you meant.")
_check("invalid-time", ERROR, LOGIC, "An impossible time of day",
       "This time isn't a valid time of day (hours must be 0–23 and minutes 0–59), so Home Assistant rejects it.",
       "Write the time as \"HH:MM\" or \"HH:MM:SS\", for example \"07:30:00\".")
_check("invalid-time-pattern", ERROR, LOGIC, "An impossible time_pattern value",
       "time_pattern values must be within range (hours 0–23, minutes and seconds 0–59) or written like \"/5\" for \"every 5\". This one isn't, so it is rejected or never matches.",
       "Correct the value, for example minutes: \"/5\" for every five minutes.")
_check("invalid-duration", ERROR, LOGIC, "A length of time Home Assistant can't understand",
       "Delays, waits and for: must be written as \"HH:MM:SS\", a number of seconds, or with hours:/minutes:/seconds:. Wording like \"5 minutes\" is rejected.",
       "Write it as, for example, \"00:05:00\" or  minutes: 5.")
_check("invalid-entity-id", ERROR, LOGIC, "A badly written entity name",
       "Entity names look like light.kitchen: a type, a dot, then lower-case letters, numbers and underscores. This one doesn't follow that pattern, so it can't match anything.",
       "Correct it. You can copy exact entity names from Settings > Devices & services > Entities.")
_check("unknown-trigger-type", WARNING, LOGIC, "An unknown kind of trigger",
       "This trigger type isn't one Home Assistant knows, so the automation is likely to be rejected. It is often a spelling slip.",
       "Correct the trigger type (state, numeric_state, time, sun, event, template …).")
_check("unknown-condition-type", WARNING, LOGIC, "An unknown kind of condition",
       "This condition type isn't one Home Assistant knows, so the automation is likely to be rejected.",
       "Correct the condition type (state, numeric_state, time, sun, template, and, or, not …).")
_check("unknown-action-type", WARNING, LOGIC, "A step Home Assistant won't understand",
       "This step doesn't contain anything Home Assistant recognises as an action (such as action:, delay:, choose: or if:).",
       "Check the spelling of the first word in the step.")
_check("trigger-data-mismatch", WARNING, LOGIC, "Uses trigger details that this trigger doesn't have",
       "The template uses trigger.to_state, trigger.from_state or trigger.entity_id, which only exist when a state-type trigger started the automation. This automation can also be started by a trigger that doesn't have them, and then the template fails.",
       "Check trigger.platform or trigger.id first, or use a separate automation for the other trigger.")
_check("trigger-outside-condition", ERROR, LOGIC, "The trigger time is outside the condition's hours",
       "The automation is triggered at a fixed time, but its time condition only allows a period that doesn't include that time. It can never pass.",
       "Change the trigger time or the condition's after:/before: times.")
_check("duplicate-trigger", TIDY, LOGIC, "The same trigger appears twice",
       "Two triggers in this automation are identical, so the automation may run twice for one event.",
       "Delete one of them.")

# ---------------------------------------------------------------- clashes
_check("contradictory-automations", ERROR, CLASH, "Two automations switch the same thing on and off at the same moment",
       "These automations start from the same trigger and do opposite things to the same entity (for example one turns a light on and the other turns it off). Which one wins is down to chance.",
       "Combine them into one automation, or give them conditions that can't both be true.")
_check("on-off-same-moment", WARNING, CLASH, "Switched on and straight off again",
       "In this list of steps, the same entity is switched one way and then straight back the other way with no delay or wait in between, so the first step has no visible effect.",
       "Add a delay between the steps, or remove the one you don't need.")

# ---------------------------------------------------------------- templates
_check("template-syntax-error", ERROR, TEMPL, "A template has a typing mistake",
       "The code inside {{ }} or {% %} can't be understood, so Home Assistant reports an error whenever it is used.",
       "Look for a missing bracket, quote or }} near the place shown.")
_check("template-no-default", WARNING, TEMPL, "A number conversion with no fallback value",
       "| float, | int, as_timestamp and similar fail when the value isn't a number — which is exactly what happens when a device is \"unavailable\" or \"unknown\". The template then errors and the automation step or sensor fails.",
       "Give a fallback value, for example   | float(0)   or   | int(0),   or check   has_value('sensor.x')   first.")
_check("template-text-number-compare", ERROR, TEMPL, "A template compares text with a number",
       "states() always gives text (for example \"21.5\"). Comparing text with a number using > or < causes an error, and using == never matches.",
       "Convert it first: states('sensor.x') | float(0) > 20.")
_check("template-direct-state", WARNING, TEMPL, "states.xxx.yyy.state fails if the entity is missing",
       "Writing states.sensor.x.state causes an error if the entity is missing or not yet loaded (for example just after a restart). states('sensor.x') does the same job safely.",
       "Use states('sensor.x') or state_attr('sensor.x', 'name') instead.")
_check("template-missing-entity", WARNING, TEMPL, "A template looks at an entity that doesn't exist",
       "The template refers to an entity that can't be found. is_state() will always be false and states() will always be \"unknown\", so the template silently gives the wrong answer.",
       "Correct the entity name (the details suggest the closest match).")

# ---------------------------------------------------------------- references
_check("missing-script", ERROR, REFS, "Runs a script that doesn't exist",
       "This step runs a script that isn't defined anywhere, so the step fails.",
       "Correct the script name, or create the script.")
_check("missing-scene", ERROR, REFS, "Uses a scene that doesn't exist",
       "This step switches on a scene that isn't defined anywhere, so the step fails.",
       "Correct the scene name, or create the scene.")
_check("missing-helper", ERROR, REFS, "Uses a helper that doesn't exist",
       "This refers to a helper (input_boolean, input_number, input_select, timer, counter and so on) that isn't defined, so anything using it fails or never matches.",
       "Correct the name, or create the helper (Settings > Devices & services > Helpers).")
_check("missing-automation", WARNING, REFS, "Refers to an automation that can't be found",
       "This refers to an automation entity that doesn't seem to exist, so the step or check does nothing.",
       "Correct the name. Automation entity names come from their alias, so they change if you rename one.")
_check("missing-service", ERROR, REFS, "Uses an action (shell_command / rest_command / python_script) that isn't defined",
       "This calls an action that would be defined in your YAML, but isn't, so the step fails.",
       "Correct the name, or add the definition.")
_check("unknown-entity", ERROR, REFS, "An entity that doesn't exist",
       "This entity name isn't in Home Assistant's list of entities (or defined in your files), so anything using it fails, never fires or never matches.",
       "Correct the name (the details suggest the closest match), or remove it if the device has gone.")
_check("disabled-entity", WARNING, REFS, "Uses an entity that is switched off (disabled)",
       "This entity is disabled in Home Assistant, so it has no state and never changes. Automations that use it won't work.",
       "Re-enable it (Settings > Devices & services > Entities) or stop using it.")
_check("deleted-entity", ERROR, REFS, "Uses an entity that has been deleted",
       "Home Assistant's records show this entity was deleted, so anything using it fails or never fires.",
       "Replace it with the entity that took its place, or remove it.")
_check("orphaned-entity", ERROR, REFS, "Uses an entity whose device or integration has been removed",
       "The device or integration that provided this entity has been removed, leaving the entity orphaned. It will stay unavailable.",
       "Replace it with the entity from the new device or integration, or remove it.")
_check("unknown-device", ERROR, REFS, "Uses a device that no longer exists",
       "This device trigger, condition or action refers to a device that isn't in Home Assistant's list of devices any more (often after re-pairing a device). It won't work.",
       "Open the automation in the editor and pick the device again.")
_check("unused-helper", TIDY, REFS, "A helper nothing seems to use",
       "This helper isn't used by any automation, script, template or dashboard the doctor could see.",
       "Check it isn't used somewhere the doctor can't see (such as a helper made in the screens) before deleting it.")

# ---------------------------------------------------------------- size and structure
_check("long-automation", TIDY, SIZE, "A very long automation",
       "This automation has a lot of steps. Long automations are hard to follow and to fix, and the editor becomes slow.",
       "Move groups of steps into scripts and call them from the automation.")
_check("deep-nesting", TIDY, SIZE, "Steps nested very deeply",
       "This automation has choices inside choices inside choices. Deep nesting is hard to read and easy to get wrong.",
       "Split it into separate automations (one per trigger) or move inner parts into scripts.")
_check("similar-automations", TIDY, SIZE, "Several automations are almost identical",
       "These automations are the same apart from the entities they use. If you change one, you have to remember to change them all.",
       "Turn them into a blueprint, so one design is shared and each automation only fills in its entities.")
_check("repeated-steps", TIDY, SIZE, "The same group of steps appears in several places",
       "The same sequence of steps is copied into more than one automation or script. If it needs changing, every copy has to be changed.",
       "Move the steps into a script and call the script from each place.")


CHECK_ORDER = {code: index for index, code in enumerate(CHECKS)}


def check(code: str) -> Check:
    return CHECKS[code]


@dataclass
class Finding:
    code: str
    severity: str
    file: str
    line: int
    where: str
    detail: str
    fix: str = ""

    @property
    def check(self) -> Check:
        return CHECKS[self.code]

    @property
    def title(self) -> str:
        return self.check.title

    @property
    def suggested_fix(self) -> str:
        return self.fix or self.check.fix

    def sort_key(self) -> tuple:
        return (SEVERITY_ORDER[self.severity], GROUP_ORDER[self.check.group], CHECK_ORDER[self.code], self.file, self.line, self.detail)


class Findings:
    """Collects findings, hiding private details and removing exact duplicates."""

    def __init__(self) -> None:
        self.items: list[Finding] = []
        self._seen: set[tuple] = set()

    def add(self, code: str, file: str, line: int, detail: str, where: str = "", fix: str = "", severity: str | None = None) -> None:
        meta = CHECKS[code]
        sev = severity or meta.severity
        assert sev in SEVERITIES, sev
        finding = Finding(code, sev, file or "", int(line or 0), redact_text(where), redact_text(detail), redact_text(fix))
        key = (finding.code, finding.file, finding.line, finding.detail, finding.where)
        if key in self._seen:
            return
        self._seen.add(key)
        self.items.append(finding)

    def sorted(self) -> list[Finding]:
        return sorted(self.items, key=Finding.sort_key)

    def count(self, severity: str) -> int:
        return sum(1 for f in self.items if f.severity == severity)

    def codes(self) -> set[str]:
        return {f.code for f in self.items}
