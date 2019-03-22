import threading


class PAR:
    """ Tag-indicator to use in type annotations
        Denotes that class attribute is protocol parameter variable
    """


class ProxyProtocolMetaclass(type):
    """ Create class attr 'altered' signifying whether any class attributes
            (except for those starting with '_') were changed
            since last time 'cls.altered' was checked (accessed)
        Access to class attrs is synchronous
    """

    def __init__(cls, name, bases, dct):
        super().__setattr__('altered', False)
        super().__setattr__('lock', threading.RLock())
        super().__init__(name, bases, dct)


    def __call__(cls, *args):
        raise SyntaxError("Class is not intended to be instantiated.")


    def __getattribute__(cls, name):
        with super().__getattribute__('lock'):
            if (name == 'altered'):
                altered = super().__getattribute__(name)
                super().__setattr__('altered', False)
                return altered
            return super().__getattribute__(name)


    def __setattr__(cls, name, val):
        with super().__getattribute__('lock'):
            if (cls.__annotations__.get(name, None) == PAR):
                super().__setattr__('altered', True)
            return super().__setattr__(name, val)


    def __str__(cls):
        return ', '.join(f'{attr} = {cls.__dict__[attr]}' for attr in cls.__dict__
                         if (not attr.startswith('__') and attr != 'altered'))

