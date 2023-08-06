from src import unused_attrs

class C:
    d = 6

    def __init__(self):
        self.a = 0
        self.b = 1


c = C()
c.a = 2
c.b = 3
c.e = 4
print(c.a)
