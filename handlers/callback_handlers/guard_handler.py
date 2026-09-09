"""Compatibility entry point for existing verification buttons."""
from services.moderation.verification import callback


async def guard_callback_handler(update, context, cmd):
    await callback(update, context, cmd)
