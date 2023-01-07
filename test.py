from unused_attrs import decorate_all_classes


class C:
    def __init__(self):
        self.a = 0
        self.b = 1


decorate_all_classes(vars())

c = C()
c.a = 2
c.b = 3
print(c.a)

