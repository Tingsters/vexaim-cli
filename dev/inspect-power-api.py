# Stationary, read-only MicroPython introspection. Run with vexaim exec -f.
# Only names are printed; no candidate method is called.
import json
import sys

import vex

terms = ("power", "alive", "idle", "sleep", "init", "system", "sys")
print(
    json.dumps(
        {
            "robot_names": [
                name for name in dir(robot) if any(t in name.lower() for t in terms)
            ],
            "vex_names": [
                name for name in dir(vex) if any(t in name.lower() for t in terms)
            ],
            "builtin_modules": list(getattr(sys, "builtin_module_names", ())),
            "loaded_modules": list(sys.modules),
        }
    )
)
