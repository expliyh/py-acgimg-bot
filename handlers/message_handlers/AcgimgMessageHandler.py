from typing import Optional, Callable, Awaitable, Any, Union

from telegram import Update
from telegram.ext import filters as filters_module, MessageHandler, ContextTypes


class AcgimgMessageHandler:
    """Acgimg message handler."""
    def __init__(
        self,
        filters: Optional[filters_module.BaseFilter],
        callback: Callable[[Update, Any], Awaitable[object]],
        no_parallel: bool = True,
        block: bool = False,
    ):
        self.filters = filters
        self.callback = callback
        self.block = block
        self.no_parallel = no_parallel

    def check_update(self, update: object) -> Optional[Union[bool, dict[str, list[Any]]]]:
        """Determines whether an update should be passed to this handler's :attr:`callback`.

        Args:
            update (:class:`telegram.Update` | :obj:`object`): Incoming update.

        Returns:
            :obj:`bool`

        """
        if isinstance(update, Update):
            return self.filters.check_update(update) or False
        return None

    async def handle_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Passes an update to this handler's :attr:`callback`.

        Args:
            update (:class:`telegram.Update`): Incoming update.
            context (:class:`telegram.ext.CallbackContext`): The current context.

        """
        await self.callback(update, context)
