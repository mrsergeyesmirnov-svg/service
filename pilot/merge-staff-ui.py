"""Resolve the staff-removal merge against the server browser-login UI."""
import re
import subprocess
from pathlib import Path

p = Path("pilot/pilot.js")
s = p.read_text()
assert s.count("<<<<<<< HEAD") >= 1
s = re.sub(r"<<<<<<< HEAD\n(.*?)=======\n.*?>>>>>>> origin/main\n", r"\1", s, flags=re.S)
t = subprocess.check_output(["git", "show", ":3:pilot/pilot.js"]).decode()
start = "if(view==='team')"
end = "if(view==='courses')"
s = s[:s.index(start)] + t[t.index(start):t.index(end)] + s[s.index(end):]
action = t.split("case'remove-staff':")[1].split("case'approve-staff':")[0]
if "case'remove-staff':" not in s:
    s = s.replace("case'approve-staff':", "case'remove-staff':" + action + "case'approve-staff':")
assert "<<<<<<<" not in s and "browser-login" in s and "remove-staff" in s
p.write_text(s)
