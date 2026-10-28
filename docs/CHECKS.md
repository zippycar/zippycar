# Every check ha-config-doctor makes

This file is produced from the program itself (`py -m ha_config_doctor list-checks --markdown`).

## Files and settings

### No configuration.yaml in this folder

- **Usual severity:** Error
- **Code:** `no-configuration-yaml`
- **Why it matters:** Every Home Assistant configuration folder has a file called configuration.yaml. Without it, this probably isn't the right folder, and very little can be checked.
- **How to fix it:** Point the doctor at the folder that contains configuration.yaml (on the Raspberry Pi this is the "config" folder).

### A file can't be read because of a layout mistake

- **Usual severity:** Error
- **Code:** `yaml-syntax-error`
- **Why it matters:** Home Assistant can't understand this file because something in its layout (the spaces, colons, dashes and quotes) breaks the rules. Everything in the file is ignored until it is fixed, and if it is configuration.yaml Home Assistant may start in "safe mode".
- **How to fix it:** Look at the line shown and the line just above it. Common causes: a missing space after a colon, a TAB instead of spaces, or text containing a colon that needs quotes around it.

### A file isn't saved as ordinary text (UTF-8)

- **Usual severity:** Error
- **Code:** `file-not-utf8`
- **Why it matters:** Home Assistant expects every YAML file to be saved as UTF-8 text. This one contains characters in another format, so Home Assistant will refuse to read it.
- **How to fix it:** Open the file in Notepad, choose File > Save As, set Encoding to UTF-8 and save.

### The same setting appears twice

- **Usual severity:** Warning
- **Code:** `duplicate-key`
- **Why it matters:** When the same name appears twice in one block, Home Assistant silently uses the last one and throws the first away. This is almost always a copy-and-paste slip, and it means some of what you wrote is being ignored.
- **How to fix it:** Delete or merge the duplicate so the setting appears only once.

### An !include points at something that isn't there

- **Usual severity:** Error
- **Code:** `include-missing`
- **Why it matters:** An !include line tells Home Assistant to read another file or folder. The one named here doesn't exist (or its capital letters don't match — the Raspberry Pi cares about capitals even though Windows doesn't), so Home Assistant will report a configuration error.
- **How to fix it:** Correct the name in the !include line, or create the missing file or folder.

### An !include points outside the config folder

- **Usual severity:** Error
- **Code:** `include-outside-folder`
- **Why it matters:** This !include reaches outside the configuration folder. On the Raspberry Pi that location almost certainly doesn't exist, and the doctor deliberately doesn't look outside the folder you gave it.
- **How to fix it:** Move the file into the config folder and change the !include to a name relative to the file that includes it.

### Files include each other in a circle

- **Usual severity:** Error
- **Code:** `include-loop`
- **Why it matters:** File A includes file B, which (directly or through others) includes file A again. Home Assistant can't load a circle like this.
- **How to fix it:** Remove one of the !include lines that closes the circle.

### A file in an include folder is silently skipped

- **Usual severity:** Warning
- **Code:** `include-wrong-content`
- **Why it matters:** !include_dir_merge_list only takes files that contain a list (lines starting with -), and !include_dir_merge_named only takes files that contain named blocks. A file of the wrong kind is skipped without any error message.
- **How to fix it:** Make the file the same shape as the others in that folder.

### A .yml file in an include folder is ignored

- **Usual severity:** Warning
- **Code:** `yml-ignored`
- **Why it matters:** The !include_dir_… commands only read files whose names end in .yaml. A file ending in .yml in the same folder is silently ignored, so anything in it does nothing.
- **How to fix it:** Rename the file so it ends in .yaml.

### A section has the wrong shape

- **Usual severity:** Error
- **Code:** `wrong-include-type`
- **Why it matters:** Some sections must be a list (automations, scenes) and others a set of named blocks (scripts, helpers). This one is the other shape, often because the wrong !include_dir_… command was used.
- **How to fix it:** For automations use !include automations.yaml, !include_dir_list or !include_dir_merge_list. For scripts use !include scripts.yaml, !include_dir_named or !include_dir_merge_named.

### A !secret name isn't in secrets.yaml

- **Usual severity:** Error
- **Code:** `secret-missing`
- **Why it matters:** The file asks for a value from secrets.yaml by name, but secrets.yaml has no entry with that name. Home Assistant will refuse to load this part of the configuration.
- **How to fix it:** Add the missing name to secrets.yaml (the doctor never reads the values there — only the names), or correct the spelling.

### !secret is used but there is no secrets.yaml

- **Usual severity:** Error
- **Code:** `secrets-file-missing`
- **Why it matters:** !secret takes a value from a file called secrets.yaml, but there isn't one in this folder.
- **How to fix it:** Create secrets.yaml in the config folder, or copy it across if your copy of the folder is missing it.

### secrets.yaml is read with !include

- **Usual severity:** Warning
- **Code:** `secrets-included`
- **Why it matters:** secrets.yaml is meant to be used only through !secret. Including it directly mixes your passwords into the rest of the configuration. The doctor has not read it.
- **How to fix it:** Remove the !include of secrets.yaml and use !secret name for each value instead.

### !env_var is used

- **Usual severity:** Warning
- **Code:** `env-var-used`
- **Why it matters:** !env_var reads a value from the computer's environment. On Home Assistant OS (the Raspberry Pi set-up) you can't set these, so without a default value this fails.
- **How to fix it:** Put the value in secrets.yaml and use !secret instead.

### An unknown ! command is used

- **Usual severity:** Error
- **Code:** `unknown-tag`
- **Why it matters:** Words starting with ! are special commands. Home Assistant only knows !include, !include_dir_list, !include_dir_named, !include_dir_merge_list, !include_dir_merge_named, !secret, !input and !env_var. Anything else stops the file loading.
- **How to fix it:** Check the spelling of the ! command.

### !input is used outside a blueprint

- **Usual severity:** Error
- **Code:** `input-outside-blueprint`
- **Why it matters:** !input only works inside blueprint files (in the blueprints folder). Anywhere else Home Assistant can't fill it in.
- **How to fix it:** Replace the !input with the real value.

### A password or key is typed straight into a file

- **Usual severity:** Warning
- **Code:** `inline-secret`
- **Why it matters:** This looks like a password, token or private key typed directly into the file. Anyone you share the file with (for example when asking for help on a forum) will see it. The doctor has hidden the value in this report.
- **How to fix it:** Move the value into secrets.yaml and write !secret some_name here instead.

### A YAML file isn't used by Home Assistant

- **Usual severity:** Tidy-up
- **Code:** `file-not-used`
- **Why it matters:** Nothing in configuration.yaml includes this file, so Home Assistant never reads it. It may be an old copy, or something you meant to switch on.
- **How to fix it:** If you still need it, add an !include for it. If not, you can move it out of the config folder.

### A file the editor uses isn't connected

- **Usual severity:** Warning
- **Code:** `ui-file-not-included`
- **Why it matters:** Automations, scripts and scenes you make in the Home Assistant screens are saved in automations.yaml, scripts.yaml and scenes.yaml. configuration.yaml must include these files or what you make in the editor won't load.
- **How to fix it:** Add the line shown in the details to configuration.yaml.

### An automation uses a blueprint that isn't there

- **Usual severity:** Error
- **Code:** `blueprint-missing`
- **Why it matters:** This automation is built from a blueprint file that can't be found in the blueprints folder, so the automation can't be created.
- **How to fix it:** Re-import the blueprint (Settings > Automations & scenes > Blueprints) or correct the path.

### A blueprint setting hasn't been filled in

- **Usual severity:** Error
- **Code:** `blueprint-input-missing`
- **Why it matters:** The blueprint needs this setting and has no default, but the automation doesn't provide it, so Home Assistant can't create the automation.
- **How to fix it:** Open the automation in the editor and fill in the missing setting.

### An automation fills in a blueprint setting that doesn't exist

- **Usual severity:** Warning
- **Code:** `blueprint-input-unknown`
- **Why it matters:** The automation provides a setting the blueprint doesn't have — usually a spelling slip, or the blueprint was updated and the setting renamed. The value is ignored.
- **How to fix it:** Open the automation in the editor and check its settings.

### A blueprint uses a setting it never lists

- **Usual severity:** Error
- **Code:** `blueprint-input-undeclared`
- **Why it matters:** The blueprint uses !input with a name that isn't listed in its input section, so Home Assistant rejects the blueprint.
- **How to fix it:** Add the setting to the blueprint's input list, or correct the name.

### A blueprint lists a setting it never uses

- **Usual severity:** Tidy-up
- **Code:** `blueprint-input-unused`
- **Why it matters:** The blueprint asks for this setting but never uses it, so filling it in does nothing.
- **How to fix it:** Remove the setting from the blueprint, or use it.

## Automations

### An automation has no id

- **Usual severity:** Warning
- **Code:** `missing-id`
- **Why it matters:** Without an id, an automation can't be opened in the automation editor and Home Assistant keeps no traces (the step-by-step record you use to find out why it did or didn't run).
- **How to fix it:** Add a line such as   id: "hall_light_motion"   with a name not used by any other automation.

### Two items share the same id

- **Usual severity:** Error
- **Code:** `duplicate-id`
- **Why it matters:** Every automation (and every scene) must have its own id. When two share one, Home Assistant mixes them up: editing one can overwrite the other, and one of them may not load at all.
- **How to fix it:** Give one of them a new, unique id.

### An automation has no name (alias)

- **Usual severity:** Tidy-up
- **Code:** `missing-alias`
- **Why it matters:** Without an alias the automation shows up with a meaningless name, which makes it hard to find in lists and logs.
- **How to fix it:** Add a line such as   alias: "Hall light on when motion".

### Two automations have the same name

- **Usual severity:** Warning
- **Code:** `duplicate-alias`
- **Why it matters:** Two automations with the same alias look identical in lists and logs, and Home Assistant has to add _2 to the end of one's entity name. It's easy to edit or switch off the wrong one.
- **How to fix it:** Give each automation its own name.

### An automation has a setting Home Assistant doesn't recognise

- **Usual severity:** Error
- **Code:** `unknown-automation-key`
- **Why it matters:** Home Assistant checks every setting in an automation and rejects the whole automation if it finds one it doesn't know. This is usually a spelling slip.
- **How to fix it:** Correct the spelling (the details suggest the closest known setting) or remove the line.

### Both the old and the new name for the same part are used

- **Usual severity:** Error
- **Code:** `both-old-and-new-keys`
- **Why it matters:** The automation has, for example, both trigger: and triggers:. Home Assistant won't accept both at once.
- **How to fix it:** Merge the two lists under the new name (triggers:, conditions:, actions:).

### An automation has no triggers

- **Usual severity:** Error
- **Code:** `no-triggers`
- **Why it matters:** Triggers are what start an automation. With none, it never runs by itself.
- **How to fix it:** Add a trigger, or if you only ever run it by hand, make it a script instead.

### An automation has no actions

- **Usual severity:** Error
- **Code:** `no-actions`
- **Why it matters:** Actions are what the automation does. With none, it does nothing (and Home Assistant may reject it).
- **How to fix it:** Add the actions, or delete the automation.

### An automation or script has an unknown mode

- **Usual severity:** Error
- **Code:** `invalid-mode`
- **Why it matters:** mode must be one of single, restart, queued or parallel. Anything else is rejected.
- **How to fix it:** Correct the mode.

### max: is set but has no effect

- **Usual severity:** Tidy-up
- **Code:** `max-ignored`
- **Why it matters:** max: only matters when mode is queued or parallel. With single or restart it is ignored.
- **How to fix it:** Remove the max: line, or change the mode if you meant queued or parallel.

### An automation is switched off every time Home Assistant starts

- **Usual severity:** Warning
- **Code:** `initial-state-off`
- **Why it matters:** initial_state: false switches the automation off at every restart, whatever you set in the screens. People often forget it is there.
- **How to fix it:** Remove the initial_state line unless you really want this.

### An automation is switched off

- **Usual severity:** Tidy-up
- **Code:** `automation-switched-off`
- **Why it matters:** Home Assistant's saved state shows this automation is turned off, so it never runs.
- **How to fix it:** If you no longer need it, delete it; otherwise switch it back on.

### A script has no steps

- **Usual severity:** Error
- **Code:** `script-no-sequence`
- **Why it matters:** Every script needs a sequence: list of steps. Without one Home Assistant rejects the script.
- **How to fix it:** Add the steps under sequence:.

## Old or retired features

### Old names: trigger / condition / action

- **Usual severity:** Tidy-up  ·  **Tidy mode fixes this**
- **Code:** `old-plural-keys`
- **Why it matters:** Since Home Assistant 2024.10 the three main parts of an automation are called triggers:, conditions: and actions:. The old singular names still work, but the editor and the documentation now use the new ones.
- **How to fix it:** Rename them. Tidy mode does this for you.

### Old name: platform: inside a trigger

- **Usual severity:** Tidy-up  ·  **Tidy mode fixes this**
- **Code:** `old-platform-key`
- **Why it matters:** Since Home Assistant 2024.10, each trigger starts with trigger: (for example trigger: state) instead of platform:. The old name still works for now.
- **How to fix it:** Rename platform: to trigger:. Tidy mode does this for you.

### Old name: service: in an action

- **Usual severity:** Tidy-up  ·  **Tidy mode fixes this**
- **Code:** `old-service-key`
- **Why it matters:** Since Home Assistant 2024.8, an action that does something (like light.turn_on) is written action: instead of service:. The old name still works for now.
- **How to fix it:** Rename service: to action:. Tidy mode does this for you.

### Old names: data_template / service_template

- **Usual severity:** Tidy-up  ·  **Tidy mode fixes this**
- **Code:** `old-data-template`
- **Why it matters:** Templates have been allowed directly in data: and action: for years, so data_template: and service_template: are no longer needed.
- **How to fix it:** Rename data_template: to data: and service_template: to action:. Tidy mode does this for you.

### An integration that has been removed or is being retired

- **Usual severity:** Warning
- **Code:** `retired-integration`
- **Why it matters:** Home Assistant removes integrations from time to time, or moves their set-up into its screens. Removed ones do nothing and show an error; ones being retired still work for now. The details say which version does what, and where that information comes from.
- **How to fix it:** Follow the suggestion in the details.

### A setting that has been removed or is being retired

- **Usual severity:** Warning
- **Code:** `retired-setting`
- **Why it matters:** Home Assistant has removed, renamed or is retiring this setting. Removed settings are ignored or stop the section loading. The details say which version does what, and where that information comes from.
- **How to fix it:** Follow the suggestion in the details.

### An action that has been removed or is being retired

- **Usual severity:** Warning
- **Code:** `retired-action`
- **Why it matters:** This step uses an action (or an option of an action) that Home Assistant has removed or is retiring. A removed one makes the step fail. The details say which version does what, and where that information comes from.
- **How to fix it:** Follow the suggestion in the details.

### Works differently in your version

- **Usual severity:** Warning
- **Code:** `behaviour-change`
- **Why it matters:** Home Assistant changed how this works. It isn't broken, but it may not do what you expect in the situation the details describe.
- **How to fix it:** Follow the suggestion in the details.

### Template entity written the old way (platform: template)

- **Usual severity:** Error
- **Code:** `legacy-template-entity`
- **Why it matters:** Template entities written the old way (platform: template under sensor:, binary_sensor:, switch: and so on) are no longer supported by recent versions of Home Assistant. The details say which version removed them and show a suggested replacement written the current way.
- **How to fix it:** Move each one into the template: section using the suggested replacement, check it, then delete the old block.

## Timing and repeats

### A wait or delay in a "single" automation drops new triggers

- **Usual severity:** Warning
- **Code:** `single-mode-wait`
- **Why it matters:** In mode: single (the default), while the automation is waiting, any new trigger is thrown away (Home Assistant only writes "Already running" in the log). A classic example: a motion light with a 5-minute delay won't restart its timer when you walk past again, so the light goes off while you're still there.
- **How to fix it:** Use mode: restart if each new trigger should start again (good for motion lights), or mode: queued if every trigger must be handled. If dropping them is what you want, add max_exceeded: silent to say so.

### A wait has no time limit

- **Usual severity:** Warning
- **Code:** `wait-without-timeout`
- **Why it matters:** A wait_template or wait_for_trigger without timeout: waits forever if the thing never happens. While it waits, an automation in single mode ignores every new trigger.
- **How to fix it:** Add timeout: (for example timeout: "00:30:00") and, if needed, continue_on_timeout: false.

### Risk of a pile-up of runs

- **Usual severity:** Warning
- **Code:** `queue-storm`
- **Why it matters:** In queued or parallel mode every trigger starts (or lines up) another run. With a trigger that fires very often, or a long wait, or a very high max:, runs can pile up, slow Home Assistant down and carry on long after you expect.
- **How to fix it:** Use mode: restart or single, add a condition, lower max:, or trigger on something that changes less often.

### Restart mode with a busy trigger may never finish

- **Usual severity:** Warning
- **Code:** `restart-storm`
- **Why it matters:** In restart mode each new trigger stops the run and starts again. If the trigger fires more often than the actions take, the actions after the wait or delay may never be reached.
- **How to fix it:** Use a trigger that changes less often (for example with to: and for:), or use mode: single or queued.

### An automation changes the thing that triggers it

- **Usual severity:** Warning
- **Code:** `self-trigger-loop`
- **Why it matters:** The automation is triggered by an entity and then changes that same entity. That change can trigger the automation again — and again — creating a loop.
- **How to fix it:** Add a condition, trigger only on specific changes (to: / from:), or watch a different entity.

### Triggers on something that changes all the time, with no conditions

- **Usual severity:** Warning
- **Code:** `chatty-trigger`
- **Why it matters:** This trigger fires on every small change of a busy sensor (for example every power or temperature reading, or every attribute update), and the automation has no conditions to filter them. It may run hundreds of times a day.
- **How to fix it:** Trigger on specific values instead (numeric_state with above:/below:, or state with to:), or add a condition.

### Triggers when a device goes offline or comes back

- **Usual severity:** Warning
- **Code:** `trigger-on-unavailable`
- **Why it matters:** This trigger fires on the special states "unavailable" or "unknown". These happen whenever a device drops off the network and every time Home Assistant restarts, so the automation may run when nothing real has happened.
- **How to fix it:** If you want to know when a device goes offline, add for: "00:05:00" so short blips and restarts are ignored. Otherwise use not_from: / not_to: ["unavailable", "unknown"].

### May fire when a device reconnects

- **Usual severity:** Tidy-up
- **Code:** `reconnect-false-trigger`
- **Why it matters:** This trigger fires when the entity changes to the given state from anything — including from "unavailable" when the device reconnects or Home Assistant restarts. That can look like a real event when it isn't.
- **How to fix it:** Add   not_from: ["unavailable", "unknown"]   to the trigger.

### A repeat loop has no pause

- **Usual severity:** Warning
- **Code:** `repeat-no-pause`
- **Why it matters:** This repeat (while/until) has no delay or wait inside, so it loops as fast as it can until the condition changes. That can make Home Assistant sluggish.
- **How to fix it:** Add a short delay inside the repeat, for example delay: "00:00:05".

## Automations that fight each other

### Two automations act on the same thing at almost the same time

- **Usual severity:** Warning
- **Code:** `time-clash`
- **Why it matters:** These automations are timed within a minute of each other and do opposite things to the same entity. The result depends on which happens to run last.
- **How to fix it:** Move one of the times, or combine them into one automation.

### A sunset/sunrise time and a clock time swap order during the year

- **Usual severity:** Warning
- **Code:** `sun-time-overlap`
- **Why it matters:** One automation uses sunrise or sunset, which moves through the year, and another uses a fixed clock time, and they do opposite things to the same entity. At some times of year the fixed time comes first, so (for example) a light switched on at sunset is never switched off, or the other way round.
- **How to fix it:** Use a time condition, or base both on the sun, or combine them into one automation with a check of the time.

### Two automations switch the same thing on and off at the same moment

- **Usual severity:** Error
- **Code:** `contradictory-automations`
- **Why it matters:** These automations start from the same trigger and do opposite things to the same entity (for example one turns a light on and the other turns it off). Which one wins is down to chance.
- **How to fix it:** Combine them into one automation, or give them conditions that can't both be true.

### Switched on and straight off again

- **Usual severity:** Warning
- **Code:** `on-off-same-moment`
- **Why it matters:** In this list of steps, the same entity is switched one way and then straight back the other way with no delay or wait in between, so the first step has no visible effect.
- **How to fix it:** Add a delay between the steps, or remove the one you don't need.

## Things that can never happen

### on / off / yes / no without quotes

- **Usual severity:** Error
- **Code:** `yaml-boolean-state`
- **Why it matters:** YAML (the file format) turns an unquoted on, off, yes or no into true or false. Home Assistant states are text such as "on", so this either gets rejected or never matches — the automation never fires or the condition never passes.
- **How to fix it:** Put quotes around it: "on" or "off".

### A time without quotes is read as a number

- **Usual severity:** Error
- **Code:** `yaml-number-time`
- **Why it matters:** YAML (the file format) reads an unquoted time such as 7:30 or 12:30:00 as a number (7:30 becomes 450). Home Assistant then rejects it or reads it as a number of seconds.
- **How to fix it:** Put quotes around times: "07:30:00".

### above and below can never both be true

- **Usual severity:** Error
- **Code:** `impossible-range`
- **Why it matters:** The value must be above the first number and below the second at the same time, but the first is not smaller than the second, so this can never be true.
- **How to fix it:** Swap the numbers, or split it into two triggers/conditions if you meant "either".

### A number check on something that isn't a number

- **Usual severity:** Error
- **Code:** `numeric-on-non-numeric`
- **Why it matters:** numeric_state compares numbers, but this entity's state is a word such as on/off, so it never fires.
- **How to fix it:** Use a state trigger/condition instead, or add attribute: if you meant to watch a number attribute.

### from: and to: are the same

- **Usual severity:** Error
- **Code:** `same-from-to`
- **Why it matters:** A trigger with the same from: and to: values waits for a change from a state to itself, which never happens.
- **How to fix it:** Correct one of the values.

### "After sunset and before sunrise" can never be true

- **Usual severity:** Error
- **Code:** `sun-condition-never`
- **Why it matters:** A single sun condition only looks at one day, midnight to midnight, so "after sunset AND before sunrise" is never true. It's a well-known trap.
- **How to fix it:** Use   condition: state, entity_id: sun.sun, state: "below_horizon"   or an "or" of two sun conditions.

### Conditions that contradict each other

- **Usual severity:** Error
- **Code:** `contradictory-conditions`
- **Why it matters:** All of an automation's conditions must be true together, but these two can't both be true at once (for example the same light both "on" and "off"). The actions never run.
- **How to fix it:** Remove one condition, or use condition: or if either is enough.

### All of the triggers are switched off

- **Usual severity:** Error
- **Code:** `all-triggers-disabled`
- **Why it matters:** Every trigger in this automation has enabled: false, so nothing can start it.
- **How to fix it:** Switch at least one trigger back on, or delete the automation.

### A template trigger that never changes

- **Usual severity:** Error
- **Code:** `template-trigger-static`
- **Why it matters:** A template trigger fires when its result changes from false to true. This one has no template code in {{ }}, so its result never changes and it never fires.
- **How to fix it:** Write the test inside {{ }}, or use a state trigger.

### A template where Home Assistant doesn't allow one

- **Usual severity:** Error
- **Code:** `template-not-allowed`
- **Why it matters:** This setting doesn't accept {{ }} templates, so Home Assistant either rejects it or treats the template text literally, and it never matches.
- **How to fix it:** Use a template trigger or template condition instead, or type the value directly.

### A check for a trigger id that no trigger has

- **Usual severity:** Warning
- **Code:** `unknown-trigger-id`
- **Why it matters:** A condition checks which trigger started the automation, using an id that none of its triggers has. That branch never runs.
- **How to fix it:** Correct the id, or add id: to the trigger you meant.

### An impossible time of day

- **Usual severity:** Error
- **Code:** `invalid-time`
- **Why it matters:** This time isn't a valid time of day (hours must be 0–23 and minutes 0–59), so Home Assistant rejects it.
- **How to fix it:** Write the time as "HH:MM" or "HH:MM:SS", for example "07:30:00".

### An impossible time_pattern value

- **Usual severity:** Error
- **Code:** `invalid-time-pattern`
- **Why it matters:** time_pattern values must be within range (hours 0–23, minutes and seconds 0–59) or written like "/5" for "every 5". This one isn't, so it is rejected or never matches.
- **How to fix it:** Correct the value, for example minutes: "/5" for every five minutes.

### A length of time Home Assistant can't understand

- **Usual severity:** Error
- **Code:** `invalid-duration`
- **Why it matters:** Delays, waits and for: must be written as "HH:MM:SS", a number of seconds, or with hours:/minutes:/seconds:. Wording like "5 minutes" is rejected.
- **How to fix it:** Write it as, for example, "00:05:00" or  minutes: 5.

### A badly written entity name

- **Usual severity:** Error
- **Code:** `invalid-entity-id`
- **Why it matters:** Entity names look like light.kitchen: a type, a dot, then lower-case letters, numbers and underscores. This one doesn't follow that pattern, so it can't match anything.
- **How to fix it:** Correct it. You can copy exact entity names from Settings > Devices & services > Entities.

### An unknown kind of trigger

- **Usual severity:** Warning
- **Code:** `unknown-trigger-type`
- **Why it matters:** This trigger type isn't one Home Assistant knows, so the automation is likely to be rejected. It is often a spelling slip.
- **How to fix it:** Correct the trigger type (state, numeric_state, time, sun, event, template …).

### An unknown kind of condition

- **Usual severity:** Warning
- **Code:** `unknown-condition-type`
- **Why it matters:** This condition type isn't one Home Assistant knows, so the automation is likely to be rejected.
- **How to fix it:** Correct the condition type (state, numeric_state, time, sun, template, and, or, not …).

### A step Home Assistant won't understand

- **Usual severity:** Warning
- **Code:** `unknown-action-type`
- **Why it matters:** This step doesn't contain anything Home Assistant recognises as an action (such as action:, delay:, choose: or if:).
- **How to fix it:** Check the spelling of the first word in the step.

### Uses trigger details that this trigger doesn't have

- **Usual severity:** Warning
- **Code:** `trigger-data-mismatch`
- **Why it matters:** The template uses trigger.to_state, trigger.from_state or trigger.entity_id, which only exist when a state-type trigger started the automation. This automation can also be started by a trigger that doesn't have them, and then the template fails.
- **How to fix it:** Check trigger.platform or trigger.id first, or use a separate automation for the other trigger.

### The trigger time is outside the condition's hours

- **Usual severity:** Error
- **Code:** `trigger-outside-condition`
- **Why it matters:** The automation is triggered at a fixed time, but its time condition only allows a period that doesn't include that time. It can never pass.
- **How to fix it:** Change the trigger time or the condition's after:/before: times.

### The same trigger appears twice

- **Usual severity:** Tidy-up
- **Code:** `duplicate-trigger`
- **Why it matters:** Two triggers in this automation are identical, so the automation may run twice for one event.
- **How to fix it:** Delete one of them.

## Templates (the bits in {{ }})

### A template has a typing mistake

- **Usual severity:** Error
- **Code:** `template-syntax-error`
- **Why it matters:** The code inside {{ }} or {% %} can't be understood, so Home Assistant reports an error whenever it is used.
- **How to fix it:** Look for a missing bracket, quote or }} near the place shown.

### A number conversion with no fallback value

- **Usual severity:** Warning
- **Code:** `template-no-default`
- **Why it matters:** | float, | int, as_timestamp and similar fail when the value isn't a number — which is exactly what happens when a device is "unavailable" or "unknown". The template then errors and the automation step or sensor fails.
- **How to fix it:** Give a fallback value, for example   | float(0)   or   | int(0),   or check   has_value('sensor.x')   first.

### A template compares text with a number

- **Usual severity:** Error
- **Code:** `template-text-number-compare`
- **Why it matters:** states() always gives text (for example "21.5"). Comparing text with a number using > or < causes an error, and using == never matches.
- **How to fix it:** Convert it first: states('sensor.x') | float(0) > 20.

### states.xxx.yyy.state fails if the entity is missing

- **Usual severity:** Warning
- **Code:** `template-direct-state`
- **Why it matters:** Writing states.sensor.x.state causes an error if the entity is missing or not yet loaded (for example just after a restart). states('sensor.x') does the same job safely.
- **How to fix it:** Use states('sensor.x') or state_attr('sensor.x', 'name') instead.

### A template looks at an entity that doesn't exist

- **Usual severity:** Warning
- **Code:** `template-missing-entity`
- **Why it matters:** The template refers to an entity that can't be found. is_state() will always be false and states() will always be "unknown", so the template silently gives the wrong answer.
- **How to fix it:** Correct the entity name (the details suggest the closest match).

## Names that point at nothing

### Runs a script that doesn't exist

- **Usual severity:** Error
- **Code:** `missing-script`
- **Why it matters:** This step runs a script that isn't defined anywhere, so the step fails.
- **How to fix it:** Correct the script name, or create the script.

### Uses a scene that doesn't exist

- **Usual severity:** Error
- **Code:** `missing-scene`
- **Why it matters:** This step switches on a scene that isn't defined anywhere, so the step fails.
- **How to fix it:** Correct the scene name, or create the scene.

### Uses a helper that doesn't exist

- **Usual severity:** Error
- **Code:** `missing-helper`
- **Why it matters:** This refers to a helper (input_boolean, input_number, input_select, timer, counter and so on) that isn't defined, so anything using it fails or never matches.
- **How to fix it:** Correct the name, or create the helper (Settings > Devices & services > Helpers).

### Refers to an automation that can't be found

- **Usual severity:** Warning
- **Code:** `missing-automation`
- **Why it matters:** This refers to an automation entity that doesn't seem to exist, so the step or check does nothing.
- **How to fix it:** Correct the name. Automation entity names come from their alias, so they change if you rename one.

### Uses an action (shell_command / rest_command / python_script) that isn't defined

- **Usual severity:** Error
- **Code:** `missing-service`
- **Why it matters:** This calls an action that would be defined in your YAML, but isn't, so the step fails.
- **How to fix it:** Correct the name, or add the definition.

### An entity that doesn't exist

- **Usual severity:** Error
- **Code:** `unknown-entity`
- **Why it matters:** This entity name isn't in Home Assistant's list of entities (or defined in your files), so anything using it fails, never fires or never matches.
- **How to fix it:** Correct the name (the details suggest the closest match), or remove it if the device has gone.

### Uses an entity that is switched off (disabled)

- **Usual severity:** Warning
- **Code:** `disabled-entity`
- **Why it matters:** This entity is disabled in Home Assistant, so it has no state and never changes. Automations that use it won't work.
- **How to fix it:** Re-enable it (Settings > Devices & services > Entities) or stop using it.

### Uses an entity that has been deleted

- **Usual severity:** Error
- **Code:** `deleted-entity`
- **Why it matters:** Home Assistant's records show this entity was deleted, so anything using it fails or never fires.
- **How to fix it:** Replace it with the entity that took its place, or remove it.

### Uses an entity whose device or integration has been removed

- **Usual severity:** Error
- **Code:** `orphaned-entity`
- **Why it matters:** The device or integration that provided this entity has been removed, leaving the entity orphaned. It will stay unavailable.
- **How to fix it:** Replace it with the entity from the new device or integration, or remove it.

### Uses a device that no longer exists

- **Usual severity:** Error
- **Code:** `unknown-device`
- **Why it matters:** This device trigger, condition or action refers to a device that isn't in Home Assistant's list of devices any more (often after re-pairing a device). It won't work.
- **How to fix it:** Open the automation in the editor and pick the device again.

### A helper nothing seems to use

- **Usual severity:** Tidy-up
- **Code:** `unused-helper`
- **Why it matters:** This helper isn't used by any automation, script, template or dashboard the doctor could see.
- **How to fix it:** Check it isn't used somewhere the doctor can't see (such as a helper made in the screens) before deleting it.

## Size and structure

### A very long automation

- **Usual severity:** Tidy-up
- **Code:** `long-automation`
- **Why it matters:** This automation has a lot of steps. Long automations are hard to follow and to fix, and the editor becomes slow.
- **How to fix it:** Move groups of steps into scripts and call them from the automation.

### Steps nested very deeply

- **Usual severity:** Tidy-up
- **Code:** `deep-nesting`
- **Why it matters:** This automation has choices inside choices inside choices. Deep nesting is hard to read and easy to get wrong.
- **How to fix it:** Split it into separate automations (one per trigger) or move inner parts into scripts.

### Several automations are almost identical

- **Usual severity:** Tidy-up
- **Code:** `similar-automations`
- **Why it matters:** These automations are the same apart from the entities they use. If you change one, you have to remember to change them all.
- **How to fix it:** Turn them into a blueprint, so one design is shared and each automation only fills in its entities.

### The same group of steps appears in several places

- **Usual severity:** Tidy-up
- **Code:** `repeated-steps`
- **Why it matters:** The same sequence of steps is copied into more than one automation or script. If it needs changing, every copy has to be changed.
- **How to fix it:** Move the steps into a script and call the script from each place.

## Rules about removed, retired and changed features

These come from `data/ha_rules.yaml` (last reviewed 2026-10-28; newest Home Assistant release covered: 2026.10). For the version being checked, a removed feature is an Error, a feature marked for retirement is a Warning, a behaviour change is a Warning where it matters, and anything that only happens in a later version is a Tidy-up.

**Verification:** None of these rules could be checked against home-assistant.io when they were written (28 October 2026): the official site could not be reached from the environment used to write them. Every rule is therefore marked "unverified". The rules marked basis "owner" come from the owner of the set-up; "search-summary" rules come from web-search summaries of the official release notes, changelogs and community posts.

| Rule | Marked for retirement | Removed | Changed | Checked? | Based on | Source |
|---|---|---|---|---|---|---|
| `legacy-template-entities` | 2025.12 | 2026.6 | — | unverified | information from the owner of this set-up | <https://www.home-assistant.io/blog/2026/06/03/release-20266/> |
| `device-tracker-see` | 2026.5 | planned for 2027.5 | — | unverified | information from the owner of this set-up | <https://www.home-assistant.io/blog/2026/06/03/release-20266/> |
| `mqtt-publish-needs-admin` | — | — | 2026.10 | unverified | information from the owner of this set-up | <https://www.home-assistant.io/blog/2026/10/07/release-202610/> |
| `mqtt-dump-needs-admin` | — | — | 2026.10 | unverified | a web-search summary of Home Assistant's release notes and community posts | <https://www.home-assistant.io/blog/2026/10/07/release-202610/> |
| `synology-reboot-needs-admin` | — | — | 2026.10 | unverified | information from the owner of this set-up | <https://www.home-assistant.io/blog/2026/10/07/release-202610/> |
| `synology-shutdown-needs-admin` | — | — | 2026.10 | unverified | a web-search summary of Home Assistant's release notes and community posts | <https://www.home-assistant.io/blog/2026/10/07/release-202610/> |
| `removed-integrations-2026-10` | — | 2026.10 | — | unverified | a web-search summary of Home Assistant's release notes and community posts | <https://www.home-assistant.io/blog/2026/10/07/release-202610/> |
| `disabled-integrations-2026-10` | — | 2026.10 | — | unverified | a web-search summary of Home Assistant's release notes and community posts | <https://www.home-assistant.io/blog/2026/10/07/release-202610/> |
| `vlc-removed` | — | 2026.9 | — | unverified | a web-search summary of Home Assistant's release notes and community posts | <https://www.home-assistant.io/changelogs/core-2026.9/> |
| `influxdb-yaml-connection` | 2026.3 | 2026.9 | — | unverified | a web-search summary of Home Assistant's release notes and community posts | <https://www.home-assistant.io/integrations/influxdb/> |
| `light-color-temp-mireds` | — | 2026.3 | — | unverified | a web-search summary of Home Assistant's release notes and community posts | <https://www.home-assistant.io/changelogs/core-2026.3/> |
| `light-kelvin-option` | — | 2026.3 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/light/> |
| `snapcast-grouping-actions` | — | 2026.3 | — | unverified | a web-search summary of Home Assistant's release notes and community posts | <https://www.home-assistant.io/changelogs/core-2026.3/> |
| `old-zwave` | — | 2022.1 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/zwave_js/> |
| `old-housekeeping-integrations` | — | 2023.1 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/default_config/> |
| `map-panel` | 2024.12 | — | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/dashboards/map/> |
| `platform-mqtt` | — | 2022.12 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/mqtt/> |
| `platform-command-line` | 2023.6 | 2023.12 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/command_line/> |
| `platforms-moved-to-screens` | 2024.1 | — | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/> |
| `entity-namespace` | — | 2021.1 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/docs/configuration/platform_options/> |
| `whitelist-external-dirs` | 2020.12 | — | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/homeassistant/> |
| `legacy-templates-option` | — | 2021.10 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/homeassistant/> |
| `http-old-options` | — | 2021.1 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/http/> |
| `recorder-purge-interval` | — | 2021.1 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/recorder/> |
| `frontend-javascript-version` | — | 2021.1 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/frontend/> |
| `mqtt-broker-yaml` | — | 2023.1 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/mqtt/> |
| `automation-hide-entity` | — | 2021.1 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/docs/automation/yaml/> |
| `weather-get-forecast` | 2023.12 | 2024.6 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/weather/> |
| `weather-forecast-attribute` | 2023.9 | 2024.3 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/weather/> |
| `climate-aux-heat` | 2024.4 | 2024.10 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/climate/> |
| `group-set-visibility` | — | 2021.1 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/group/> |
| `light-white-value` | — | 2022.9 | — | unverified | the tool author's own knowledge | <https://www.home-assistant.io/integrations/light/> |

### `legacy-template-entities`

- **What happened:** From Home Assistant 2026.6, template entities written the old way (platform: template under sensor:, binary_sensor:, switch: and so on) are no longer supported. They are not created, so anything that uses them sees an entity that doesn't exist.
- **What to do:** Move each one into the template: section, written the current way. A suggested replacement is shown below; check it, then delete the old platform: template block.
- **How sure we are:** Stated by the owner. A search summary of the official 2026.6 changelog agrees (one "Remove legacy ... template entities" change for each of the ten entity types).

### `device-tracker-see`

- **What happened:** The device_tracker.see action is being retired. Template device trackers, added in Home Assistant 2026.6, replace it.
- **What to do:** Create a template device tracker in the template: section (it can use latitude/longitude templates or a list of zones), and remove the device_tracker.see step.
- **How sure we are:** Deprecation stated by the owner. The 2026.5 log warning ("will be removed in Home Assistant Core 2027.5") and the 2026.6 template device tracker come from search summaries.

### `mqtt-publish-needs-admin`

- **What happened:** From Home Assistant 2026.10, sending an MQTT message by hand (mqtt.publish) needs an administrator. Automations that start by themselves are not affected, but if someone who isn't an administrator runs this script (for example from a dashboard button), the step fails.
- **What to do:** Make sure only administrator accounts run this script, or start it from an automation instead.

### `mqtt-dump-needs-admin`

- **What happened:** From Home Assistant 2026.10, mqtt.dump needs an administrator. If someone who isn't an administrator runs this script, the step fails.
- **What to do:** Make sure only administrator accounts run this script.

### `synology-reboot-needs-admin`

- **What happened:** From Home Assistant 2026.10, restarting a Synology NAS (synology_dsm.reboot) needs an administrator. If someone who isn't an administrator runs this script, the step fails.
- **What to do:** Make sure only administrator accounts run this script.

### `synology-shutdown-needs-admin`

- **What happened:** From Home Assistant 2026.10, shutting down a Synology NAS (synology_dsm.shutdown) needs an administrator. If someone who isn't an administrator runs this script, the step fails.
- **What to do:** Make sure only administrator accounts run this script.

### `removed-integrations-2026-10`

- **What happened:** This integration was removed from Home Assistant in 2026.10, so this part of the configuration does nothing any more and will show an error.
- **What to do:** Delete this section (and anything that uses its entities), or find a replacement integration.
- **How sure we are:** The list (Dublin Bus, Etherscan, Melnor RainCloud, Orange and Rockland Utility, Sigfox, SolarEdge Local, Travis-CI, Zestimate) comes from search summaries of the 2026.10 release coverage. The YAML names used to spot them are from the author's memory.

### `disabled-integrations-2026-10`

- **What happened:** This integration was switched off in Home Assistant 2026.10 and no longer starts, so this part of the configuration does nothing any more.
- **What to do:** Delete this section (and anything that uses its entities), or find a replacement integration.

### `vlc-removed`

- **What happened:** The VLC media player integration (platform: vlc) was removed in Home Assistant 2026.9. The separate "VLC media player via Telnet" integration is not affected.
- **What to do:** Delete this block. If you still use VLC, set up "VLC media player via Telnet" from Settings > Devices & services instead.
- **How sure we are:** A search summary of the official 2026.9 changelog lists "Remove VLC integration".

### `influxdb-yaml-connection`

- **What happened:** The InfluxDB connection settings (address, port and so on) are no longer read from configuration.yaml. They were copied into the Home Assistant screens automatically when the change was announced. Settings such as include, exclude and tags can stay in YAML.
- **What to do:** Check the connection under Settings > Devices & services > InfluxDB, then delete these connection lines from configuration.yaml.
- **How sure we are:** From community posts quoting Home Assistant's own warning; the exact list of connection settings may be longer.

### `light-color-temp-mireds`

- **What happened:** Setting a light's colour temperature in "mireds" (color_temp) was removed in Home Assistant 2026.3. Only Kelvin is accepted now.
- **What to do:** Use color_temp_kelvin instead. To convert, divide 1,000,000 by the mired value (370 mireds is about 2700 K).

### `light-kelvin-option`

- **What happened:** The old kelvin option for lights was retired along with mireds. Only color_temp_kelvin is accepted now.
- **What to do:** Rename kelvin to color_temp_kelvin.
- **How sure we are:** The author recalls kelvin and color_temp being retired together; the version is assumed.

### `snapcast-grouping-actions`

- **What happened:** Snapcast's own grouping actions were removed in Home Assistant 2026.3.
- **What to do:** Use media_player.join and media_player.unjoin instead.
- **How sure we are:** A search summary of the 2026.3 changelog mentions removing Snapcast's "custom grouping services"; the action names are from the author's memory.

### `old-zwave`

- **What happened:** The old Z-Wave and OpenZWave integrations were removed years ago.
- **What to do:** Use Z-Wave JS (Settings > Devices & services), then delete this section.

### `old-housekeeping-integrations`

- **What happened:** This integration was removed: Home Assistant now finds devices and tells you about updates by itself.
- **What to do:** Delete this line from configuration.yaml.

### `map-panel`

- **What happened:** The map: line is no longer needed; the map is a dashboard now.
- **What to do:** Delete the map: line and add a Map card or Map dashboard instead.

### `platform-mqtt`

- **What happened:** Writing MQTT entities as "platform: mqtt" under sensor:, switch: and so on was removed.
- **What to do:** Put them under the mqtt: section instead (mqtt: > sensor: > - name: …).

### `platform-command-line`

- **What happened:** Writing command line entities as "platform: command_line" was removed.
- **What to do:** Put them under the command_line: section instead.

### `platforms-moved-to-screens`

- **What happened:** This is now set up in the Home Assistant screens rather than in YAML. The YAML version was copied into the screens automatically when the change happened, and may already have stopped being read.
- **What to do:** Check it under Settings > Devices & services, then delete this block.
- **How sure we are:** These moved at different times; the version is the earliest the author recalls.

### `entity-namespace`

- **What happened:** entity_namespace was removed.
- **What to do:** Delete the entity_namespace line.

### `whitelist-external-dirs`

- **What happened:** whitelist_external_dirs was renamed.
- **What to do:** Rename it to allowlist_external_dirs.

### `legacy-templates-option`

- **What happened:** legacy_templates was removed.
- **What to do:** Delete the line.

### `http-old-options`

- **What happened:** These settings were removed from http:. (Any value is hidden in this report.)
- **What to do:** Set the addresses under Settings > System > Network, use normal logins instead of api_password, and delete these lines.

### `recorder-purge-interval`

- **What happened:** purge_interval was removed from recorder:.
- **What to do:** Use auto_purge (on by default) and purge_keep_days, and delete the line.

### `frontend-javascript-version`

- **What happened:** javascript_version was removed from frontend:.
- **What to do:** Delete the line.

### `mqtt-broker-yaml`

- **What happened:** The connection settings for MQTT are no longer read from YAML. (Any values are hidden in this report.)
- **What to do:** Set the connection in Settings > Devices & services > MQTT > Configure, then delete these lines.

### `automation-hide-entity`

- **What happened:** hide_entity was removed, and Home Assistant rejects automations that still have it.
- **What to do:** Delete the hide_entity line.

### `weather-get-forecast`

- **What happened:** weather.get_forecast (without an s) was removed.
- **What to do:** Use weather.get_forecasts (with an s); its result is grouped by entity.

### `weather-forecast-attribute`

- **What happened:** Weather entities no longer have a "forecast" attribute.
- **What to do:** Use the weather.get_forecasts action with response_variable, and read the forecast from that.

### `climate-aux-heat`

- **What happened:** climate.set_aux_heat was removed ("auxiliary heat" is no longer part of climate devices).
- **What to do:** Use a switch or the device's own option instead, and remove this step.

### `group-set-visibility`

- **What happened:** group.set_visibility was removed long ago.
- **What to do:** Remove this step.

### `light-white-value`

- **What happened:** white_value was removed from lights.
- **What to do:** Use white or rgbw_color instead.

## Still supported (never reported)

- **id on triggers, and "condition: trigger" checks, written in YAML** — Home Assistant 2026.10 added a way to pick triggers in the editor's "Triggered by" condition, which manages trigger IDs for you. Trigger IDs written in YAML keep working exactly as before. (unverified; source <https://www.home-assistant.io/blog/2026/10/07/release-202610/>)

