#!/usr/bin/env python
import argparse
import atexit, os, inspect
import importlib
import sys
from dataclasses import dataclass
from typing import Optional, Any, Callable

@dataclass
class ClassAttributes:

    attributes: dict[str, int]
    class_information: str

# Define the tracer function
def reads_tracer(frame: Any, event: str, arg: Optional[Any] = None) -> Callable:
    """Trace each class's __init__() method to track attributes reads"""
    # Disable tracing lines inside the frame
    frame.f_trace_lines = False

    #if event != 'return' or '__qualname__' not in frame.f_locals:
    if event != 'return' or 'self' not in frame.f_locals:
        return reads_tracer
    #print(getattr(getmodule(globals(), frame.f_locals['__module__']), frame.f_locals['__qualname__']))

    # Extract the frame's code object
    code = frame.f_code

    # Create a global set of previous hooks if it doesn't exist
    global __previous_hooks

    if "__previous_hooks" not in globals():
        __previous_hooks = set()
        print("Collection started")
        atexit.register(print_report)

    # Extract the line number
    line_no = frame.f_lineno

    # Skip if the code+line combination is already in the set
    if f"{code}{line_no}" in __previous_hooks:
        return reads_tracer

    # Add the code+line combination to the set
    __previous_hooks.add(f"{code}{line_no}")

    record_class_init_attrbiutes(frame.f_locals['self'], frame)

    return reads_tracer


def record_class_init_attrbiutes(self, frame):
    """Enumerate class attributes and set hook to reading attributes"""
    # print(dir(self))

    the_class = type(self)
    if hasattr(the_class, "__already_decorated"):
        return

    orig_getattr = the_class.__getattribute__
    orig_setattr = the_class.__setattr__
    global __reads_count
    if "__reads_count" not in globals():
        global __reads_count
        __reads_count = {}

    if the_class not in __reads_count:
        traceback = inspect.getframeinfo(frame=frame)
        __reads_count[the_class] = ClassAttributes(class_information=f"{traceback.filename}:{traceback.lineno}",
                                                   attributes={})

    def getattribute(self, attr_name):
        """Record attrbibute was read"""
        global __reads_count
        the_class = type(self)

        if the_class in __reads_count:
            if attr_name not in __reads_count[the_class].attributes:
                __reads_count[the_class].attributes[attr_name] = 0
            __reads_count[the_class].attributes[attr_name] += 1
        return orig_getattr(self, attr_name)


    def setattr(self, attr_name, value):
        """Record attrbibute was written"""
        global __reads_count
        the_class = type(self)
        if the_class in __reads_count and attr_name not in __reads_count[the_class].attributes:
            __reads_count[the_class].attributes[attr_name] = 0
        return orig_setattr(self, attr_name, value)


    # Initialize counter for each attribute
    try:
        for attr_name in dir(self):
            try:
                if not attr_name.endswith('__') and not callable(getattr(self, attr_name)):
                    __reads_count[the_class][attr_name] = 0
            except Exception:
                pass
        the_class.__getattribute__ = getattribute
        the_class.__setattr__ = setattr
    except Exception:
        pass
    try:
        the_class.__already_decorated = True
    except Exception:
        pass


def print_report():
    sys.settrace(None)
    if "__reads_count" not in globals():
        print("No data collected")
        return
    for the_class, attrs in __reads_count.items():
        class_name = the_class.__name__
        for attr, count in attrs.attributes.items():
            if count == 0:
                print(f"{attrs.class_information}:1: W001: in class {class_name} variable {attr} was never read")

def main():
    if len(sys.argv) < 2:
        print("""usage: tracer.py script
    
    Collect unused attributes
    
    positional arguments:
      script      Script to test
    """)
        sys.exit(1)

    script = sys.argv[1]
    sys.argv = sys.argv[1:]

    filename = os.path.abspath(script)
    script_dir = os.path.dirname(filename)
    sys.path.insert(0, script_dir)
    script_name = os.path.splitext(os.path.basename(filename))[0]

    # Set the tracer function
    sys.settrace(reads_tracer)

    importlib.import_module(script_name)

if __name__ == "__main__":
    main()
