#!/usr/bin/env python3
# cron wrapper: the question to the owner, no model. Empty stdout = silence,
# which is what a quiet queue must look like. See INSTALL.md.
import os, sys
os.execvp("python3", ["python3", "/opt/data/skills/calls/scripts/gate.py", "ask"] + sys.argv[1:])
