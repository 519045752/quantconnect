
import json

from Log import log
from Pojo import *

class TradingTrigger:


    def __init__(self):
        self.source = None
        self.operations = None

        self.env: Optional[Env] = None
        self.target: Optional[Target] = None
        self.strategy: Optional[Strategy] = None

    def __str__(self) -> str:
        ret = f"\n对于标的: {self.target.name} (持仓上限: {self.target.holding_percentage*100}%) 执行 {self.strategy.name}" \
              f" 策略#{self.strategy.priority}" \
              f"\n策略参数:\n{json.dumps(self.strategy.params, indent=4)}"
        return ret

    def __lt__(self, other):
        return self.strategy.priority < self.strategy.priority

    def __eq__(self, other):
        raise ValueError("对于同一标的, 策略优先级不能相同")

    @classmethod
    def create(cls, env: dict):
        instance = cls()
        instance.env = Env.from_dict(env)
        return instance

    def on(self, target: dict):
        self.target = Target.from_dict(target)
        self.target.holding_percentage = target['holding_weight']/self.env.total_holding_weight
        return self

    def when(self, strategy: dict):
        self.strategy = Strategy.from_dict(strategy)
        return self

    def log(self):
        log.debug(self)
        return self

    # def store(self):
    #     pipeline.add(self)
    #     return self

    def trade(self):
        # print(f"对于标的<{self.target}>执行<{self.strategy_name}>策略")
        # print(f"默认参数: {json.dumps(self.strategy_param,  indent=4)}")
        return self






    def filter(self, condition: Callable[[Any], bool]):
        self.operations.append(('filter', condition))
        return self

    def transform(self, func: Callable[[Any], Any]):
        self.operations.append(('transform', func))
        return self

    def batch(self, size: int):
        self.operations.append(('batch', size))
        return self

    def execute(self) -> Generator:
        data = self.source

        for op_type, op_func in self.operations:
            if op_type == 'filter':
                data = (item for item in data if op_func(item))
            elif op_type == 'transform':
                data = (op_func(item) for item in data)
            elif op_type == 'batch':
                def batcher():
                    batch = []
                    for item in data:
                        batch.append(item)
                        if len(batch) >= op_func:
                            yield batch
                            batch = []
                    if batch:
                        yield batch

                data = batcher()

        return data
