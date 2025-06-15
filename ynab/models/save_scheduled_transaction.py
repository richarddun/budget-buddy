class SaveScheduledTransaction:
    def __init__(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self, k, v)
    def to_dict(self):
        return self.__dict__
