class UserBlockedError(Exception):
    """
    This class is a custom exception that is raised when a user is blocked.

    Attributes:
        message (str): The error message to be displayed when the exception is raised.
    """

    def __init__(self, message="User is blocked"):
        """
        The constructor for the UserBlockedError class.

        Parameters:
            message (str): The error message to be displayed when the exception is raised.
                           Default is "User is blocked".
        """
        self.message = message
        super().__init__(self.message)
