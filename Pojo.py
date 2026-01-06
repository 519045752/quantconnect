from dataclasses import dataclass, fields, field, asdict
from typing import Generator, Any, Callable, Dict, Optional


@dataclass
class Env:
    total_holding_weight: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> 'Env':
        valid_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class Target:
    name: str = ""
    holding_percentage: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> 'Target':
        valid_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class Strategy:
    name: str = ""
    priority: int = -1
    params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> 'Strategy':
        valid_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)
