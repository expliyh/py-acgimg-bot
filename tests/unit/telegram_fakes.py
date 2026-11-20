"""Lightweight stand-ins for Telegram objects used by handler unit tests.

The fakes only expose attributes the handlers read. They never open a socket
or require a bot token.
"""

from __future__ import annotations

from unittest.mock import AsyncMock


class Bag:
    """Attribute bag. Unset Telegram fields read as None."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getattr__(self, name):
        return None


def sent_texts(mock) -> list:
    texts = []
    for call in mock.await_args_list:
        if call.args:
            texts.append(call.args[0])
        else:
            texts.append(call.kwargs.get("text"))
    return texts


def make_bot(**overrides):
    bot = Bag(
        id=900,
        edit_message_reply_markup=AsyncMock(),
        edit_message_text=AsyncMock(),
        send_message=AsyncMock(return_value=Bag(message_id=501, id=501)),
        delete_message=AsyncMock(),
        send_document=AsyncMock(return_value=Bag(id=77, document=Bag(file_id="doc-file"))),
        send_photo=AsyncMock(return_value=Bag(id=78)),
        get_chat_member=AsyncMock(),
        get_chat=AsyncMock(),
        get_me=AsyncMock(),
        set_webhook=AsyncMock(),
        delete_webhook=AsyncMock(),
        get_my_commands=AsyncMock(return_value=[]),
        delete_my_commands=AsyncMock(),
        set_my_commands=AsyncMock(),
        shutdown=AsyncMock(),
    )
    for key, value in overrides.items():
        setattr(bot, key, value)
    return bot


def make_context(args=None, chat_data=None, bot=None):
    return Bag(
        args=list(args or []),
        bot=bot or make_bot(),
        chat_data={} if chat_data is None else chat_data,
        user_data={},
    )


def make_user(user_id=1, **kwargs):
    data = dict(
        id=user_id,
        username="tester",
        full_name="Tester",
        first_name="Tester",
        last_name=None,
        is_bot=False,
    )
    data.update(kwargs)
    return Bag(**data)


def make_chat(chat_id=10, chat_type="private", title="测试群"):
    return Bag(id=chat_id, type=chat_type, title=title)


def make_message(
    *,
    text="hello",
    chat_id=10,
    chat_type="private",
    message_id=20,
    user_id=1,
    chat=None,
    from_user=None,
    **extra,
):
    chat = chat or make_chat(chat_id, chat_type)
    from_user = from_user or make_user(user_id)
    message = Bag(
        text=text,
        chat=chat,
        chat_id=chat.id,
        message_id=message_id,
        id=message_id,
        from_user=from_user,
        reply_text=AsyncMock(),
        edit_text=AsyncMock(),
        reply_to_message=None,
        sender_chat=None,
        entities=None,
        photo=None,
        document=None,
        caption=None,
        date=None,
        edit_date=None,
        media_group_id=None,
        reply_markup=None,
    )
    for key, value in extra.items():
        setattr(message, key, value)
    return message


def make_update(
    *,
    text="hello",
    chat_id=10,
    chat_type="private",
    user_id=1,
    message_id=20,
    query_data=None,
    message=None,
    user=None,
    chat=None,
    update_id=7,
    **message_extra,
):
    user = user or make_user(user_id)
    chat = chat or make_chat(chat_id, chat_type)
    message = message or make_message(
        text=text,
        chat=chat,
        message_id=message_id,
        from_user=user,
        **message_extra,
    )
    query = None
    if query_data is not None:
        query = Bag(
            data=query_data,
            answer=AsyncMock(),
            message=message,
            from_user=user,
            edit_message_text=AsyncMock(),
        )
    return Bag(
        update_id=update_id,
        effective_user=user,
        effective_chat=chat,
        effective_message=message,
        message=message,
        callback_query=query,
    )
