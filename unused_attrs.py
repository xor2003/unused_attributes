import atexit, os, inspect

from sys import settrace


def my_tracer(frame, event, arg=None):
    frame.f_trace_lines = False
    # extracts frame code
    code = frame.f_code
    # extracts calling function name
    func_name = code.co_name
    if not (event == 'return' and func_name == '__init__'):
        return my_tracer
    # print(event)
    # extracts the line number
    line_no = frame.f_lineno

    global __previous_hooks
    if "__previous_hooks" not in globals():
        __previous_hooks = set()
        atexit.register(print_report)
    if f"{code}{line_no}" in __previous_hooks:
        return my_tracer
    __previous_hooks.add(f"{code}{line_no}")

    init(frame.f_locals['self'])

    return my_tracer


def init(self):
    global __read_count
    # print(dir(self))

    the_class = type(self)
    if hasattr(the_class, "__already_decorated"):
        return

    orig_getattr = the_class.__getattribute__
    # print(f"self.__getattribute__ {self.__getattribute__}")
    if "__read_count" not in globals():
        global __read_count
        __read_count = {}
    class_name = the_class.__name__
    #filepath = os.path.abspath(inspect.getfile(the_class))
    #print(f"In __init__ file: {filepath}")
    index = the_class  #filepath + '.' + class_name

    if index not in __read_count:
        #print(f"Class {class_name} added")
        __read_count[index] = {}

    def __getattribute__(self, attr_name):
        global __read_count
        the_class = type(self)
        class_name = the_class.__name__

        #filepath = os.path.abspath(inspect.getfile(type(self)))
        index = the_class  # filepath + '.' + class_name

        if index not in __read_count:
            #print(f"Class {class_name} added")
            __read_count[index] = {}
        if attr_name in __read_count[index]:
            __read_count[index][attr_name] += 1
        return orig_getattr(self, attr_name)


    for attr_name in dir(self):
        with suppress(Exception):
            atr = getattr(self, attr_name)
            if not attr_name.endswith('__') and not callable(atr):
                # print(f"Added {type(self).__name__} {attr_name}")
                __read_count[index][attr_name] = 0
    the_class.__getattribute__ = __getattribute__
    the_class.__already_decorated = True


def start_tracking():
    settrace(my_tracer)


def print_report():
    if "__read_count" in globals():
        for the_class, attrs in __read_count.items():
            filepath = os.path.abspath(inspect.getfile(the_class))
            class_name = the_class.__name__
            for attr, count in attrs.items():
                if count == 0:
                    print(f"warning: in class {filepath} {class_name} variable {attr} is never read")


start_tracking()
