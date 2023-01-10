from unused_attrs import decorate_all_classes

from sys import settrace


__previous_hooks = set()
# local trace function which returns itself
def my_tracer(frame, event, arg=None):
    frame.f_trace_lines = False
    # extracts frame code
    code = frame.f_code
    # extracts calling function name
    func_name = code.co_name
    if event != 'return' and not (event=='call' and func_name=='__getattribute__'):
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
    decorate_all_classes(frame.f_globals)
    #if frame.f_back:
    #    print(f" {frame.f_back.f_locals}")
    #    decorate_all_classes(frame.f_back.f_locals)

    return my_tracer


# returns reference to local
# trace function (my_tracer)
settrace(my_tracer)


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

