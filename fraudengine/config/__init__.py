"""Configuration management for fraudengine."""
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


class Config:
    """Load and manage YAML configuration files."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(__file__).parent.parent.parent / "configs"
        self._cache: Dict[str, Dict[str, Any]] = {}

    def load(self, name: str) -> Dict[str, Any]:
        """Load a YAML config file by name (without .yaml extension)."""
        if name not in self._cache:
            path = self.config_dir / f"{name}.yaml"
            if path.exists():
                with open(path, "r") as f:
                    self._cache[name] = yaml.safe_load(f) or {}
            else:
                # Fall back to model_config.yaml which contains merged configs
                model_cfg_path = self.config_dir / "model_config.yaml"
                if model_cfg_path.exists():
                    with open(model_cfg_path, "r") as f:
                        all_cfg = yaml.safe_load(f) or {}
                    # If name is a top-level section (e.g. redis, kafka, features)
                    clean_name = name.replace("_config", "")
                    if clean_name in all_cfg:
                        self._cache[name] = {clean_name: all_cfg[clean_name]}
                    elif name in all_cfg:
                        self._cache[name] = {name: all_cfg[name]}
                    else:
                        self._cache[name] = all_cfg
                else:
                    raise FileNotFoundError(f"Config file not found: {path}")
        return self._cache[name]

    def get(self, name: str, key: str, default: Any = None) -> Any:
        """Get a specific key from a config file."""
        config = self.load(name)
        return config.get(key, default)


# Global config instance
config = Config()