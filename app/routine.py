"""Rotina do robô: coleta + curadoria + postagem no Telegram, em ciclos.

Uso:
    python -m app.routine            # roda um ciclo e termina
    python -m app.routine --loop     # fica rodando a cada BOOR_BOT_INTERVAL_MIN minutos
"""
from __future__ import annotations

import random
import sys
import time

from . import bootstrap, robot
from .config import BOT_INTERVAL_MIN


def cycle() -> dict:
    bootstrap(verbose=False)
    # variação no horário, para não parecer script (comportamento humano)
    time.sleep(random.uniform(0, 20))
    result = robot.run_cycle(publish=True)
    print(f"[boorlinkcopy] ciclo: coletadas={result['collected']} "
          f"bloqueadas={result['blocked']} postadas={result['posted']} "
          f"erros={result['post_errors']}")
    return result


def main() -> None:
    if "--loop" in sys.argv:
        while True:
            try:
                cycle()
            except Exception as exc:  # noqa: BLE001
                print("[boorlinkcopy] erro no ciclo:", exc)
            time.sleep(BOT_INTERVAL_MIN * 60 + random.uniform(-60, 180))
    else:
        cycle()


if __name__ == "__main__":
    main()
