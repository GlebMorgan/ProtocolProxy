


class Par:
    def __init__(self, name, reqType):
        self.name = name
        self.value = reqType()
        self.inSync = False

    def __get__(self, instance, owner):
        print(f"Inside __get__: instance: {instance}, owner = {owner}")
        return self.value

    def __set__(self, instance, value):
        print(f"Inside __set__: instance: {instance}")
        self.value = value
        self.inSync = False
        instance.notify('altered', self.name, value)


class T():
    POWER = Par('POWER', bool)
    NUMBER = Par('NUMBER', int)

    def notify(self, tag, name, value):
        print(f"Called 'notify' on {name}={value}")

    @classmethod
    def test(cls):
        for item in dir(cls.__init__.__code__):
            if item.startswith('co'):
                print(f"{item}: {getattr(cls.__init__.__code__, item)}")


if __name__ == '__main__':
    t = T()
    t.NUMBER = 8
    print(f"==:{t.NUMBER == T.NUMBER}")
    print(T.POWER)
    T.POWER = True
