import atexit

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

    init(**frame.f_locals)

    return my_tracer


def init(self):
    global __read_count
    # print(dir(self))

    if hasattr(type(self), "__already_decorated"):
        return

    orig_getattr = type(self).__getattribute__
    # print(f"self.__getattribute__ {self.__getattribute__}")
    if "__read_count" not in globals():
        global __read_count
        __read_count = dict()
    if type(self).__name__ not in __read_count:
        __read_count[type(self).__name__] = dict()

    def __getattribute__(self, attr_name):
        global __read_count
        if attr_name in __read_count[type(self).__name__]:
            __read_count[type(self).__name__][attr_name] += 1
        return orig_getattr(self, attr_name)

    type(self).__getattribute__ = __getattribute__

    for attr_name in dir(self):
        if not attr_name.endswith('__') and not callable(getattr(self, attr_name)):
            # print(f"Added {type(self).__name__} {attr_name}")
            __read_count[type(self).__name__][attr_name] = 0
    type(self).__already_decorated = True


def start_tracking():
    settrace(my_tracer)


def print_report():
    if "__read_count" in globals():
        for class_name, attrs in __read_count.items():
            for attr, count in attrs.items():
                if count == 0:
                    print(f"warning: in class {class_name} variable {attr} is never read")


start_tracking()
