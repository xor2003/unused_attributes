import atexit, os, inspect
from sys import settrace
from typing import Optional, Any, Callable


# Define the tracer function
def my_tracer(frame: Any, event: str, arg: Optional[Any] = None) -> Callable:
    """Trace each class's __init__() method to track attributes reads"""
    # Disable tracing lines inside the frame
    frame.f_trace_lines = False

    if event != 'return':
        return my_tracer

    # Extract the frame's code object
    code = frame.f_code

    # Extract the calling function name
    func_name = code.co_name

    if func_name != '__init__':
        return my_tracer

    # Create a global set of previous hooks if it doesn't exist
    global __previous_hooks

    if "__previous_hooks" not in globals():
        __previous_hooks = set()
        atexit.register(print_report)

    # Extract the line number
    line_no = frame.f_lineno

    # Skip if the code+line combination is already in the set
    if f"{code}{line_no}" in __previous_hooks:
        return my_tracer

    # Add the code+line combination to the set
    __previous_hooks.add(f"{code}{line_no}")

    # Call the 'init' function with the local variables
    record_class_init_attrbiutes(frame.f_locals['self'])

    return my_tracer


def record_class_init_attrbiutes(self):
    """Enumerate class attributes and set hook to reading attributes"""
    # print(dir(self))

    the_class = type(self)
    if hasattr(the_class, "__already_decorated"):
        return

    orig_getattr = the_class.__getattribute__
    # print(f"self.__getattribute__ {self.__getattribute__}")
    global __reads_count
    if "__reads_count" not in globals():
        global __reads_count
        __reads_count = {}
    #class_name = the_class.__name__
    #filepath = os.path.abspath(inspect.getfile(the_class))
    #print(f"In __init__ file: {filepath}")
    index = the_class  #filepath + '.' + class_name

    if index not in __reads_count:
        __reads_count[index] = {}

    def __getattribute__(self, attr_name):
        """Record attrbibute was read"""
        global __reads_count
        the_class = type(self)
        #class_name = the_class.__name__

        #filepath = os.path.abspath(inspect.getfile(type(self)))
        index = the_class  # filepath + '.' + class_name
        if attr_name not in __reads_count[index]:
            __reads_count[index][attr_name] = 0
        __reads_count[index][attr_name] += 1
        return orig_getattr(self, attr_name)


    # Initialize counter for each attribute
    for attr_name in dir(self):
        try:
            if not attr_name.endswith('__') and not callable(getattr(self, attr_name)):
                # print(f"Added {type(self).__name__} {attr_name}")
                __reads_count[index][attr_name] = 0
        except Exception:
            pass
    the_class.__getattribute__ = __getattribute__
    the_class.__already_decorated = True


def print_report():
    if "__reads_count" not in globals():
        print("No data collected")
        return
    for the_class, attrs in __reads_count.items():
        try:
            filepath = os.path.abspath(inspect.getfile(the_class))
        except Exception:
            filepath = ""
        class_name = the_class.__name__
        for attr, count in attrs.items():
            if count == 0:
                print(f"{filepath}:1:1: W001: in class {class_name} variable {attr} was never read")


# Set the tracer function
settrace(my_tracer)
