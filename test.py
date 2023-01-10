from unused_attrs import decorate_all_classes, init, getattribute, print_report
import atexit

from sys import settrace


__previous_hooks = set()
# local trace function which returns itself
def my_tracer(frame, event, arg=None):
    frame.f_trace_lines = False
    # extracts frame code
    code = frame.f_code
    # extracts calling function name
    func_name = code.co_name
    if not (event=='return' and func_name=='__init__') \
            and not (event=='call' and func_name=='__getattribute__') \
            and not (event=='call' and func_name=='__setattribute__'):
        return my_tracer
    print(event)


    # extracts the line number
    line_no = frame.f_lineno

    global __previous_hooks
    if f"{code}{line_no}" in __previous_hooks:
        return my_tracer
    __previous_hooks.add(f"{code}{line_no}")

    print(f"A {event} encountered in \
    {func_name}() at line number {line_no} {frame.f_locals}")
    if event=='return' and func_name=='__init__':
        #decorate_all_classes(frame.f_globals)
        init(**frame.f_locals)
    #elif event=='call' and func_name=='__getattribute__':
    #    print(f"get {frame.f_locals}")
    #    getattribute(**frame.f_locals)
    #elif event=='call' and func_name=='__setattribute__':
    #    print(f"set {frame.f_locals}")
    #    pass


    return my_tracer


# returns reference to local
# trace function (my_tracer)
settrace(my_tracer)
if "__read_count" not in globals():
    atexit.register(print_report)


class C:
    d=6
    def __init__(self):
        self.a = 0
        self.b = 1


#decorate_all_classes(locals())

c = C()
c.a = 2
c.b = 3
print(c.a)

