"""
配置管理模块
管理 Codecks 连接器的配置
"""

import os
import json
from typing import Optional
from dataclasses import dataclass, asdict
from astrbot.api import logger


@dataclass
class CodecksConfig:
    """Codecks 配置"""
    token: str = ""  # API Token
    subdomain: str = ""  # 组织子域名
    user_id: Optional[int] = None  # 用户 ID（用于创建/更新操作）
    
    def is_valid(self) -> bool:
        """检查配置是否有效"""
        return bool(self.token and self.subdomain)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "CodecksConfig":
        return cls(
            token=data.get("token", ""),
            subdomain=data.get("subdomain", ""),
            user_id=data.get("user_id")
        )


class ConfigManager:
    """配置管理器"""
    
    DEFAULT_CONFIG = CodecksConfig()
    
    def __init__(self, plugin_data_dir: str):
        """
        初始化配置管理器
        
        Args:
            plugin_data_dir: 插件数据目录路径
        """
        self.plugin_data_dir = plugin_data_dir
        self.config_file = os.path.join(plugin_data_dir, "config.json")
        self._config: Optional[CodecksConfig] = None
        
        # 确保数据目录存在
        os.makedirs(plugin_data_dir, exist_ok=True)
    
    def load(self) -> CodecksConfig:
        """加载配置"""
        if self._config is not None:
            return self._config
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = CodecksConfig.from_dict(data)
                logger.info("[Codecks] 配置加载成功")
            except Exception as e:
                logger.error(f"[Codecks] 加载配置失败: {e}")
                self._config = CodecksConfig()
        else:
            self._config = CodecksConfig()
            self.save()
        
        return self._config
    
    def save(self, config: Optional[CodecksConfig] = None):
        """保存配置"""
        if config:
            self._config = config
        
        if self._config is None:
            return
        
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self._config.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info("[Codecks] 配置保存成功")
        except Exception as e:
            logger.error(f"[Codecks] 保存配置失败: {e}")
    
    def get_config(self) -> CodecksConfig:
        """获取当前配置"""
        if self._config is None:
            return self.load()
        return self._config
    
    def update(self, **kwargs):
        """更新配置字段"""
        config = self.get_config()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self.save()
