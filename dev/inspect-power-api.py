# Stationary, read-only MicroPython introspection. Run with vexaim exec -f.
# Only names and nonexecuting metadata are printed; no candidate method is called.
import json
import sys

import vex

terms = ("power", "alive", "idle", "sleep", "init", "system", "sys")
robot_instance = globals()["robot"]  # Supplied by the CLI's exec preamble.
sleep_control = getattr(robot_instance, "_sleep_disable", None)
sleep_doc = getattr(sleep_control, "__doc__", None)
print(
    json.dumps(
        {
            "robot_names": [
                name
                for name in dir(robot_instance)
                if any(t in name.lower() for t in terms)
            ],
            "vex_names": [
                name for name in dir(vex) if any(t in name.lower() for t in terms)
            ],
            "builtin_modules": list(getattr(sys, "builtin_module_names", ())),
            "loaded_modules": list(sys.modules),
            "sleep_control": {
                "present": sleep_control is not None,
                "callable": callable(sleep_control),
                "kind": str(type(sleep_control)),
                "doc": str(sleep_doc)[:200] if sleep_doc is not None else None,
            },
        }
    )
)
