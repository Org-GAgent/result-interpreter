"""
Skills Loader - 加载和管理分析技能

参考OpenRouter的skills-loader设计，但使用我们自己的LLM API
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """单个Skill的定义"""
    name: str
    description: str
    content: str  # SKILL.md的完整内容
    directory: str  # Skill所在目录
    has_config: bool = False


class SkillsLoader:
    """Skills加载器 - 管理和加载预定义的分析技能"""

    def __init__(self, skills_dir: Optional[str] = None):
        """
        初始化Skills Loader

        Args:
            skills_dir: skills目录路径，默认为项目根目录的skills/
        """
        if skills_dir is None:
            # 默认使用项目根目录下的skills文件夹
            project_root = Path(__file__).parent.parent.parent.parent
            self.skills_dir = project_root / "skills"
        else:
            self.skills_dir = Path(skills_dir)

        self._loaded_skills: Set[str] = set()  # 已加载的skills（防止重复）
        self._available_skills: Dict[str, Skill] = {}  # 可用的skills缓存

        logger.info(f"SkillsLoader initialized with directory: {self.skills_dir}")

        # 初始化时扫描可用skills
        self._scan_skills()

    def _scan_skills(self) -> None:
        """扫描skills目录，发现所有可用的skills"""
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return

        for item in self.skills_dir.iterdir():
            if not item.is_dir():
                continue

            skill_file = item / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                # 读取skill内容
                content = skill_file.read_text(encoding='utf-8')

                # 提取描述（第一个非标题段落）
                description = self._extract_description(content)

                # 检查是否有config文件
                config_file = item / "config.json"
                has_config = config_file.exists()

                # 创建Skill对象
                skill = Skill(
                    name=item.name,
                    description=description,
                    content=content,
                    directory=str(item),
                    has_config=has_config
                )

                self._available_skills[item.name] = skill
                logger.info(f"Discovered skill: {item.name}")

            except Exception as e:
                logger.warning(f"Failed to load skill {item.name}: {e}")

        logger.info(f"Total skills available: {len(self._available_skills)}")

    def _extract_description(self, content: str) -> str:
        """从SKILL.md内容中提取描述（第一个非标题段落）"""
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                return line[:200]  # 最多200字符
        return "No description available"

    def list_skills(self, category: Optional[str] = None) -> List[Dict[str, any]]:
        """
        列出所有可用的skills

        Args:
            category: 可选的分类过滤（暂未实现）

        Returns:
            skills信息列表
        """
        skills_info = []
        for skill_name, skill in self._available_skills.items():
            skills_info.append({
                "name": skill_name,
                "description": skill.description,
                "has_config": skill.has_config,
                "loaded": skill_name in self._loaded_skills
            })
        return skills_info

    def is_skill_loaded(self, skill_name: str) -> bool:
        """检查skill是否已加载（防止重复）"""
        return skill_name in self._loaded_skills

    def load_skill(self, skill_name: str) -> Optional[str]:
        """
        加载单个skill，返回要注入到上下文的内容

        Args:
            skill_name: skill名称

        Returns:
            skill内容（带标记），如果已加载或不存在则返回None
        """
        # 检查是否已加载
        if skill_name in self._loaded_skills:
            logger.info(f"Skill {skill_name} already loaded, skipping")
            return None

        # 检查skill是否存在
        if skill_name not in self._available_skills:
            available = ', '.join(self._available_skills.keys())
            logger.warning(f"Skill {skill_name} not found. Available: {available}")
            return None

        # 加载skill
        skill = self._available_skills[skill_name]
        self._loaded_skills.add(skill_name)

        # 构建注入内容（带标记）
        skill_marker = f"[Skill: {skill_name}]"
        injected_content = f"""{skill_marker}
Base directory: {skill.directory}

{skill.content}
"""

        logger.info(f"Loaded skill: {skill_name}")
        return injected_content

    def load_multiple_skills(self, skill_names: List[str]) -> str:
        """
        加载多个skills

        Args:
            skill_names: skill名称列表

        Returns:
            所有skills的组合内容
        """
        loaded_contents = []
        loaded_names = []
        failed_names = []

        for skill_name in skill_names:
            content = self.load_skill(skill_name)
            if content:
                loaded_contents.append(content)
                loaded_names.append(skill_name)
            else:
                if skill_name not in self._available_skills:
                    failed_names.append(skill_name)

        logger.info(f"Loaded {len(loaded_names)} skills: {loaded_names}")
        if failed_names:
            logger.warning(f"Failed to load skills: {failed_names}")

        return "\n\n---\n\n".join(loaded_contents)

    def get_skill_content(self, skill_name: str) -> Optional[str]:
        """获取skill的完整内容（不标记为已加载）"""
        if skill_name not in self._available_skills:
            return None
        return self._available_skills[skill_name].content

    def reset_loaded_skills(self) -> None:
        """重置已加载skills列表"""
        self._loaded_skills.clear()
        logger.info("Reset loaded skills")

    def get_skills_summary_for_llm(self) -> str:
        """
        生成给LLM看的skills摘要（用于决策）

        Returns:
            格式化的skills列表字符串
        """
        if not self._available_skills:
            return "No skills available"

        summary_lines = ["Available skills:"]
        for skill_name, skill in self._available_skills.items():
            summary_lines.append(f"- {skill_name}: {skill.description}")

        return "\n".join(summary_lines)


# 全局单例（可选）
_global_skills_loader: Optional[SkillsLoader] = None


def get_skills_loader(skills_dir: Optional[str] = None) -> SkillsLoader:
    """获取全局SkillsLoader实例"""
    global _global_skills_loader
    if _global_skills_loader is None:
        _global_skills_loader = SkillsLoader(skills_dir=skills_dir)
    return _global_skills_loader
