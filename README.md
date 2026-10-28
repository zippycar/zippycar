# Home Assistant Config Doctor

A careful check-up for your Home Assistant set-up. You point it at a **copy** of your Home Assistant
`config` folder on your Windows PC, and it writes you a report — in plain English — of anything that is
broken, likely to misbehave, or worth tidying, with the file and line number of each one and what to do
about it.

It can also make a **tidied copy** of your files in a new folder, with a list of every change and why.

**It never changes your files.** It only reads them.

Written for Home Assistant OS on a Raspberry Pi (tested against Core 2026.10.4), looked at from a
Windows 11 PC.

> **Important — how up to date its knowledge is.** What the doctor knows about features Home Assistant
> has removed or retired is kept in one file, [`data/ha_rules.yaml`](data/ha_rules.yaml), with the
> version and source of every rule. When those rules were written (28 October 2026),
> **home-assistant.io could not be reached**, so **none of them could be checked against the official
> release notes**. Every rule is marked **"unverified"**, and the report says so next to each finding
> that comes from one. See [How up to date are the rules?](#how-up-to-date-are-the-rules)

---

## Contents

1. [What it looks at](#what-it-looks-at)
2. [What it will never do](#what-it-will-never-do)
3. [Setting it up (once)](#setting-it-up-once)
4. [Checking your configuration](#checking-your-configuration)
5. [Reading the report](#reading-the-report)
6. [Which Home Assistant version it checks against](#which-home-assistant-version-it-checks-against)
7. [How up to date are the rules?](#how-up-to-date-are-the-rules)
8. [Making a tidied copy (optional)](#making-a-tidied-copy-optional)
9. [Putting tidied files back into Home Assistant](#putting-tidied-files-back-into-home-assistant)
10. [If something goes wrong](#if-something-goes-wrong)
11. [Updating or removing it](#updating-or-removing-it)
12. [A few words explained](#a-few-words-explained)
13. [For helpers and developers](#for-helpers-and-developers)

---

## What it looks at

* **Every file Home Assistant reads**, starting from `configuration.yaml` and following every
  `!include` just as Home Assistant does (including the `packages` folder if you use one).
* **Every automation and script**, in great detail — 99 different checks. For example:
  * automations that can **never run** (an unquoted `on`, an impossible time, conditions that contradict
    each other, "after sunset and before sunrise"…);
  * automations that **fight each other** (one switches a light on while another switches it off at the
    same moment, or a sunset time and a clock time that swap order during the year);
  * **waits and delays that silently drop new triggers** (the classic motion light that switches off
    while you're still in the room);
  * triggers that fire **hundreds of times a day**, or when a device **drops offline**;
  * **templates** (the bits in `{{ }}`) that break when a device is unavailable;
  * names of scripts, scenes, helpers and devices that **point at nothing**;
  * **features Home Assistant has removed or is retiring** — for example old-style template sensors
    (removed in 2026.6), with a suggested replacement written the current way — judged against
    **your** version of Home Assistant;
  * **old ways of writing** things that Home Assistant has replaced;
  * automations that are **too long or too deeply nested** to follow.
* **Home Assistant's own list of entities and devices** (in the `.storage` folder), so every entity name
  you use is cross-checked: does it exist, is it switched off (disabled), or has its device gone?

The full list, with an explanation of each check, is in [docs/CHECKS.md](docs/CHECKS.md).

## What it will never do

* **It never changes anything** in the folder you check. It only reads.
* **It never reads your passwords.** From `secrets.yaml` it looks only at the *names* on the left (to
  check that every `!secret` you use exists). The values are never read into the program, shown or copied.
* **It never opens Home Assistant's login files** in `.storage` (such as `auth`,
  `auth_provider.homeassistant`, `core.config_entries`, `cloud` and `http`).
* From `.storage` it reads only: the list of entities, the list of devices, the last saved states (just
  each entity's name and on/off-type state), the home location (rounded, used only to work out sunrise
  and sunset times, and never shown), the lists of helpers, and the entity names used on your
  dashboards.
* **It hides anything that looks private** in its report: passwords, tokens, e-mail addresses, phone
  numbers and network addresses.
* **It never uses the internet.**

---

## Setting it up (once)

You do this part only once. It takes about 10 minutes.

### 1. Open PowerShell

PowerShell is the window where you paste the commands below.

1. Click the **Start** button.
2. Type `PowerShell`.
3. Press **Enter**.

A window with a dark background opens. (On some computers it is called **Terminal** — that's fine too.)

To paste into it, **right-click** inside the window (or press **Ctrl+V**), then press **Enter**.

### 2. Install Python

Python is the free program the doctor runs on. Paste this into PowerShell and press Enter:

```powershell
winget install --id Python.Python.3.13 --source winget --accept-package-agreements --accept-source-agreements
```

When it says it has finished, **close PowerShell and open it again** (as in step 1). Then check it worked:

```powershell
py --version
```

You should see something like `Python 3.13.…`.

> If `winget` isn't recognised: go to <https://www.python.org/downloads/>, click the yellow
> **Download Python** button, run the file you downloaded, and say yes to everything it suggests.

### 3. Download the doctor

1. On this project's GitHub page, click the green **Code** button, then **Download ZIP**.
2. Open your **Downloads** folder, right-click the ZIP file and choose **Extract All…**, then **Extract**.
3. Open the folder that appears, and keep opening the folder inside it until you can see a file called
   `README.md` and a folder called `src`.

### 4. Install the doctor

1. In that folder, click once in the **address bar** at the top of the File Explorer window (where the
   folder's name is shown), so the text is highlighted.
2. Type `powershell` and press **Enter**. A PowerShell window opens, already *in that folder*.
3. Paste this and press Enter (the dot at the end matters — it means "this folder"):

```powershell
py -m pip install --user .
```

It takes a minute and ends with `Successfully installed … ha-config-doctor-1.0.0`.
You may see a yellow message about something "not on PATH" — you can ignore it.

That's it. You can delete the ZIP file now if you like (keep the extracted folder until you've finished,
in case you want to try the examples in it).

---

## Checking your configuration

### 1. Make sure your copy is complete and up to date

Your copy of the Home Assistant `config` folder needs to include:

* `configuration.yaml` (and `automations.yaml`, `scripts.yaml`, `scenes.yaml`, `secrets.yaml`…),
* any folders such as `packages` or `blueprints`,
* and the **`.storage`** folder. It is easy to miss because its name starts with a dot, but without
  it the doctor can only partly check your entity names.

If you copy the folder over the network with the Samba share add-on, copy the **whole** `config` folder.
Do it again before each check so the doctor sees what Home Assistant is really using.

### 2. Find the full name ("path") of your copy

1. In File Explorer, open the folder that contains `configuration.yaml`.
2. Click once in the address bar at the top. It shows something like `C:\HA Copy\config`.
3. Press **Ctrl+C** to copy it.

### 3. Run the check

Open PowerShell (Start → type `PowerShell` → Enter). First move to your Documents folder, so the
report is saved there:

```powershell
cd $HOME\Documents
```

Then type the start of this command, paste your folder's path between the quote marks, and press Enter:

```powershell
py -m ha_config_doctor check "C:\HA Copy\config" --open
```

* Replace `C:\HA Copy\config` with your own path — **keep the double quote marks** around it.
* Don't put a `\` at the very end of the path.

After a few seconds it prints a short summary, for example:

```text
Result: 3 Error(s), 7 Warning(s), 12 Tidy-up(s).
```

…and your web browser opens the full report. The report is also saved in your Documents folder, in a
folder called `ha-config-doctor-report`:

* `report.html` — the easy-to-read version (double-click it to open it in your browser);
* `report.md` — the same report as plain text, handy for sending to someone who is helping you.

Each new check replaces the previous report.

### Trying it on the made-up examples first

If you'd like to see what a report looks like before using your own files, open PowerShell in the
doctor's folder (as in "Install the doctor" above) and paste:

```powershell
py -m ha_config_doctor check "samples\faulty-config" --open
```

That folder is full of deliberate mistakes in made-up automations. `samples\healthy-config` is a tidy
example that should come back with nothing to fix.

---

## Reading the report

The first page is a **one-page summary**: how many things were found, the few to **start with**, and
what was checked. After that, everything is listed in three groups:

| Group | What it means |
|---|---|
| **Error** | Something is broken, or won't work the way it looks like it should. Fix these first. |
| **Warning** | Probably works, but is likely to misbehave sometimes, or is a trap waiting to go off. |
| **Tidy-up** | Works today. Tidying it makes things easier to look after and ready for future versions. |

For each kind of problem the report says **why it matters** and **how to fix it**, then lists every
place it was found: the **file**, the **line number**, which automation or script it is in, and the
specific details.

**Finding a line:** open the file in Notepad, press **Ctrl+G**, type the line number and press Enter.
(If Ctrl+G does nothing, turn off **Format → Word Wrap** first.) Line 1 is the first line of the file.

**Making the change:** it's best to make fixes in Home Assistant itself (Settings → Automations &
scenes), or in the file on the Raspberry Pi, rather than in your copy — your copy is only for checking.
Then make a fresh copy and run the check again to see the list get shorter.

A few things are worth knowing:

* Some Warnings and Tidy-ups are matters of judgement. If you've done something on purpose (for
  example, an automation that is *meant* to ignore new triggers while it waits), it's fine to leave it.
* "A helper nothing seems to use" means nothing the doctor could *see* uses it. Something made in the
  Home Assistant screens might still use it, so check before deleting.
* Sunrise and sunset times are worked out from your home's location. If the location isn't in the
  copy, the report uses typical times and says so.
* Findings about removed or retired features also show **which versions** are affected, the
  **official page** to check, and whether the rule has been **checked** against the official release
  notes yet (at the moment none have — see below). Old-style template entities come with a
  **suggested replacement**, ready to compare with what you have.

---

## Which Home Assistant version it checks against

Whether something is a problem can depend on your version of Home Assistant. For example, old-style
template sensors still worked on 2026.5 but were removed in 2026.6. The doctor treats each rule like this:

| For your version… | It is… |
|---|---|
| the feature has been **removed** | an **Error** |
| the feature has been **marked for retirement** but still works | a **Warning** |
| it **works differently** now in a way that may catch you out | a **Warning** |
| none of that has happened **yet** in your version | a **Tidy-up** (a heads-up for later) |

The doctor reads your version from the small `.HA_VERSION` file in the config folder, so normally there
is nothing to do. If your copy doesn't have that file, the report says which version it assumed. You
can also say which version you have — you can see it in Home Assistant under **Settings → About**
("Core"):

```powershell
py -m ha_config_doctor check "C:\HA Copy\config" --ha-version 2026.10.4 --open
```

---

## How up to date are the rules?

Everything the doctor knows about removed, retired and changed features is in
[`data/ha_rules.yaml`](data/ha_rules.yaml). Each rule records the version where the feature was marked
for retirement, the version where it was removed (or changed), a plain-English explanation and fix, the
official web page to check it against, and the date it was last reviewed.

**Please read this:** when the rules were written (28 October 2026), the computer they were written on
was **not allowed to reach home-assistant.io**. So **no rule has been checked against the official
release notes, breaking-change lists or integration documentation**, and every rule is marked
**"unverified"**. Each rule also says where its information came from:

* **"owner"** — facts supplied by the owner of this set-up: old-style template entities removed in
  2026.6, `device_tracker.see` being retired in favour of template device trackers, and, from 2026.10,
  manual MQTT publishing and Synology restarts needing an administrator (while trigger IDs written in
  YAML keep working);
* **"search-summary"** — from web-search summaries of the official 2026.1–2026.10 release notes,
  changelogs and community posts (not the pages themselves);
* **"author-memory"** — older changes, from the tool author's own knowledge.

To see every rule, and what it means for a given version:

```powershell
py -m ha_config_doctor list-rules --ha-version 2026.10.4
```

The full list is also in [docs/CHECKS.md](docs/CHECKS.md#rules-about-removed-retired-and-changed-features).
If you or a helper check a rule against the official page, change its `verification` to `verified` in
`data/ha_rules.yaml` (and correct anything that's wrong) — no program code needs to change.

---

## Making a tidied copy (optional)

Tidy mode writes **corrected copies** of your files into a **new** folder. Your original folder is not
touched. It only makes changes that are *certain* to mean exactly the same thing to Home Assistant:

* renaming old names to their current ones (`service:` → `action:`, `platform:` → `trigger:`,
  `trigger:`/`condition:`/`action:` → `triggers:`/`conditions:`/`actions:`, `data_template:` → `data:`);
* putting the parts of each automation and script in the standard order (id, alias, description,
  triggers, conditions, actions, mode), and sorting named lists like helpers A to Z — but only where no
  comments would end up in the wrong place;
* making the spacing and indentation consistent.

Your comments (lines starting with `#`) are kept. Every tidied file is read back and compared with the
original using Home Assistant's own rules; if anything at all would mean something different, or a
comment would be lost, that change isn't made. Anything uncertain is **only reported, never changed**.

Paste this into PowerShell (with your own path first, then a **new** folder for the copies):

```powershell
py -m ha_config_doctor tidy "C:\HA Copy\config" "C:\HA Copy\tidied" --open
```

Your browser opens `CHANGES.html`, which lists:

* every file that was tidied, and every change in it — with the line number and the reason;
* files that were left alone, and why;
* the things that were **not** changed because they need your decision.

`secrets.yaml` is never copied. The tidied folder is still a copy of your configuration, so keep it as
private as the original.

If you'd rather nothing is put in a different order, add `--keep-order` to the end of the command.

---

## Putting tidied files back into Home Assistant

Only do this when you're happy with what `CHANGES.html` says.

1. **Make a backup first.** In Home Assistant go to **Settings → System → Backups** and choose
   **Back up now**. Wait for it to finish.
2. **Copy only the files you want** from the tidied folder into the same place in Home Assistant's
   `config` folder, replacing the old ones. Use the same way you normally copy files to Home Assistant
   (for example the Samba share add-on — in File Explorer type `\\homeassistant.local\config` in the
   address bar; your Home Assistant may use a different name).
3. In Home Assistant go to **Developer tools → YAML** and press **Check configuration**.
   If it reports a problem, restore the backup from step 1.
4. If the check is fine, press **Restart**.

Note: when you save an automation in the Home Assistant editor, Home Assistant rewrites
`automations.yaml` in its own layout. That's normal and doesn't undo the tidying of names.

---

## If something goes wrong

**"py is not recognized…"**
Python isn't installed, or PowerShell was opened before it was. Close PowerShell, open it again and
try once more. If it still fails, install Python from <https://www.python.org/downloads/>.
If `python --version` works but `py` doesn't, use `python` instead of `py` in every command.

**"No module named ha_config_doctor"**
The doctor isn't installed yet. Do [Install the doctor](#4-install-the-doctor) again, making sure the
PowerShell window was opened *in the folder that contains README.md*.

**"I can't find a folder called …"**
The path is mistyped or is missing its quote marks. Copy it again from File Explorer's address bar and
put it between `"` marks.

**"The report can't be saved inside the configuration folder"**
PowerShell is currently *inside* your config folder. Type `cd $HOME\Documents`, press Enter and try
again.

**"No .storage folder with an entity list was found"**
Your copy is missing the `.storage` folder. Copy the whole `config` folder again, including `.storage`.

**"The folder … already has things in it"** (tidy mode)
To be safe, tidy mode only writes into a new or empty folder (or one it made itself before). Choose a
new folder name.

**Something else** — run the command again, copy everything PowerShell printed (drag over it with the
mouse, then press Ctrl+C) and send it, with `report.md`, to whoever is helping you.
The report has already had passwords and addresses hidden.

---

## Updating or removing it

**To update:** download the new ZIP and repeat [Download the doctor](#3-download-the-doctor) and
[Install the doctor](#4-install-the-doctor). Installing over the old version is fine.

**To see which version you have:**

```powershell
py -m ha_config_doctor --version
```

**To remove it:**

```powershell
py -m pip uninstall ha-config-doctor
```

**To list every check it makes:**

```powershell
py -m ha_config_doctor list-checks
```

---

## A few words explained

* **YAML** — the kind of text file Home Assistant's settings are written in (`.yaml` files). Spaces at
  the start of each line matter, and so do colons and quote marks.
* **Automation** — "when this happens, if these things are true, do that".
* **Trigger / condition / action** — the three parts of an automation: what starts it, what must be
  true, and what it does.
* **Script** — a list of actions you can run by name, from automations or a dashboard.
* **Entity** — one thing Home Assistant knows about, such as `light.kitchen` or
  `sensor.outside_temperature`.
* **Helper** — an entity you create yourself, such as a switch (`input_boolean`), a number
  (`input_number`) or a timer.
* **Template** — the small bits of code in `{{ }}` that work things out, like
  `{{ states('sensor.outside_temperature') }}`.
* **Blueprint** — a ready-made automation design that you fill in.
* **Package** — a file that groups related settings together, usually in a `packages` folder.
* **`!include`** — a line that tells Home Assistant to read another file at that point.
* **`!secret`** — a line that takes a value (such as a password) from `secrets.yaml`.
* **`.storage`** — the folder where Home Assistant keeps the things you set up in its screens.

---

## For helpers and developers

The rest of this page is technical.

### Running from source and the tests

```bash
python -m pip install -e ".[test]"
python -m pytest
```

The tests cover the YAML reader, `!include` handling, every check (each with an example that should
and one that shouldn't trigger it), the entity cross-check, tidy mode (including proof that tidied files
mean the same and that originals are never modified), the reports, the command line, redaction, and a
repository scan for addresses, e-mails and tokens. One test fails if any check in the catalogue isn't
triggered by the samples; another fails if the healthy sample produces any finding.

### Commands

```text
ha-config-doctor check CONFIG_FOLDER [--report-folder DIR] [--open] [--ha-version VERSION] [--rules FILE]
ha-config-doctor tidy CONFIG_FOLDER OUTPUT_FOLDER [--keep-order] [--open] [--ha-version VERSION] [--rules FILE]
ha-config-doctor list-checks [--markdown]
ha-config-doctor list-rules [--ha-version VERSION] [--rules FILE]
```

`py -m ha_config_doctor` and `ha-config-doctor` are the same program. Exit codes for `check`: `0` no
Errors, `1` Errors were found, `2` it couldn't run.

### How it works

* `yamlio.py` reads YAML with PyYAML's safe loader — the same YAML 1.1 rules Home Assistant uses — and
  records the file and line of every value. Home Assistant's `!` tags are kept as objects.
* `configtree.py` follows `!include`, `!include_dir_list`, `!include_dir_named`,
  `!include_dir_merge_list` and `!include_dir_merge_named` with Home Assistant's rules (`.yaml` only,
  hidden files skipped, `secrets.yaml` skipped, case-sensitive like Linux). `secrets.yaml` is scanned
  for names only.
* `registry.py` reads an allow-list of `.storage` files and keeps only the fields the checks need.
* `model.py` gathers automations, scripts, scenes, helpers, defined entities and every entity reference.
* `templates.py` analyses templates with Jinja's own parser.
* `checks/` holds the checks; `catalog.py` holds every check's title, severity, explanation and fix.
* `data/ha_rules.yaml` holds every fact about removed, retired and changed features (versions,
  explanations, sources, verification status). `rules.py` loads and checks it, works out the Home
  Assistant version (`.HA_VERSION` or `--ha-version`) and turns each rule into an Error, Warning or
  Tidy-up; `checks/retired.py` finds the matching places. The file is installed inside the package as
  `ha_config_doctor/data/ha_rules.yaml`. A test fails if a retired feature's name is written into the
  program code instead.
* `tidy.py` uses ruamel.yaml to keep comments, applies only behaviour-preserving changes, then re-reads
  the result with the Home Assistant-style loader and compares it with the original (and compares the
  comments). It falls back to a more cautious level, and finally leaves the file alone, if anything
  differs.
* `report.py` writes the HTML and Markdown reports and the tidy change log; all text passes through
  `redact.py`.

### Adding or correcting a rule about a removed feature

Edit `data/ha_rules.yaml` (the comments at the top explain every field and the kinds of rule), then run
the tests: one of them builds a small configuration for every rule and checks the rule finds it.
Regenerate `docs/CHECKS.md` afterwards (below).

### Continuous testing

`.github/workflows/tests.yml` runs the tests on Windows and Ubuntu (Python 3.10 and 3.13), and runs the
Windows commands from this README exactly as written, in Windows PowerShell 5.1, against a copied config
folder whose path has a space in it and is typed with a trailing backslash.

### Adding a check

1. Add it to `catalog.py` (code, severity, plain-English title, why, fix).
2. Implement it in the right module in `checks/`.
3. Add a deliberate example to `samples/faulty-config` (the samples test insists on it) and a
   good/bad pair to the tests.
4. Regenerate the check list: `python -m ha_config_doctor list-checks --markdown > docs/CHECKS.md`.

### The samples

Everything in `samples/` is made up: no real names, places, addresses, devices or passwords. The
"secrets" are labelled `FAKE-…`, e-mail addresses use `example.com`, web addresses end in `.invalid`,
and the network addresses used in the tests come from the ranges reserved for documentation.

* `faulty-config` — deliberately wrong in every way the doctor can detect.
* `healthy-config` — the doctor should find nothing.
* `no-storage-config` — no `.storage` folder and no `secrets.yaml`.
* `not-a-config-folder` — no `configuration.yaml` at all.
