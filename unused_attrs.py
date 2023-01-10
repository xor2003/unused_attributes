import atexit


def for_all_attrs(original_class):
    if hasattr(original_class, "__already_decorated"):
        return original_class
    original_class.__already_decorated = True

    orig_init = original_class.__init__
    orig_getattr = original_class.__getattribute__
    if "__read_count" not in globals():
        global __read_count
        __read_count = dict()
    if original_class.__name__ not in __read_count:
        __read_count[original_class.__name__] = dict()

    # Make copy of original __init__, so we can call it without recursion

    def __init__(self, *args, **kws):
        orig_init(self, *args, **kws) # Call the original __init__
        global __read_count
        for attr_name in dir(self):
            if not attr_name.endswith('__') and not callable(getattr(self, attr_name)):
                __read_count[original_class.__name__][attr_name] = 0

    def __getattribute__(self, attr_name):
        global __read_count
        if attr_name in __read_count[original_class.__name__]:
            __read_count[original_class.__name__][attr_name] += 1
        return orig_getattr(self, attr_name)

    original_class.__init__ = __init__ # Set the class' __init__ to the new one
    original_class.__getattribute__ = __getattribute__
    return original_class


def decorate_all_classes(vars):
    import inspect
    if "__read_count" not in globals():
        atexit.register(print_report)
    for obj in [obj for obj in vars.values() if inspect.isclass(obj)]:
            print(obj)
            obj = for_all_attrs(obj)


def print_report():
    if "__read_count" in globals():
        for class_name, attrs in __read_count.items():
            for attr, count in attrs.items():
                if count == 0:
                    print(f"warning: in class {class_name} variable {attr} is never read")
