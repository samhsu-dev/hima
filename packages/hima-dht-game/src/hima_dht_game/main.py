"""Game entry: argument parsing and one game launch."""
import argparse
import logging
import os
from datetime import datetime

from sc2 import maps
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

from hima_dht_game.bots.protoss_bot import Protoss_Bot
from hima_dht_game.bots.swarmbrain import SwarmBrain
from hima_dht_game.bots.terran_bot import Terran_Bot
from hima_dht_game.bots.textstarcraft import TextStarCraft
from hima_dht_game.bots.zerg_bot import Zerg_Bot

# Shared with the hima CLI process, whose environment this process
# inherits; the contract is documented in .env.example.
ENV_LOG_LEVEL = "HIMA_LOG_LEVEL"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=os.environ.get(ENV_LOG_LEVEL, "INFO"), format=LOG_FORMAT)
    parser = argparse.ArgumentParser(description='StarCraft II agent')
    parser.add_argument('--port', default=8080, type=int)
    parser.add_argument('--num_server', default=3, type=int)
    parser.add_argument('--advisor_host', default='localhost')
    parser.add_argument('--save_path', default='tmp')
    parser.add_argument('--temperature', default=0.7)
    parser.add_argument('--LLM_api_text', default='gpt-4o-mini')
    parser.add_argument('--LLM_api_key', default="YOUR_API_KEY")
    parser.add_argument('--LLM_base_url', default=None)
    parser.add_argument('--realtime', action='store_true', default=False)

    parser.add_argument(
        '--own_race', default='Terran',
        choices=['Protoss', 'Zerg', 'Terran']
    )
    parser.add_argument('--mode', default='bot', choices=['bot', 'agent'])

    # if mode is bot
    parser.add_argument('--seed', type=int, default=3)
    parser.add_argument(
        '--enemy_race', default='Terran',
        choices=['Protoss', 'Zerg', 'Terran']
    )
    parser.add_argument(
        '--difficulty', default='Hard',
        choices=[
            'VeryEasy', 'Easy', 'Medium', 'MediumHard', 'Hard', 'Harder',
            'VeryHard', 'CheatVision', 'CheatMoney', 'CheatInsane'
        ]
    )

    # if mode is agent
    parser.add_argument(
        '--enemy_agent',
        default='HEP-TextStarCraft',
        choices=['TextStarCraft', 'SwarmBrain', 'HEP-TextStarCraft']
    )

    args = parser.parse_args()
    args.own_race = Race[args.own_race]
    args.enemy_race = Race[args.enemy_race]
    args.difficulty = Difficulty[args.difficulty]
    args.current_time = datetime.now().strftime('%Y%m%d_%H%M%S')

    temp_replay_folder = args.save_path
    os.makedirs(temp_replay_folder, exist_ok=True)
    temp_replay_path = f'{temp_replay_folder}/{args.current_time}_{args.difficulty}_{args.enemy_race}_temp.SC2Replay'
    if args.own_race == Race.Protoss:
        our_bot = Protoss_Bot(args)
    elif args.own_race == Race.Zerg:
        our_bot = Zerg_Bot(args)
    elif args.own_race == Race.Terran:
        our_bot = Terran_Bot(args)
    logger.info(
        "game launching: mode=%s own_race=%s enemy_race=%s difficulty=%s seed=%d realtime=%s",
        args.mode, args.own_race.name, args.enemy_race.name, args.difficulty.name,
        args.seed, args.realtime,
    )
    if args.mode == 'bot':
        enemy = Computer(args.enemy_race, args.difficulty)
        result = run_game(maps.get("Ancient Cistern LE"), [Bot(args.own_race, our_bot), enemy], realtime=args.realtime, save_replay_as=temp_replay_path, random_seed=args.seed)
        result = str(result).split(".")[1]
        final_replay_path = f'{temp_replay_folder}/{args.current_time}_{args.difficulty}_{args.enemy_race}_{result}.SC2Replay'
        os.rename(temp_replay_path, final_replay_path)
        logger.info("replay saved: result=%s replay=%s", result, final_replay_path)
    elif args.mode == 'agent':
        if args.enemy_agent == 'TextStarCraft':
            enemy = Bot(Race.Protoss, TextStarCraft(args))
        elif args.enemy_agent == 'SwarmBrain':
            enemy = Bot(Race.Zerg, SwarmBrain(args))
        elif args.enemy_agent == 'HEP-TextStarCraft':
            enemy = Bot(Race.Protoss, TextStarCraft(args, hep=True))
        run_game(maps.get("Ancient Cistern LE"), [Bot(args.own_race, our_bot), enemy], realtime=args.realtime, save_replay_as=temp_replay_path, random_seed=args.seed)
        logger.info("replay saved: replay=%s", temp_replay_path)
