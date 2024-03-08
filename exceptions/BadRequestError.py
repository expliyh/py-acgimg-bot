class BadRequestError(Exception):
    """Exception raised for errors when processing request.

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message="Bad request error occurred"):
        self.message = message
        super().__init__(self.message)
