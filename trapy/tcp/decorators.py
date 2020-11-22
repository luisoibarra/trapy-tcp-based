from trapy.tcp.tcp_exc import ConnException


def raise_error(func):
    """
    Release resources and raise connection error in case of any error
    """
    def wrapper(self, *args, **kwargs):
        if self.errors:
            self._close_connection(0)
            raise ConnException(*self.errors)
        else:
            return func(self, *args, **kwargs)
    return wrapper