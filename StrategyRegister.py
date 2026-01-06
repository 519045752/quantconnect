import threading
from typing import Callable, Any, Dict

from Log import log
from TradingTrigger import TradingTrigger


class StrategyRegister:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, env):
        if not StrategyRegister._initialized:
            self.env = env
            self._functions: Dict[str, Callable] = {}
            self._setup_default_functions()
            StrategyRegister._initialized = True

    def register(self, name: str = None):
        def decorator(func):
            func_name = name or func.__name__
            self._functions[func_name] = func
            return func

        return decorator

    def register_function(self, name: str, func: Callable):
        self._functions[name] = func

    def call(self, name: str, *args, **kwargs) -> Any:
        if name not in self._functions:
            raise KeyError(f"Function '{name}' not found")
        return self._functions[name](*args, **kwargs)

    def __call__(self, name: str, *args, **kwargs):
        return self.call(name, *args, **kwargs)

    def _setup_default_functions(self):
        self.register_function("test", lambda: "test")
        self.register_function("add", lambda a, b: a + b)

        @self.register()
        def inspect(trigger: TradingTrigger):
            log.warning(self.env['vix'])
            trigger.log()

        @self.register("minus")
        def add(a: float, b: float) -> float:
            return a - b
