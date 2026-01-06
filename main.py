import json
import StrategyRegister
import yaml

from Log import log
from TradingPipeline import TradingPipeline
from TradingTrigger import TradingTrigger

pipeline = TradingPipeline()

if __name__ == '__main__':

    with open('./config.yaml', 'r', encoding='utf-8') as file:
        config = yaml.safe_load(file)

    target = config['targets']

    total_holding_weight = 0
    for target in config['targets']:
        total_holding_weight += target['holding_weight']

    env = {
        'total_holding_weight': total_holding_weight
    }

    for target in config['targets']:
        target_name = target['name']
        holding_weight = target['holding_weight'] / total_holding_weight
        strategies = target['strategies']
        for strategy in strategies:
            strategy_name = strategy['name']
            strategy_param = strategy['params']
            trigger = (TradingTrigger.create(env)
                       .on(target)
                       .when(strategy)
                       )
            pipeline.add(trigger)

    env = {
        "vix": 30
    }
    pipeline.execute(env)
    # dispatcher = StrategyRegister

    # dispatcher
    #     .register(target)\
    #     .when(strategy)\
    #     .trade()

    # registry = StrategyDispatcher.FunctionRegistry()
    # print(registry.call("test"))  # test
    # print(registry("test"))  # test
    #
    # print(registry("greeting", "test"))
    # print(registry("minus", 1, 2))
