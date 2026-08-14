from __future__ import annotations


DIRECTOR_TEST_TEAMS = {
    376957179: ("Максима", 0),
    772920814: ("Ксении", 5),
    661269678: ("Анны", 10),
    140961733: ("Татьяны", 15),
    541848217: ("Иллидана", 20),
}

DIRECTOR_DISPLAY_NAMES = {
    376957179: "Максим",
    772920814: "Ксения",
    661269678: "Анна",
    140961733: "Татьяна",
    541848217: "Иллидан Ярость Бури",
}


def is_director_dashboard_demo_user(telegram_id: int | None) -> bool:
    return telegram_id in DIRECTOR_TEST_TEAMS
