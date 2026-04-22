from mtg_bot.bot import Bot


def main() -> None:
    bot = Bot(name="mtg-bot")
    print(f"{bot.name} is ready to play Magic: The Gathering.")


if __name__ == "__main__":
    main()
