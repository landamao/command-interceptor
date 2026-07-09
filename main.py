import sys
from pypinyin import lazy_pinyin
from astrbot.api.all import (
    Star, Context, Plain, Reply, Node, Nodes,
    AstrBotConfig, AstrMessageEvent, logger
)
from astrbot.api.event import filter
from astrbot.core.star.star_handler import star_handlers_registry
from astrbot.core.star.filter.command_group import CommandFilter

class 指令拦截(Star):

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.名字:str = config['名字']
        self.禁用指令唤醒:bool = config['禁用指令唤醒']
        self.禁用前缀唤醒:bool = config['禁用前缀唤醒']
        self.唤醒前缀:tuple[str] = tuple(context.get_config()["wake_prefix"])
        self.所有指令:list[str] = self.获取所有指令(config['额外指令'])
        self.所有指令集合:set[str] = set(self.所有指令)
        config['额外指令'] = self.指令列表处理(config['额外指令'])
        config.save_config()

    @filter.on_astrbot_loaded(priority=-sys.maxsize)
    async def 启动完成获取所有指令(self):
        """框架初次启动完成时获取所有指令，不冲突"""
        self.所有指令 = self.获取所有指令(self.config['额外指令'])
        self.所有指令集合 = set(self.所有指令)

    @filter.on_llm_request(priority=sys.maxsize)
    async def llm请求前(self, event: AstrMessageEvent, _):
        """在llm请求前拦截指令消息"""
        if self.禁用指令唤醒 and (l:=event.get_message_str().strip().split()) and l[0] in self.所有指令集合:
            event.stop_event()
            logger.info(f"[指令拦截] （指令拦截）拦截了消息 |{event.get_message_outline()} | 唤醒llm")
            return
        if self.禁用前缀唤醒 and next((seg.text for seg in event.get_messages() if isinstance(seg, Plain)), '').strip().startswith(self.唤醒前缀):
            event.stop_event()
            logger.info(f"[指令拦截] （前缀拦截）拦截了消息 |{event.get_message_outline()} | 唤醒llm")
            return

    @filter.command("所有指令")
    async def 所有指令(self, event: AstrMessageEvent):
        """合并转发所有指令，避免刷屏"""
        event.stop_event()
        await event.send(event.chain_result([Nodes([Node(uin=event.get_self_id(), name=self.名字, content=[Plain(文本)]) for 文本 in [f"所有{len(self.所有指令)}个指令", '/' + '\n/'.join(self.所有指令)]])]))

    @filter.command("验证指令")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 验证指令(self, event: AstrMessageEvent, 指令: str):
        """验证指令是否在所有指令中，支持逗号分隔多个指令"""
        event.stop_event()
        指令列表 = self.指令列表处理(指令.replace('，', ',').split(','))
        await self.发送回复文本(event, '\n'.join([ f"✅ 「{指令}」在所有指令中" if 指令 in self.所有指令集合 else f"❌ 「{指令}」不在所有指令中" for 指令 in 指令列表])) if 指令列表 else await self.发送回复文本(event, "❌ 请输入有效指令")

    @filter.command("刷新指令")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 刷新指令(self, event: AstrMessageEvent):
        """刷新指令"""
        旧指令集合 = self.所有指令集合.copy()
        self.所有指令 = self.获取所有指令(self.config['额外指令'])
        self.所有指令集合 = set(self.所有指令)
        新增 = self.所有指令集合 - 旧指令集合
        删除 = 旧指令集合 - self.所有指令集合
        新增文本 = ', '.join(sorted(新增)) if 新增 else '无'
        删除文本 = ', '.join(sorted(删除)) if 删除 else '无'
        await self.发送回复文本(event, f"✅ 已刷新所有指令\n新增：{新增文本}\n减少：{删除文本}")

    @filter.command("添加额外指令", alias={'添加指令', '额外指令'})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 添加额外指令(self, event: AstrMessageEvent, 指令: str):
        """快速添加额外指令，用逗号分隔每个指令"""
        if not (新增指令:=self.指令列表处理(set(指令.replace('，', ',').strip().split(',')))):
            await self.发送回复文本(event, "❌ 请输入有效指令文本")
            return
        重复指令 = 新增指令 & self.所有指令集合
        if not (真正新增:=新增指令-self.所有指令集合):
            await self.发送回复文本(event, f"❌ 指令已存在：{'，'.join(重复指令)}")
            return

        self.config['额外指令'].extend(真正新增)
        self.config.save_config()

        self.所有指令 = self.获取所有指令(self.config['额外指令'])
        self.所有指令集合 = set(self.所有指令)
        await self.发送回复文本(event, f"✅ 已添加指令：{'，'.join(真正新增)}\n{'⚠️ ' + '，'.join(重复指令) + '已存在，跳过添加' if 重复指令 else ''}")

    @staticmethod
    async def 发送回复文本(event: AstrMessageEvent, 文本: str) -> None:
        """以引用回复的方式发送文本"""
        await event.send(event.chain_result([Reply(id=event.message_obj.message_id),Plain(text=文本)]))

    @staticmethod
    def 获取所有指令(额外指令:list=None) -> list:
        """遍历所有注册的处理器获取所有命令，包括别名"""
        if 额外指令 is None:
            额外指令 = []
        l指令 = []
        for handler in star_handlers_registry:
            for i in handler.event_filters:
                if isinstance(i, CommandFilter):
                    l指令.append(i.command_name)
                    if hasattr(i, 'alias') and i.alias:
                        l指令.extend(list(i.alias))
        所有指令 = set(l指令 + 额外指令)
        中文指令 = []
        英文指令 = []
        for 指令 in 所有指令:
            if 指令 and '\u4e00' <= 指令[0] <= '\u9fff':
                中文指令.append(指令)
            else:
                英文指令.append(指令)
        中文指令.sort(key=lambda x: lazy_pinyin(x))
        英文指令.sort(key=lambda x: x.lower())
        所有指令 = 中文指令 + 英文指令
        return 所有指令

    def 指令列表处理(self, 指令列表: list | set) -> list | set:
        """移除前缀并过滤空值"""
        处理后 = [ i.strip() for i in 指令列表 if i.strip()]
        处理后 = [next((指令[len(前缀):] for 前缀 in self.唤醒前缀 if 指令.startswith(前缀)), 指令) for 指令 in 处理后]
        处理后 = [ i.strip() for i in 处理后 if i.strip()]
        if isinstance(指令列表, set):
            return set(处理后)
        return 处理后