"""English texts. Keys: usage.* (one-line command usage, shown in !help), help.* (detailed help per
command: help.<command>[.<sub>], plus help.group.*, help.area.*, help.role.*), err.* (errors),
msg.* (replies), web.* (signup pages). Replies are Markdown. strings/de.py later mirrors the keys.

Texts without parameters are returned as they are, so they may contain literal braces (the help
texts are never formatted). Texts with parameters need doubled braces for literal ones.

Every reply should tell the reader what happened, why, and what to do next.
"""

STRINGS: dict[str, str] = {
    # --- usage (one line each, shown in !help) -----------------------------------------------
    "usage.help": "`!help [<command>]`: this overview, or details and examples for one command",
    "usage.whoami": "`!whoami`: your roles and courses",
    "usage.confirm": "`!confirm <code>`: run a plan I proposed",
    "usage.cancel": "`!cancel`: drop your pending plan, or stop me waiting for a file",
    "usage.admin.prof": "`!admin prof add|remove|list [@user]`: who counts as a professor",
    "usage.admin.audit": "`!admin audit [n]`: the last n audit entries",
    "usage.admin.bots": "`!admin bots pending|approve <id>|reject <id> [reason]|disable-all`: professor bots",
    "usage.course.create": '`!course create <code> "<title>" [--semester HS26] [--template <name>]`: new course',
    "usage.course.list": "`!course list`: your courses",
    "usage.course.info": "`!course info <code>`: staff, rooms, numbers of a course",
    "usage.course.ta": "`!course ta add|remove <code> @user`: appoint or remove a TA",
    "usage.course.archive": "`!course archive <code> [--kick-students] [--dry-run]`: make a course read-only",
    "usage.course.rollover": "`!course rollover <code> <new-semester>`: same course for a new semester",
    "usage.room.add": '`!room add <code> "<name>" [--private] [--topic "..."]`: add a room to a course',
    "usage.room.remove": '`!room remove <code> "<room>"`: take a room out of a course',
    "usage.invite": "`!invite <code> [--dry-run]` + email list: bring people into a course",
    "usage.roster.sync": "`!roster sync <code> [--remove] [--dry-run]` + email list: compare a list with the course",
    "usage.groups.create": "`!groups create <code> <n>`: create n exercise group rooms",
    "usage.groups.assign": "`!groups assign <code> [--auto]` (+ CSV email,group): put people into groups",
    "usage.groups.post": "`!groups post <code>` + CSV group,message or email,message: one message per group/student",
    "usage.template.export": "`!template export <code> [<name>]` or `--saved <name>`: save and download a layout",
    "usage.template.import": "`!template import <name> [--global]` + .yaml file: import a layout",
    "usage.template.list": "`!template list`: your and the global templates",
    "usage.template.delete": "`!template delete <name> [--global]`: delete a template",
    "usage.signup.new": "`!signup new <email> [course]`: signup link for one person",
    "usage.signup.guest": "`!signup guest <email> <name> [course]`: signup link for a guest without unibas address",
    "usage.signup.list": "`!signup list [course]`: signup links that weren't used yet",
    "usage.signup.revoke": "`!signup revoke <email|@user>`: make open links stop working",
    "usage.signup.renew": "`!signup renew <email|@user>`: new link, the old one stops working",
    "usage.signup.reset": "`!signup reset @user`: password-reset link",
    "usage.bot.create": "`!bot create <name>` + .mbp file: request your own bot",
    "usage.bot.update": "`!bot update <name>` + .mbp file: new plugin version",
    "usage.bot.list": "`!bot list`: your bots",
    "usage.bot.info": "`!bot info <name>`: status, version, rooms",
    "usage.bot.config": "`!bot config <name>`: download the config; as a reply to a .yaml: replace it",
    "usage.bot.start": "`!bot start <name>`: start a stopped bot",
    "usage.bot.stop": "`!bot stop <name>`: stop a bot (it stays set up)",
    "usage.bot.delete": "`!bot delete <name>`: delete a bot and its account",
    # --- help overview ------------------------------------------------------------------------
    "help.area.basics": "Basics",
    "help.area.courses": "Courses and rooms",
    "help.area.people": "People and signup links",
    "help.area.groups": "Exercise groups",
    "help.area.templates": "Course templates",
    "help.area.bots": "Your own bots",
    "help.area.admin": "Administration",
    "help.role.admin": "bot admins",
    "help.role.professor": "professors (for an existing course: its owner)",
    "help.role.ta": "course staff (the course owner and its TAs)",
    "help.role.any": "everyone I know",
    # --- help per command group (shown by !help <command>) ------------------------------------
    "help.group.course": "**Courses.** A course is a Matrix *space* with rooms inside. Whoever creates it owns it; TAs help with people and groups.",
    "help.group.room": "**Rooms** inside a course you own.",
    "help.group.roster": "**Roster**: check a course against an official list of participants.",
    "help.group.groups": "**Exercise groups**: one private room per group, people assigned by list or automatically, and messages per group or per student.\nUsual order: `create`, then `assign`, then `post`.",
    "help.group.template": "**Templates** store a course layout (rooms, names, topics, settings, but no people) so you can create the next course the same way.",
    "help.group.signup": "**Signup links.** New people get their account through a personal link: it fixes their username (from the university email address), works once and expires after 14 days.",
    "help.group.bot": "**Your own bots.** Upload a maubot plugin (.mbp file) and I set up a bot account that runs it. You can then invite the bot to your rooms.",
    "help.group.admin": "**Administration** for bot admins.",
    # --- detailed help per command (shown by !help <command> <sub>) ---------------------------
    "help.help": """Without anything after it, `!help` lists the commands you can use, grouped by topic. With a command, it explains that command: what it does, its options, an example and what to do next.

**Examples**
- `!help course create`
- `!help invite`
- `!help groups` (all group commands)

**Shortcuts:** `!course help` and `!course create --help` work as well.

**Who:** everyone I know.""",
    "help.whoami": """Shows your Matrix ID, your roles (admin, professor) and the courses where you are staff, with your role there (owner or ta).

Useful when I say you are not allowed to do something: the roles listed here decide what you can do.

**Who:** everyone I know.""",
    "help.confirm": """Commands that change many things at once (`!invite`, `!roster sync --remove`, `!groups ...`, `!course archive`, `!bot delete`) don't act right away. First I reply with a **plan**: what would happen, how many people or rooms are affected, and a four-character code. Nothing has changed at that point.

`!confirm <code>` runs the plan:
- Only the person who made the plan can confirm it.
- A plan expires after 10 minutes (configurable), and a new plan replaces your previous one.
- Your rights are checked again when you confirm.
- The work runs as a *job* in the background. I post one progress message, update it as I go, and send a summary at the end. You can use other commands in the meantime.

**Example:** `!confirm 7f3k`

**Who:** everyone I know (for their own plans).""",
    "help.cancel": """Drops your pending plan (the one waiting for `!confirm`) and stops me from waiting for a file you were asked to send. Nothing is changed.

A job that already started can't be cancelled: it finishes and reports what it did.

**Who:** everyone I know.""",
    "help.course.create": """Creates a course: a Matrix *space* called `<code> <title> (<semester>)` with rooms inside. You become its owner with full rights.

Without a template the rooms are **Announcements** (only staff can post), **General**, **Questions** and **Staff** (only you and your TAs). Everyone in the course space can join the other rooms. All rooms are end-to-end encrypted.

**Arguments**
- `<code>`: short, unique course code, e.g. `CS101` (letters, digits, `.`, `_`, `-`; stored in capitals)
- `"<title>"`: the course title, in quotes if it has spaces
- `--semester HS26`: HS = autumn, FS = spring, plus the year. Default: the current semester.
- `--template <name>`: use a saved layout instead of the default (see `!template list`)

**Example**
`!course create CS101 "Introduction to Computer Science" --semester HS26`

**Next steps**
- `!course ta add CS101 @name:server`: appoint TAs
- `!invite CS101` with a list of email addresses: bring in the students
- `!room add CS101 "Lab"`: add rooms

**Who:** professors. If I say you are not allowed, ask a bot admin to add you (`!admin prof add`).""",
    "help.course.list": """Lists the courses you own or are a TA of, with semester and your role. Bot admins see every course. Archived courses are marked.

**Next steps:** `!course info <code>` for details of one course.

**Who:** everyone I know.""",
    "help.course.info": """Shows a course's title, semester, owner and TAs, the number of students (joined or invited), its rooms, the number of signup links nobody has used yet, whether it is archived, and a link to the space.

**Example:** `!course info CS101`

**Who:** course staff (the owner and TAs) and bot admins.""",
    "help.course.ta": """Appoints or removes a teaching assistant for one course.

- **add**: the person becomes staff of the course. They are invited to every room of the course (including Staff and group rooms) and get moderator rights there. They can then invite people, compare rosters and manage groups for this course, but they can't delete, archive or roll over the course.
- **remove**: the moderator rights are taken away and they are removed from staff-only rooms. They stay in the normal course rooms like any member.

The person needs an account already. Write their full Matrix ID, e.g. `@max.muster:matrix.dmi.unibas.ch` (in Element: click their name to see it).

**Examples**
- `!course ta add CS101 @max.muster:matrix.dmi.unibas.ch`
- `!course ta remove CS101 @max.muster:matrix.dmi.unibas.ch`

**Who:** the course owner and bot admins.""",
    "help.course.archive": """Closes a course at the end of the semester. Everything stays readable, but:
- students can't post anymore (only staff can)
- every room gets an `[Archiv <semester>]` prefix
- the space is added to the server's archive space, if an admin set one up
- with `--kick-students` students are also removed from all rooms

This goes through a plan you confirm with `!confirm`. Use `--dry-run` to only see the plan.

**Example:** `!course archive CS101`

**Next steps:** for the next semester, use `!course rollover` (before or after archiving).

**Who:** the course owner and bot admins.""",
    "help.course.rollover": """Prepares a course for a new semester:
1. The current course is renamed to `<code>-<old semester>` (e.g. `CS101-HS26`), so its code stays free. Its rooms and members are not touched.
2. A new course `<code>` is created for the new semester with the same rooms and settings, the same owner and the same TAs. No students are carried over.

**Example:** `!course rollover CS101 FS27`

**Next steps**
- `!invite CS101` with the new list of students
- `!course archive CS101-HS26` to make the old course read-only

**Who:** the course owner and bot admins.""",
    "help.room.add": """Adds a room to a course.

- Default: every member of the course space can find and join it.
- `--private`: only staff are invited; nobody else can join (like the Staff room).
- `--topic "..."`: a short description shown at the top of the room.

The owner and TAs are invited and get their usual rights.

**Examples**
- `!room add CS101 "Lab sessions" --topic "Questions about the weekly lab"`
- `!room add CS101 "Grading" --private`

**Who:** the course owner and bot admins.""",
    "help.room.remove": """Takes a room out of a course space, so it no longer appears in the course. The room itself, its members and its history still exist; people who are in it stay in it.

Name the room as it is shown (in quotes if it has spaces) or by its room ID. `!course info <code>` lists the rooms.

**Example:** `!room remove CS101 "Lab sessions"`

**Who:** the course owner and bot admins.""",
    "help.invite": """Brings a list of people into a course. Give the email addresses below the command (one per line, or separated by commas or spaces), or send a .txt/.csv file after the command. Only university addresses work; both `@unibas.ch` and `@stud.unibas.ch` for the same name count as one person.

First I reply with a plan:
- **existing accounts** get an invitation to the course space (they accept it in Element)
- **new people** get a personal signup link. After `!confirm` I send you the links as `signup-links.csv` with a text you can send with mail merge. When someone uses the link, their account is created and they are added to the course automatically.
- **unusable entries** (not a university address, typos) are listed so you can fix them

**Example**
```
!invite CS101
anna.beispiel@stud.unibas.ch
max.muster@unibas.ch
```
then `!confirm <code>`.

Options: `--dry-run` shows the plan only.

**Next steps:** send the links from the CSV to the new people. `!signup list CS101` shows links that weren't used yet, `!signup renew <email>` replaces a lost one.

**Who:** course staff (the owner and TAs) and bot admins.""",
    "help.roster.sync": """Compares an official participant list (email addresses, pasted below the command or as a .txt/.csv file) with the people in the course space. Staff are never counted or touched.

I reply with:
- who is on the list but **missing** in the course (invite them with `!invite`)
- who is in the course but **not on the list**

With `--remove`, the people not on the list are removed from the course space and all its rooms. That goes through a plan you confirm with `!confirm`. Without `--remove` nothing is changed.

**Examples**
- `!roster sync CS101` and then send the list as a file
- `!roster sync CS101 --remove` with the list below the command

**Who:** course staff (the owner and TAs) and bot admins.""",
    "help.groups.create": """Creates exercise group rooms `Group 1` to `Group n` in a course. Group rooms are private: only staff are invited at first; students get in through `!groups assign`. If groups exist already, the numbering continues (e.g. Group 5 to 8).

This goes through a plan you confirm with `!confirm`.

**Example:** `!groups create CS101 8`

**Next steps:** `!groups assign CS101 --auto` or with a CSV file.

**Who:** course staff (the owner and TAs) and bot admins.""",
    "help.groups.assign": """Puts people into group rooms (they get an invitation to their group room).

- `--auto`: splits all students who have joined the course space evenly across the existing groups.
- Otherwise send a CSV file with the columns `email` and `group` (Matrix IDs work too, in a column called `user`). An optional `role` column with `ta` gives that person moderator rights in that group room (e.g. the TA who runs the group).

**CSV example**
```
email,group,role
anna.beispiel@stud.unibas.ch,1,
max.muster@stud.unibas.ch,2,
tutor.one@unibas.ch,1,ta
```
Excel: save as "CSV UTF-8"; `;` as separator works too.

This goes through a plan you confirm with `!confirm`; `--dry-run` shows the plan only.

**Who:** course staff (the owner and TAs) and bot admins.""",
    "help.groups.post": """Sends one message per group room or per student, e.g. points or feedback. Send a CSV file after the command:

- `group,message`: the message is posted in that group's room
- `email,message`: the message goes to that student in a direct chat with me

**CSV example**
```
group,message
1,"Sheet 3: 18/20 points, well done"
2,"Sheet 3: 15/20 points, see the comments on task 2"
```
Put messages with commas in quotes.

I always show a preview and wait for `!confirm`. After sending, the messages are deleted from my database.

**Who:** course staff (the owner and TAs) and bot admins.""",
    "help.template.export": """Saves the layout of a course as a template and sends it to you as a .yaml file. The layout contains the room names, topics, order and settings (who can join, who can post, encryption) and the number of group rooms. People and messages are not included.

- `!template export <code> [<name>]`: save under `<name>` (default: the course code) and send the file
- `!template export --saved <name>`: send a saved template again, even if its course no longer exists

**Example:** `!template export CS101 lecture-with-labs`

**Next steps:** `!course create <code> "<title>" --template lecture-with-labs`. You can also edit the file and load it again with `!template import`.

**Who:** the course owner and bot admins.""",
    "help.template.import": """Loads a layout from a .yaml file and saves it as a template. Send the command, then the file (or reply to an uploaded file with the command). I check the file first and tell you what is wrong, if anything.

`--global` makes it available to all professors (bot admins only). Without it, the template is only yours.

**Format**
```
version: 1
space: {name: "{code} {title} ({semester})", topic: ""}
defaults: {join_rule: restricted, encryption: true, history_visibility: shared}
rooms:
  - {name: "Announcements", power_levels: {events_default: 50}}
  - {name: "General"}
  - {name: "Staff", members: staff}
groups: {count: 0, name: "Group {n}"}
```
The easiest start is a file from `!template export`.

**Example:** `!template import lecture-with-labs`, then send the file.

**Who:** professors; `--global` only bot admins.""",
    "help.template.list": """Lists the templates you can use with `!course create ... --template <name>`: your own (personal) and the ones for everyone (global).

**Who:** professors.""",
    "help.template.delete": """Deletes one of your templates. Courses created from it are not affected. `--global` deletes a global template (bot admins only).

**Example:** `!template delete lecture-with-labs`

**Who:** professors; `--global` only bot admins.""",
    "help.signup.new": """Creates a signup link for one person, for example a latecomer. Their username is fixed by the email address: `anna.beispiel@stud.unibas.ch` becomes `@anna.beispiel`. The link works once and expires after 14 days.

With a course code, the person is added to that course as soon as they sign up. If they already have an account, I invite them to the course right away instead.

**Examples**
- `!signup new anna.beispiel@stud.unibas.ch CS101`
- `!signup new max.muster@unibas.ch`

**Next steps:** send the link (I include a text you can forward). For many people at once, use `!invite`.

**Who:** professors; TAs only with a course they are staff of.""",
    "help.signup.guest": """Creates a signup link for someone without a university address, e.g. a guest lecturer. Their username becomes `@guest.<name>`.

**Example:** `!signup guest jane@example.org jane.doe CS101`

**Who:** bot admins.""",
    "help.signup.list": """Lists signup links that haven't been used yet: for whom, for which course, when they expire and who created them. With a course code, only links of that course.

**Example:** `!signup list CS101`

**Who:** course staff for their courses; professors also see the links they created; bot admins see all.""",
    "help.signup.revoke": """Makes all open signup links of a person stop working, e.g. if a link was sent to the wrong address. Give the email address or the Matrix ID.

**Example:** `!signup revoke anna.beispiel@stud.unibas.ch`

**Next steps:** `!signup new <email>` if they need a new link.

**Who:** whoever created the link, course staff of its course, and bot admins.""",
    "help.signup.renew": """Replaces all open signup links of a person with one new link (e.g. the old one got lost or is about to expire). The old links stop working; the course memberships stay.

**Example:** `!signup renew anna.beispiel@stud.unibas.ch`

**Who:** whoever created the link, course staff of its course, and bot admins.""",
    "help.signup.reset": """Creates a password-reset link for an existing account. It works once and expires after 24 hours. When it is used, all the person's sessions are logged out and I tell them in a direct chat that their password was reset.

Only give the link to the account owner: whoever opens it can take over the account. Encrypted messages stay readable for them only if they have their recovery key.

**Example:** `!signup reset @anna.beispiel:matrix.dmi.unibas.ch`

**Who:** bot admins.""",
    "help.bot.create": """Requests your own bot: send this command, then your maubot plugin as an .mbp file (or reply to the uploaded file with the command).

**What I check:** the file is a valid maubot plugin; its plugin ID (`id:` in maubot.yaml) is not used by another professor; it only needs Python packages the server has. If something is wrong, I tell you what, and you can send a corrected file without repeating the command.

**Then:** an admin approves the request (I message you either way). I create the account `@bot.<you>.<name>` and start the bot. Invite it to your rooms; it joins by itself.

**Names:** 1-24 lowercase letters, digits and `-`, e.g. `quiz-bot`.

**Example:** `!bot create quiz-bot`, then send `quiz.mbp`.

**Plugin ID tip:** use an ID nobody else will use, e.g. `ch.unibas.<your.name>.quiz`.

**Who:** professors (up to 3 bots each by default).""",
    "help.bot.update": """Replaces the plugin of one of your bots with a new version: send the command, then the new .mbp file. Raise `version:` in maubot.yaml before you build it. The same checks as for `!bot create` apply, and the update may need an admin's approval again.

**Example:** `!bot update quiz-bot`, then send the new file.

**Who:** the bot's owner and bot admins.""",
    "help.bot.list": """Lists your bots with their account, plugin and state. Bot admins see all professor bots.

**Who:** professors.""",
    "help.bot.info": """Shows one bot's account, plugin ID and version, whether it is running, and in how many rooms it is.

**Example:** `!bot info quiz-bot`

**Who:** the bot's owner and bot admins (admins: `!bot info @owner:server <name>`).""",
    "help.bot.config": """The bot's settings (the instance config of your plugin, YAML).
- `!bot config <name>`: I send you the current config as a file.
- To change it: edit the file, send it here, then reply to your uploaded file with `!bot config <name>`. The bot gets the new settings right away.

**Example:** `!bot config quiz-bot`

**Who:** the bot's owner and bot admins.""",
    "help.bot.start": """Starts a stopped bot again.

**Example:** `!bot start quiz-bot`

**Who:** the bot's owner and bot admins.""",
    "help.bot.stop": """Stops a bot. It stays set up and keeps its rooms, but doesn't answer until you start it again with `!bot start`.

**Example:** `!bot stop quiz-bot`

**Who:** the bot's owner and bot admins.""",
    "help.bot.delete": """Deletes a bot: it is stopped and removed, and its account is deactivated. The plugin is removed too if no other bot uses it. You confirm this with `!confirm`. You can later create a bot with the same name again.

**Example:** `!bot delete quiz-bot`

**Who:** the bot's owner and bot admins.""",
    "help.admin.prof": """Manages who counts as a professor (may create courses, templates and bots).
- `!admin prof list`
- `!admin prof add @user:server`: the person needs an account already
- `!admin prof remove @user:server`: their courses stay as they are

**Who:** bot admins.""",
    "help.admin.audit": """Shows the last entries of the audit log (default 20, at most 100): who did what, in which course or bot, how many people or rooms were affected, and whether it worked. Email addresses are never logged.

**Example:** `!admin audit 50`

**Who:** bot admins.""",
    "help.admin.bots": """Professor bots awaiting approval, and the kill switch.
- `!admin bots pending`: open requests
- `!admin bots approve <id>`: set the bot up (the professor is told)
- `!admin bots reject <id> [reason]`: the professor gets the reason
- `!admin bots disable-all`: stop every professor bot at once (emergency)

New requests also appear in the audit room with the plugin ID, version, checksum and dependencies.

**Who:** bot admins.""",
    # --- errors -------------------------------------------------------------------------------
    "err.not_dm": "Please send me commands in a direct chat that only you and I are in. Commands can contain email addresses and signup links, so I don't answer them in shared rooms.\nStart a direct chat with {bot} and send the command there.",
    "err.forbidden": "You are not allowed to do that. `!whoami` shows your roles, `!help` the commands they allow.",
    "err.forbidden_admin": "You are not allowed to do that: only bot admins can. `!help` lists what you can do.",
    "err.forbidden_professor": "You are not allowed to do that: only professors can. If you teach a course, ask a bot admin to add you as a professor.",
    "err.forbidden_owner": "You are not allowed to do that: only the owner of {course} (or a bot admin) can. `!course list` shows your courses and your role in them.",
    "err.forbidden_staff": "You are not allowed to do that: only the staff of {course} (its owner and TAs) can. If you should be a TA there, ask the course owner to add you with `!course ta add`.",
    "err.forbidden_staff_any": "You are not allowed to do that: only professors and course staff can.",
    "err.forbidden_signup": "You are not allowed to change the links of {user_id}: they were created by someone else for a course you don't manage. Ask the person who created them, or a bot admin.",
    "err.forbidden_bot": "You can only manage your own bots. `!bot list` shows them.",
    "err.internal": "Something went wrong on my side and the command stopped. Parts that ran before the error may already be done; check with e.g. `!course info`. Try again in a moment; if it keeps failing, tell a bot admin the time of your command (the details are in the bot log).",
    "err.matrix": "The Matrix server refused a step of this command: {detail}\nThe command stopped there. If the reason above doesn't tell you what to fix, try again in a minute; if it keeps failing, tell a bot admin.",
    "err.check_failed": "This command is unavailable right now because a server check failed when I started ({check}). It's not something you did. Please tell a bot admin; they find the details in the audit room or the bot log.",
    "err.bad_args": "I couldn't read the arguments. Put names and titles with spaces in quotes.\nUsage: {usage}",
    "err.unknown_flag": "I don't know the option {flag}.\nUsage: {usage}",
    "err.bad_user": "'{value}' is not a user of this server. Write the full Matrix ID with @ and server name, e.g. @max.muster:{server} (in Element, click a person's name to see it).",
    "err.user_not_found": "{user_id} has no account on this server. Check the spelling. If the person has never logged in, create a signup link for them first: `!signup new <email>`.",
    "err.account_exists": "{user_id} already has an account, so they don't need a signup link. To add them to a course use `!signup new <email> <course>` or `!invite <course>` (they get an invitation). If they forgot their password, a bot admin can send a reset link.",
    "err.unknown_course": "There is no course '{code}'. `!course list` shows the codes of your courses.",
    "err.course_exists": "The course code {code} is already taken. Choose another code. For a new semester of an existing course, use `!course rollover {code} <semester>` instead.",
    "err.rollover_exists": "I can't roll over {code}: the code {old_code}, which the current course would be renamed to, is already taken. Rename or delete that course first, or ask a bot admin.",
    "err.course_code": "'{code}' can't be a course code. Use up to 32 letters, digits, '.', '_' or '-', without spaces, e.g. CS101.",
    "err.semester": "'{semester}' is not a semester. Write HS (autumn) or FS (spring) plus the two-digit year, e.g. HS26 or FS27.",
    "err.same_semester": "{code} is already in {semester}. Give the new semester, e.g. `!course rollover {code} FS27`.",
    "err.course_archived": "{code} is already archived, so there is nothing to do. For the next semester use `!course rollover {code} <semester>`.",
    "err.ta_is_owner": "{user_id} owns {code} and already has all the rights a TA has.",
    "err.not_ta": "{user_id} is not a TA of {code}, so there is nothing to remove. `!course info {code}` lists the TAs.",
    "err.room_unknown": "{code} has no room '{name}'. `!course info {code}` lists its rooms; put names with spaces in quotes.",
    "err.confirm_unknown": "There is no plan with the code {code} waiting for you. Plans expire after a few minutes, a newer plan replaces an older one, and only the person who made a plan can confirm it. Send the original command again to get a new code.",
    "err.email_invalid": "'{value}' is not an email address.",
    "err.email_domain": "'{value}' is not a university address (allowed: {domains}). For guests without one, ask a bot admin (`!signup guest`).",
    "err.email_chars": "'{value}' contains characters that can't be part of a username (allowed before the @: a-z, 0-9, '.', '_', '=', '-'). Ask the person for their usual university address (firstname.lastname@...).",
    "err.email_reserved": "'{value}' would get a username that is reserved for the system (admin, bot. or guest.). Ask a bot admin to set up this account.",
    "err.guest_name": "'{value}' can't be used as a guest name. Use letters, digits, '.', '_' or '-', e.g. jane.doe.",
    "err.no_valid_emails": "I found no usable university email addresses (allowed: {domains}), so nothing was planned. Not usable: {invalid}\nPut the addresses below the command (one per line, or separated by commas or spaces), or send them as a .txt or .csv file.",
    "err.no_open_link": "{user_id} has no open signup link: it was used, revoked or has expired. If they still have no account, create a new link with `!signup new <email>`.",
    "err.no_public_url": "I can't create links because the setting signup.public_base_url is empty. A bot admin has to set it in the bot's instance config. Nothing was changed.",
    "err.reset_self": "I can't reset my own password.",
    "err.csv_empty": "The file is empty.",
    "err.csv_missing_column": "The CSV file has no '{column}' column. The first line must name the columns, e.g. `email,group` or `group,message` (see `!help groups assign` and `!help groups post`).",
    "err.csv_role": "Unknown role '{value}' in the CSV file. Use `student`, `ta` or leave it empty.",
    "err.group_number": "'{value}' is not a group number. Use 1, 2, 3 ...",
    "err.group_count": "You can create between 1 and {max} groups at a time.",
    "err.no_groups": "{code} has no group rooms yet. Create them first with `!groups create {code} <number>`, then try again.",
    "err.no_students": "{code} has no students yet (only people who joined the course space count for --auto). Invite them with `!invite {code}`, or assign with a CSV file instead.",
    "err.nothing_to_assign": "None of the entries could be used, so nothing was planned. Not usable: {invalid}\nEvery row needs a university email address (or Matrix ID) and the number of an existing group.",
    "err.nothing_to_post": "None of the rows could be used, so nothing was planned. Not usable: {invalid}\nEvery row needs an existing group number (or a university email address) and a message.",
    "err.file_missing": "The message you replied to has no file. Reply to the file itself, or send the command first and the file after it.",
    "err.file_too_large": "The file is too large (max {mb} MB).",
    "err.template_invalid": "The template is invalid: {detail}\n`!help template import` shows the format; a file from `!template export` is a good starting point.",
    "err.template_unknown": "There is no template '{name}' that you can use. `!template list` shows yours and the global ones.",
    "err.template_name": "'{name}' can't be a template name. Use letters, digits, '.', '_' or '-', e.g. lecture-with-labs.",
    "err.template_empty_course": "The course has no rooms, so there is nothing to export.",
    "err.yaml_invalid": "That is not valid YAML: {detail}\nCheck the indentation (spaces, no tabs).",
    "err.bots_disabled": "Professor bots are not enabled on this server. Ask a bot admin if you need one.",
    "err.bot_name": "'{name}' can't be a bot name. Use 1-24 lowercase letters, digits and '-', starting with a letter or digit, e.g. quiz-bot.",
    "err.bot_exists": "You already have a bot called {name}. To upload a new version use `!bot update {name}`; to start over, `!bot delete {name}` first.",
    "err.bot_unknown": "There is no bot called {name}. `!bot list` shows your bots.",
    "err.bot_quota": "You already have {limit} bots, the maximum. Delete one with `!bot delete <name>`, or ask a bot admin for an exception.",
    "err.bot_unchanged": "{name} already runs exactly this file (version {version}). If you changed the code, raise `version:` in maubot.yaml, run `mbc build` again and send the new .mbp.",
    "err.bot_request_unknown": "There is no open bot request #{id}. `!admin bots pending` lists the open ones.",
    "err.mbp_invalid": "That is not a usable maubot plugin: {detail}.",
    "err.mbp_dependencies": "The plugin needs Python packages that this server doesn't have: {deps}. Plugins can only use the packages that come with maubot. Remove the dependency from maubot.yaml (and from your code), or ask a bot admin whether it can be added to the server.",
    "err.plugin_taken": "The plugin ID `{plugin_id}` is already taken by another bot on this server. All bots share one plugin list, and uploading a plugin with the same ID would replace the other one, so I refused it.\n**How to fix it:** open `maubot.yaml` in your plugin folder, change the `id:` line to an ID only you use, e.g. `id: {suggestion}`, run `mbc build` again and send me the new .mbp file.",
    "err.userbots_api": "The bot server reported an error ({status}): {detail}\nThis is a server problem, not something you did. Please tell a bot admin.",
    # --- replies ------------------------------------------------------------------------------
    "msg.yes": "yes",
    "msg.no": "no",
    "msg.and_more": " and {n} more",
    "msg.help_header": "**What I can do for you**\nSend commands here, in our direct chat. I react with 🤖 as soon as I start working on one.",
    "msg.help_footer": "**More help:** `!help <command>` explains a command with options and an example, e.g. `!help course create`, `!help invite` or `!help groups`.\nChanges to many people or rooms are shown as a plan first and only run after `!confirm <code>`.",
    "msg.help_group_footer": "Details and an example: `!help {name} <subcommand>`, e.g. `!help {name} {example}`.",
    "msg.help_hint": "Details and examples: `!help {command}`.",
    "msg.help_unknown": "There is no command `!{name}`. `!help` lists the commands you can use.",
    "msg.help_not_for_you": "`!{command}` is only for {role}. `!help` lists the commands you can use.",
    "msg.unknown_command": "I don't know the command `!{name}`.{hint} `!help` lists the commands you can use.",
    "msg.did_you_mean": " Did you mean `{command}`?",
    "msg.subcommands": "`!{name}` needs a subcommand:\n{usages}\n\nDetails and an example: `!help {name} <subcommand>`, e.g. `!help {name} {example}`.",
    "msg.unknown_subcommand": "`!{name}` has no subcommand `{sub}`.{hint} Available:\n{usages}\n\nDetails and an example: `!help {name} <subcommand>`, e.g. `!help {name} {example}`.",
    "msg.whoami": "You are {user_id}.\nRoles: {roles}\nCourses: {courses}\n\n`!help` lists the commands these roles allow.",
    "msg.plan": "{summary}\n\nNothing has been changed yet. To run this, send `!confirm {code}` within {minutes} minutes. To drop it, send `!cancel`.",
    "msg.dry_run": "{summary}\n\n_Dry run: nothing was changed. Send the same command without `--dry-run` to get a plan you can confirm._",
    "msg.cancelled": "Cancelled. Nothing was changed.",
    "msg.nothing_to_cancel": "There was nothing to cancel: no plan is waiting for your confirmation and I'm not waiting for a file from you. A job that already started can't be cancelled.",
    "msg.waiting_for_file": "Now send me the {what} here, within {minutes} minutes (drag it into the chat or use the paperclip). `!cancel` stops waiting.",
    "msg.retry_file": "Nothing was changed. You don't have to repeat the command: send the corrected {what} here within {minutes} minutes, or `!cancel`.",
    "msg.file_generic": "file",
    "msg.file_emails": "list of email addresses (.txt or .csv file)",
    "msg.file_assign_csv": "CSV file with the columns `email,group` (optional: `role`)",
    "msg.file_post_csv": "CSV file with the columns `group,message` or `email,message`",
    "msg.file_yaml": "template (.yaml file)",
    "msg.file_mbp": "plugin (.mbp file, built with `mbc build`)",
    "msg.job_started": "Job #{id} started: 0 / {total}. I update this message as I go and send a summary at the end. You can use other commands meanwhile.",
    "msg.job_progress": "Job #{id}: {done} / {total} done, {failed} failed",
    "msg.job_done": "Job #{id} finished: {done} of {total} done, {failed} failed.",
    "msg.job_failed_hint": "The reasons are listed above. Fix them and run the command again for those entries only.",
    "msg.job_done_instantly": "Done (job #{id}).",
    "msg.job_finish_failed": "Job #{id}: the final step failed: {error}\nThe items above were processed; please tell a bot admin about the final step.",
    "msg.job_start_failed": "Job #{id}: the first step failed: {error}\nLinks that were created can be sent again with `!signup list` and `!signup renew`.",
    "msg.next.invite": "**Next:** send the signup links to the new people. Existing accounts see an invitation to the {course} space in Element. `!course info {course}` shows how many people are in; `!signup list {course}` shows links nobody has used yet.",
    "msg.next.roster_remove": "Removed people can be brought back with `!invite {course}`.",
    "msg.next.groups_create": "**Next:** put people into the groups with `!groups assign {course} --auto`, or with a CSV file (`!help groups assign`).",
    "msg.next.groups_assign": "Everyone assigned now sees an invitation to their group room. **Next:** messages per group with `!groups post {course}`.",
    "msg.next.course_archive": "{course} is now read-only for students. For the next semester: `!course rollover {course} <semester>`.",
    "msg.invalid_entries": "Not usable: {entries}",
    "msg.check_ok": "Startup check **{check}**: ok",
    "msg.check_failed": "Startup check **{check}** FAILED: {detail}",
    "msg.password_reset_notice": "Your password was just reset with a link from {admin}. All your sessions were logged out. If you didn't ask for this, contact an admin right away.",
    # admin
    "msg.prof_list": "**Professors**\n{users}",
    "msg.prof_added": "{user_id} is now a professor. They can create courses now; tell them to send me `!help` in a direct chat.",
    "msg.prof_already": "{user_id} was already a professor. Nothing changed.",
    "msg.prof_removed": "{user_id} is no longer a professor. Their courses stay as they are.",
    "msg.prof_not_listed": "{user_id} was not on the list. Nothing changed.",
    "msg.prof_in_config": "Note: {user_id} is also in the instance config `professors:` and comes back on the next restart. Remove them there too.",
    "msg.audit_list": "**Audit log**\n{entries}",
    # courses and rooms
    "msg.course_creating": "Creating {code}, this takes a few seconds ...",
    "msg.course_created": "Course **{code}** is ready: {link}\nRooms: {rooms}\nYou are invited to the space and all rooms; accept the invitations in Element.\n\n**Next steps**\n- `!course ta add {code} @user:server`: appoint TAs\n- `!invite {code}` with a list of email addresses: bring in the students\n- `!room add {code} \"<name>\"`: more rooms",
    "msg.course_list": "**Courses**\n{courses}\n\n`!course info <code>` shows the details of one course.",
    "msg.archived_marker": " [archived]",
    "msg.course_info": "**{code}** {title} ({semester})\nOwner: {owner}\nTAs: {tas}\nStudents (joined or invited): {students}\nRooms: {rooms}\nOpen signup links: {links}\nArchived: {archived}\n{link}",
    "msg.ta_added": "{user_id} is now a TA of {code} and was invited to all its rooms. They can now invite people, compare rosters and manage groups for {code}; `!help` shows them how.",
    "msg.ta_removed": "{user_id} is no longer a TA of {code}: their moderator rights are gone and they were removed from staff-only rooms.",
    "msg.kick_reason_ta": "No longer a TA of this course",
    "msg.kick_reason_archive": "Course archived",
    "msg.kick_reason_roster": "Not on the course list anymore",
    "msg.archive_plan": "Archive **{code}**: {rooms} rooms (incl. the space) become read-only for students and get an [Archiv] prefix.{kick}",
    "msg.archive_kick": " Students are removed.",
    "msg.rollover_done": "**{code}** for {semester} is ready, with the same rooms and staff: {link}\nThe previous course is now **{old_code}**.\n\n**Next steps**\n- `!invite {code}` with the new list of students\n- `!course archive {old_code}` to make the old course read-only",
    "msg.room_added": "Room **{name}** added to {code}. Everyone in the course can find and join it; staff were invited.",
    "msg.room_added_private": "Private room **{name}** added to {code}. Only staff were invited; nobody else can join.",
    "msg.room_removed": "**{name}** is no longer part of {code}. The room itself and its history still exist, and its members stay in it.",
    # invites, roster, groups
    "msg.invite_plan": "Invite to **{code}**: {existing} existing accounts get an invitation, {new} new people get a signup link (as a CSV file after you confirm), {invalid} entries are not usable.",
    "msg.csv_delivery": "Here are the signup links for {count} new people. Send each person their link, e.g. with mail merge in Outlook/Word (column `link`):\n\n> Hello, please create your account for the course chat: {{link}}\n> The link works once and expires in 14 days. Afterwards log in at {login_url}.\n\nThey are added to the course automatically when they sign up.",
    "msg.roster_summary": "Roster **{code}**: {listed} on the list, {unchanged} already in the course, {missing} missing, {extra} in the course but not on the list.",
    "msg.roster_missing": "Missing: {users}\nInvite them with `!invite {code}` and the same list.",
    "msg.roster_extra": "Not on the list: {users}",
    "msg.roster_remove_hint": "To remove them, send the same command with `--remove`. Nothing was changed.",
    "msg.group_name": "Group {n}",
    "msg.group_name_format": "Group {n}",
    "msg.groups_create_plan": "Create {count} group rooms in **{code}** (Group {first} to Group {last}), staff invited.",
    "msg.groups_assign_plan": "Assign {count} people in **{code}**: {per_group}",
    "msg.groups_post_plan": "Send {count} messages for **{code}**. Preview:\n{preview}",
    # signup links
    "msg.inline_signup": "Signup link for **{user_id}** ({email}):\n{link}\n\nText to forward:\n> Please create your account for the DMI chat: {link}\n> The link works once. Afterwards log in at {login_url} as {user_id}.",
    "msg.inline_reset": "Password-reset link for **{user_id}** (valid 24 hours, works once):\n{link}\n\nOnly give it to the account owner. They will be notified when it is used.",
    "msg.signup_exists_invited": "{user_id} already has an account, so no link is needed: I invited them to {code}. They accept the invitation in Element.",
    "msg.signup_list": "**Open signup links**\n{links}",
    "msg.signup_line": "- {user_id}, course {course}, expires {expires}, by {by}",
    "msg.signup_revoked": "{count} open link(s) of {user_id} no longer work. If they need a new one: `!signup new <email>`.",
    # templates
    "msg.template_exported": "Saved the layout of {code} as your template `{name}`. Use it with `!course create <code> \"<title>\" --template {name}`. The file:",
    "msg.template_saved": "Template `{name}` saved ({scope}). Use it with `!course create <code> \"<title>\" --template {name}`.",
    "msg.template_list": "**Templates**\n{templates}\n\nUse one with `!course create <code> \"<title>\" --template <name>`.",
    "msg.template_deleted": "Template `{name}` deleted. Courses created from it are not affected.",
    "msg.scope_personal": "personal",
    "msg.scope_global": "global",
    # professor bots
    "msg.bot_requested": "Request #{id} for your bot **{name}** is waiting for an admin's approval. I'll message you here as soon as it's decided; there is nothing more to do for now.",
    "msg.bot_provisioning": "Setting up bot **{name}** ... I'll message you here when it's running (usually within a minute).",
    "msg.bot_request_audit": "Bot request **#{id}** ({action}) from {owner}: `{name}`, plugin `{plugin_id}` v{version}, sha256 `{sha256}`, dependencies: {deps}\n`!admin bots approve {id}` or `!admin bots reject {id} [reason]`",
    "msg.bot_requests": "**Pending bot requests**\n{requests}",
    "msg.bot_request_line": "- #{id} {action} `{name}` by {owner}: `{plugin_id}` v{version}",
    "msg.bot_approved": "Request #{id} approved, job #{job} sets it up. The owner is told when it's running.",
    "msg.bot_rejected_admin": "Request #{id} rejected. The owner was told.",
    "msg.bot_rejected": "Your bot request **{name}** was rejected by {admin}. Reason: {reason}\nIf you have questions, contact {admin}. Once the problem is fixed you can send `!bot create {name}` again.",
    "msg.bot_ready": "Your bot **{name}** is running as {user_id} (plugin `{plugin_id}`).\n\n**Next steps**\n- Invite {user_id} to a room (room info, then *Invite*); it joins by itself.\n- `!bot info {name}` shows its status, `!bot config {name}` its settings.",
    "msg.bot_updated": "Bot **{name}** now runs version {version}.",
    "msg.bot_list": "**Bots**\n{bots}",
    "msg.bot_info": "**{name}** ({user_id})\nPlugin: `{plugin_id}` v{version}\nStatus: {status}\nRooms: {rooms}",
    "msg.bot_running": "running",
    "msg.bot_stopped": "stopped (start it with `!bot start`)",
    "msg.bot_started": "Bot **{name}** started.",
    "msg.bot_stopped_now": "Bot **{name}** stopped. It keeps its rooms; `!bot start {name}` starts it again.",
    "msg.bot_config_saved": "Config of **{name}** saved. The bot uses it right away.",
    "msg.bot_delete_plan": "Delete bot **{name}**: it is stopped and removed, and its account {user_id} is deactivated.",
    "msg.bots_disabled_all": "Stopped {count} professor bots. Owners can start theirs again with `!bot start`.",
    # --- signup pages ---------------------------------------------------------------------------
    "web.title": "DMI Matrix account",
    "web.signup.intro": "Create your account. Your username is:",
    "web.reset.intro": "Set a new password for:",
    "web.displayname": "Display name (optional)",
    "web.password": "Password",
    "web.password_confirm": "Repeat password",
    "web.password_hint": "At least {n} characters.",
    "web.submit.signup": "Create account",
    "web.submit.reset": "Set password",
    "web.reset.warning": "All your sessions will be logged out. Messages in encrypted rooms stay readable only if you have your recovery key.",
    "web.done": "Your account is ready.",
    "web.done_reset": "Your new password is set.",
    "web.username": "Username",
    "web.server": "Server",
    "web.done_hint": "Log in with Element or any Matrix app using this server and username.",
    "web.error.invalid": "This link is invalid or has expired. Ask for a new one.",
    "web.error.password_mismatch": "The passwords don't match.",
    "web.error.password_short": "The password must have at least {n} characters.",
    "web.error.rate_limited": "Too many attempts. Please try again later.",
    "web.error.generic": "Something went wrong. Please try again later.",
}
