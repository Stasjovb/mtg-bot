from mtg_bot.bot import Bot


def test_bot_has_name():
    assert Bot(name="mtg-bot").name == "mtg-bot"
