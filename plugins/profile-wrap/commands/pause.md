---
description: Pause posting, comment drafting or everything. Every job and API call checks the flag first.
argument-hint: "[--posting | --comments | --all]  (or: resume)"
---
Run `profile-wrap pause $ARGUMENTS`. With no argument everything is paused.
To undo, run `profile-wrap resume $ARGUMENTS`. Jobs that find the flag exit with
code 4 and do nothing. Tell the user exactly what is paused and how to resume.
