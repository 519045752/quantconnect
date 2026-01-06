import json
import threading
from typing import Generator, Any, Callable, Dict, Optional, List

from Log import log, Log
from StrategyRegister import StrategyRegister
from TradingTrigger import TradingTrigger


class TradingPipeline:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not TradingPipeline._initialized:
            self.pipeline: Dict[str, List[TradingTrigger]] = {}
            TradingPipeline._initialized = True

    def add(self, trigger: TradingTrigger):
        target_name = trigger.target.name
        if target_name not in self.pipeline:
            self.pipeline[target_name] = []
        # 检查是否已存在相同策略的触发器
        # existing_strategies = [t.strategy.name for t in self.pipeline[target_name] if t.strategy]
        # if trigger.strategy and trigger.strategy.name in existing_strategies:
        #     pass
        self.pipeline[target_name].append(trigger)
        #TODO 按照标的的priority排序
        self.pipeline[target_name] = sorted(self.pipeline[target_name], key=lambda x: x.strategy.priority)
        #

        return self

    def log(self):
        for target_name in self.pipeline:
            log.error(target_name)
            for trigger in self.pipeline[target_name]:
                log.debug(trigger)
        return self

    def sort(self):
        for target_name in self.pipeline:
            self.pipeline[target_name] = sorted(self.pipeline[target_name], key=lambda x: x.strategy.priority)
        return self

    def execute(self, env: Dict):
        # FIXME 线程堵塞情况下, 单例导致env相互覆盖
        register = StrategyRegister(env)
        for target_name in self.pipeline:
            for trigger in self.pipeline[target_name]:
                register.call("inspect", trigger)

        return self