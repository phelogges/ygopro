"""YGO card type definitions, enums, and constant data.

Contains NamedIntFlag enums for card types, attributes, races, link markers,
effect categories, and availability. Also includes the ARCHETYPES lookup table.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import IntEnum, IntFlag


class NamedIntFlag(IntFlag):
    """IntFlag subclass that carries a human-readable display name."""

    _text: str

    def __new__(cls, value: int, text: str):
        obj = int.__new__(cls, value)
        obj._value_ = value
        obj._text = text
        return obj

    @property
    def text(self) -> str:
        return self._text


class CardType(NamedIntFlag):
    TYPE_MONSTER = 0x1, "怪兽卡"
    TYPE_SPELL = 0x2, "魔法卡"
    TYPE_TRAP = 0x4, "陷阱卡"
    TYPE_NORMAL = 0x10, "通常怪兽"
    TYPE_EFFECT = 0x20, "效果"
    TYPE_FUSION = 0x40, "融合"
    TYPE_RITUAL = 0x80, "仪式"
    TYPE_TRAPMONSTER = 0x100, "陷阱怪兽"
    TYPE_SPIRIT = 0x200, "灵魂"
    TYPE_UNION = 0x400, "同盟"
    TYPE_DUAL = 0x800, "二重"
    TYPE_TUNER = 0x1000, "调整"
    TYPE_SYNCHRO = 0x2000, "同调"
    TYPE_TOKEN = 0x4000, "衍生物"
    TYPE_QUICKPLAY = 0x10000, "速攻"
    TYPE_CONTINUOUS = 0x20000, "永续"
    TYPE_EQUIP = 0x40000, "装备"
    TYPE_FIELD = 0x80000, "场地"
    TYPE_COUNTER = 0x100000, "反击"
    TYPE_FLIP = 0x200000, "翻转"
    TYPE_TOON = 0x400000, "卡通"
    TYPE_XYZ = 0x800000, "超量"
    TYPE_PENDULUM = 0x1000000, "灵摆"
    TYPE_SPSUMMON = 0x2000000, "特殊召唤"
    TYPE_LINK = 0x4000000, "连接"


class Attribute(NamedIntFlag):
    ATTRIBUTE_ALL = 0x7F, "全属性"
    ATTRIBUTE_EARTH = 0x01, "地"
    ATTRIBUTE_WATER = 0x02, "水"
    ATTRIBUTE_FIRE = 0x04, "炎"
    ATTRIBUTE_WIND = 0x08, "风"
    ATTRIBUTE_LIGHT = 0x10, "光"
    ATTRIBUTE_DARK = 0x20, "暗"
    ATTRIBUTE_DIVINE = 0x40, "神"


class Race(NamedIntFlag):
    RACE_ALL = 0x3FFFFFF, "全种族"
    RACE_WARRIOR = 0x1, "战士"
    RACE_SPELLCASTER = 0x2, "魔法师"
    RACE_FAIRY = 0x4, "天使"
    RACE_FIEND = 0x8, "恶魔"
    RACE_ZOMBIE = 0x10, "不死"
    RACE_MACHINE = 0x20, "机械"
    RACE_AQUA = 0x40, "水"
    RACE_PYRO = 0x80, "炎"
    RACE_ROCK = 0x100, "岩石"
    RACE_WINDBEAST = 0x200, "鸟兽"
    RACE_PLANT = 0x400, "植物"
    RACE_INSECT = 0x800, "昆虫"
    RACE_THUNDER = 0x1000, "雷"
    RACE_DRAGON = 0x2000, "龙"
    RACE_BEAST = 0x4000, "兽"
    RACE_BEASTWARRIOR = 0x8000, "兽战士"
    RACE_DINOSAUR = 0x10000, "恐龙"
    RACE_FISH = 0x20000, "鱼"
    RACE_SEASERPENT = 0x40000, "海龙"
    RACE_REPTILE = 0x80000, "爬虫类"
    RACE_PSYCHO = 0x100000, "念动力"
    RACE_DIVINE = 0x200000, "幻神兽"
    RACE_CREATORGOD = 0x400000, "创造神"
    RACE_WYRM = 0x800000, "幻龙"
    RACE_CYBERSE = 0x1000000, "电子界"
    RACE_ILLUSION = 0x2000000, "幻想魔"


class LinkMarker(NamedIntFlag):
    LINK_MARKER_BOTTOM_LEFT = 0x001, "↙"
    LINK_MARKER_BOTTOM = 0x002, "↓"
    LINK_MARKER_BOTTOM_RIGHT = 0x004, "↘"
    LINK_MARKER_LEFT = 0x008, "←"
    LINK_MARKER_RIGHT = 0x020, "→"
    LINK_MARKER_TOP_LEFT = 0x040, "↖"
    LINK_MARKER_TOP = 0x080, "↑"
    LINK_MARKER_TOP_RIGHT = 0x100, "↗"


LINK_MARKER_DISPLAY: dict[int, str] = {
    LinkMarker.LINK_MARKER_BOTTOM_LEFT: "左下",
    LinkMarker.LINK_MARKER_BOTTOM: "正下",
    LinkMarker.LINK_MARKER_BOTTOM_RIGHT: "右下",
    LinkMarker.LINK_MARKER_LEFT: "左",
    LinkMarker.LINK_MARKER_RIGHT: "右",
    LinkMarker.LINK_MARKER_TOP_LEFT: "左上",
    LinkMarker.LINK_MARKER_TOP: "正上",
    LinkMarker.LINK_MARKER_TOP_RIGHT: "右上",
}

LINK_MARKER_ORDER: tuple[int, ...] = (
    LinkMarker.LINK_MARKER_BOTTOM_LEFT,
    LinkMarker.LINK_MARKER_BOTTOM,
    LinkMarker.LINK_MARKER_BOTTOM_RIGHT,
    LinkMarker.LINK_MARKER_LEFT,
    LinkMarker.LINK_MARKER_RIGHT,
    LinkMarker.LINK_MARKER_TOP_LEFT,
    LinkMarker.LINK_MARKER_TOP,
    LinkMarker.LINK_MARKER_TOP_RIGHT,
)


class Category(NamedIntFlag):
    """Card database deck-search categories, in strings.conf 1100–1131 order.

    These are not ocgcore/effect.h's effect_category flags.
    """

    DESTROY_SPELL_TRAP = 0x1, "魔陷破坏"
    DESTROY_MONSTER = 0x2, "怪兽破坏"
    BANISH = 0x4, "卡片除外"
    SEND_TO_GRAVE = 0x8, "送去墓地"
    RETURN_TO_HAND = 0x10, "返回手卡"
    RETURN_TO_DECK = 0x20, "返回卡组"
    DESTROY_HAND = 0x40, "手卡破坏"
    DESTROY_DECK = 0x80, "卡组破坏"
    DRAW_SUPPORT = 0x100, "抽卡辅助"
    SEARCH_DECK = 0x200, "卡组检索"
    RECYCLE_CARD = 0x400, "卡片回收"
    CHANGE_POSITION = 0x800, "表示形式"
    CHANGE_CONTROL = 0x1000, "控制权"
    CHANGE_ATK_DEF = 0x2000, "攻守变化"
    PIERCING_DAMAGE = 0x4000, "穿刺伤害"
    MULTIPLE_ATTACKS = 0x8000, "多次攻击"
    ATTACK_RESTRICTION = 0x10000, "攻击限制"
    DIRECT_ATTACK = 0x20000, "直接攻击"
    SPECIAL_SUMMON = 0x40000, "特殊召唤"
    TOKEN = 0x80000, "衍生物"
    RACE_RELATED = 0x100000, "种族相关"
    ATTRIBUTE_RELATED = 0x200000, "属性相关"
    LP_DAMAGE = 0x400000, "LP伤害"
    LP_RECOVERY = 0x800000, "LP回复"
    DESTRUCTION_RESISTANCE = 0x1000000, "破坏耐性"
    EFFECT_RESISTANCE = 0x2000000, "效果耐性"
    COUNTER = 0x4000000, "指示物"
    LUCK = 0x8000000, "幸运"
    FUSION_RELATED = 0x10000000, "融合相关"
    SYNCHRO_RELATED = 0x20000000, "同调相关"
    XYZ_RELATED = 0x40000000, "超量相关"
    EFFECT_NEGATION = 0x80000000, "效果无效"


class CardAvailability(NamedIntFlag):
    OCG = 0x1, "OCG"
    TCG = 0x2, "TCG"
    CUSTOM = 0x4, "自定义"
    SC = 0x8, "简体中文"


class ArchetypeOutput(IntEnum):
    """Controls archetype name language in query output."""
    BOTH = 0
    CHINESE_ONLY = 1
    JAPANESE_ONLY = 2


UNKNOWN_ATK_DEF: int = -2
CARD_ARTWORK_VERSIONS_OFFSET: int = 20


@dataclass(frozen=True)
class Archetype:
    zh: str
    ja: str


ARCHETYPES = {
    0x1: Archetype("正义盟军",	"A・O・J"),
    0x2: Archetype("次世代",	"ジェネクス"),
    0x1002: Archetype("真次世代",	"レアル·ジェネクス"),
    #0x2002 盟军·次世代	A・ジェネクス
    0x3: Archetype("魅惑的女王",	"魅惑の女王"),
    0x4: Archetype("亚马逊",	"アマゾネス"),
    0x5: Archetype("秘仪之力",	"アルカナフォース"),
    0x6: Archetype("暗黑界",	"暗黒界"),
    0x7: Archetype("古代的机械",	"アンティーク・ギア"),
    0x8: Archetype("英雄",	"HERO"),
    0x3008: Archetype("元素英雄",	"E・HERO"),
    0x5008: Archetype("幻影英雄",	"V・HERO"),
    0x6008: Archetype("邪心英雄",	"E-HERO"),
    0xa008: Archetype("假面英雄",	"M・HERO"),
    0xc008: Archetype("命运英雄",	"D-HERO"),
    0x9: Archetype("新宇",	"ネオス"),
    0xa: Archetype("入魔",	"ヴェルズ"),
    0x100a: Archetype("侵入魔鬼",	"インヴェルズ"),
    0xb: Archetype("永火",	"インフェルニティ"),
    0xc: Archetype("外星",	"エーリアン"),
    0xd: Archetype("剑士",	"セイバー"),
    0x100d: Archetype("X-剑士",	"X－セイバー"),
    #setname 0x300d XX-剑士	XX－セイバー
    0x400d: Archetype("元素灵剑士",	"エレメントセイバー"),
    0xe: Archetype("电气",	"エレキ"),
    0xf: Archetype("扰乱",	"おジャマ"),
    0x10: Archetype("薰风",	"ガスタ"),
    0x11: Archetype("机巧",	"カラクリ"),
    0x12: Archetype("青蛙",	"ガエル"),
    0x13: Archetype("机皇",	"機皇"),
    0x3013: Archetype("机皇帝",	"機皇帝"),
    0x5013: Archetype("机皇神",	"機皇神"),
    0x6013: Archetype("机皇兵",	"機皇兵"),
    #setname 0x14 N/A
    0x15: Archetype("巨大战舰",	"巨大戦艦"),
    0x16: Archetype("机人",	"ロイド"),
    0x1016: Archetype("交通机人",	"ビークロイド"),
    0x2016: Archetype("疾行机人",	"スピードロイド"),
    0x17: Archetype("同调",	"シンクロ"),
    0x1017: Archetype("同调士",	"シンクロン"),
    0x2017: Archetype("同调龙",	"シンクロ・ドラゴン"),
    0x18: Archetype("云魔物",	"雲魔物"),
    0x19: Archetype("剑斗",	"グラディアル"),
    0x1019: Archetype("剑斗兽",	"剣闘獣"),
    0x1a: Archetype("黑蝎",	"黒蠍"),
    0x1b: Archetype("幻兽",	"幻獣"),
    0x101b: Archetype("幻兽机",	"幻獣機"),
    0x1c: Archetype("死之信息",	"死のメッセージ"),
    0x1d: Archetype("核成",	"コアキメイル"),
    0x1e: Archetype("茧状体",	"C（コクーン）"),
    0x1f: Archetype("新空间侠",	"N（ネオスペーシアン）"),
    0x20: Archetype("紫炎",	"紫炎"),
    0x21: Archetype("地缚",	"地縛"),
    0x1021: Archetype("地缚神",	"地縛神"),
    0x22: Archetype("朱罗纪",	"ジュラック"),
    0x23: Archetype("罪",	"Sin"),
    0x24: Archetype("废铁",	"スクラップ"),
    0x25: Archetype("链",	"C（チェーン）"),
    0x26: Archetype("变形斗士",	"D（ディフォーマー）"),
    0x27: Archetype("科技属",	"TG（テックジーナス）"),
    0x28: Archetype("电池人",	"電池メン"),
    0x29: Archetype("龙骑兵团",	"ドラグニティ"),
    0x2a: Archetype("自然",	"ナチュル"),
    0x2b: Archetype("忍者",	"忍者"),
    0x2c: Archetype("炎狱",	"フレムベル"),
    #setname 0x2d N/A
    0x2e: Archetype("守墓",	"墓守"),
    0x2f: Archetype("冰结界",	"氷結界"),
    0x30: Archetype("大日",	"ヴァイロン"),
    0x31: Archetype("命运女郎",	"フォーチュンレディ"),
    0x32: Archetype("火山",	"ヴォルカニック"),
    0x33: Archetype("黑羽",	"BF（ブラックフェザー）"),
    0x1033: Archetype("强袭黑羽",	"A BF（アサルト ブラックフェザー）"),
    0x34: Archetype("宝玉",	"宝玉"),
    0x1034: Archetype("宝玉兽",	"宝玉獣"),
    0x2034: Archetype("究极宝玉神",	"究極宝玉神"),
    0x5034: Archetype("高等宝玉兽",	"A宝玉獣"),
    0x35: Archetype("魔轰神",	"魔轟神"),
    0x36: Archetype("机甲",	"マシンナーズ"),
    0x37: Archetype("霞之谷",	"霞の谷"),
    0x38: Archetype("光道",	"ライトロード"),
    0x39: Archetype("熔岩",	"ラヴァル"),
    0x3a: Archetype("遗式",	"リチュア"),
    0x3b: Archetype("真红眼",	"レッドアイズ"),
    0x3c: Archetype("爬虫妖",	"レプティレス"),
    #setname 0x3d 六武
    0x103d: Archetype("六武众",	"六武衆"),
    0x203d: Archetype("六武式",	"六武式"),
    #setname 0x503d 真六武众	真六武衆
    0x903d: Archetype("影六武众",	"影六武衆"),
    0x3e: Archetype("异虫",	"ワーム"),
    0x3f: Archetype("救世",	"セイヴァー"),
    0x40: Archetype("被封印",	"封印されし"),
    0x41: Archetype("LV",	"LV（レベル）"),
    0x42: Archetype("极星",	"極星"),
    0x3042: Archetype("极星天",	"極星天"),
    0x5042: Archetype("极星宝",	"極星宝"),
    0x6042: Archetype("极星兽",	"極星獣"),
    0xa042: Archetype("极星灵",	"極星霊"),
    0x43: Archetype("废品",	"ジャンク"),
    0x44: Archetype("代行者",	"代行者"),
    0x45: Archetype("恶魔",	"デーモン"),
    0x1045: Archetype("红莲魔|恶魔",	"レッド・デーモン"),
    0x46: Archetype("融合",	"融合/フュージョン"),
    0x1046: Archetype("融合龙",	"フュージョン・ドラゴン"),
    0x47: Archetype("宝石",	"ジェム"),
    0x1047: Archetype("宝石骑士",	"ジェムナイト"),
    0x48: Archetype("No.",	"No."),
    0x1048: Archetype("混沌No.",	"CNo."),
    0x2048: Archetype("No.99",	"No.99"),
    0x49: Archetype("铳士",	"銃士"),
    0x4a: Archetype("时械神",	"時械神"),
    0x4b: Archetype("极神",	"極神"),
    0x4c: Archetype("落穴",	"落とし穴"),
    #setname 0x4d N/A
    #setname 0x4e 进化	エヴォル
    0x304e: Archetype("进化虫",	"エヴォルド"),
    0x504e: Archetype("进化帝",	"エヴォルカイザー"),
    0x604e: Archetype("进化龙",	"エヴォルダー"),
    #setname 0x4f 爆裂	バスター
    0x104f: Archetype("爆裂体",	"／バスター"),
    0x50: Archetype("蛇毒",	"ヴェノム"),
    0x1050: Archetype("凶饿毒|蛇毒",	"スターヴ・ヴェノム"),
    0x51: Archetype("零件",	"ガジェット"),
    0x52: Archetype("守护者",	"ガーディアン"),
    0x1052: Archetype("门之守护神|守护者",	"ゲート・ガーディアン"),
    0x2052: Archetype("法理守护者",	"ローガーディアン"),
    0x53: Archetype("星圣",	"セイクリッド"),
    0x54: Archetype("我我我",	"ガガガ"),
    0x55: Archetype("光子",	"フォトン"),
    0x56: Archetype("甲虫装机",	"甲虫装機"),
    0x57: Archetype("共鸣者",	"リゾネーター"),
    0x58: Archetype("发条",	"ゼンマイ"),
    0x59: Archetype("隆隆隆",	"ゴゴゴ"),
    0x5a: Archetype("企鹅",	"ペンギン"),
    0x5b: Archetype("番茄小子",	"トマボー"),
    0x5c: Archetype("斯芬克斯",	"スフィンクス"),
    #setname 0x5d N/A
    #setname 0x5e N/A
    #setname 0x5f N/A
    0x60: Archetype("竹光",	"竹光"),
    0x61: Archetype("忍法",	"忍法"),
    0x62: Archetype("卡通",	"トゥーン"),
    0x63: Archetype("反应机",	"リアクター"),
    0x64: Archetype("鹰身",	"ハーピィ"),
    0x65: Archetype("侵略的",	"侵略の"),
    0x66: Archetype("战士",	"ウォリアー"),
    0x1066: Archetype("音响战士",	"音響戦士"),
    0x2066: Archetype("磁石战士",	"マグネット・ウォリアー"),
    0x6066: Archetype("磁石战士Σ",	"磁石の戦士Σ"),
    #setname 0x67 钢铁	アイアン
    #setname 0x68 铁皮	ブリキ
    0x69: Archetype("圣刻",	"聖刻"),
    0x6a: Archetype("幻蝶刺客",	"幻蝶の刺客"),
    0x6b: Archetype("保镖",	"バウンサー"),
    #setname 0x6c 光芒使者	ライトレイ
    0x6d: Archetype("魔人",	"魔人（まじん）"),
    0x6e: Archetype("魔导",	"魔導"),
    0x106e: Archetype("魔导书",	"魔導書"),
    0x6f: Archetype("英豪",	"ヒロイック"),
    0x106f: Archetype("英豪挑战者",	"H・C"),
    0x206f: Archetype("英豪冠军",	"H－C"),
    0x70: Archetype("先史遗产",	"先史遺産"),
    0x71: Archetype("魔偶甜点",	"マドルチェ"),
    0x72: Archetype("齿轮齿轮",	"ギアギア"),
    0x1072: Archetype("齿轮齿轮人",	"ギアギアーノ"),
    0x73: Archetype("超量",	"エクシーズ"),
    0x1073: Archetype("混沌超量",	"CX（カオスエクシーズ）"),
    0x2073: Archetype("超量龙",	"エクシーズ・ドラゴン"),
    0x4073: Archetype("铠装超量",	"アーマード・エクシーズ"),
    0x74: Archetype("水精鳞",	"水精鱗"),
    0x75: Archetype("深渊",	"アビス"),
    0x76: Archetype("纹章兽",	"紋章獣"),
    0x77: Archetype("海皇",	"海皇"),
    0x78: Archetype("迅捷",	"素早い"),
    0x79: Archetype("炎星",	"炎星"),
    #setname 0x7a 圣	聖
    0x107a: Archetype("圣骑士",	"聖騎士（せいきし）"),
    0x207a: Archetype("圣剑",	"聖剣（せいけん）"),
    0x507a: Archetype("焰圣骑士",	"焔聖騎士"),
    0x607a: Archetype("焰圣剑",	"焔聖剣"),
    0x7b: Archetype("银河",	"ギャラクシー"),
    0x107b: Archetype("银河眼",	"ギャラクシーアイズ"),
    0x307b: Archetype("银河眼时空龙",	"ギャラクシーアイズ・タキオン・ドラゴン"),
    0x7c: Archetype("炎舞",	"炎舞"),
    0x7d: Archetype("阳炎",	"ヘイズ"),
    0x107d: Archetype("阳炎兽",	"陽炎獣"),
    0x7e: Archetype("异热同心",	"ゼアル"),
    0x107e: Archetype("异热同心武器",	"ZW（ゼアル・ウェポン）"),
    0x207e: Archetype("异热同心从者",	"ZS（ゼアル・サーバス）"),
    0x7f: Archetype("霍普",	"ホープ"),
    0x107f: Archetype("希望皇 霍普",	"希望皇ホープ"),
    0x207f: Archetype("未来皇 霍普",	"未来皇ホープ"),
    0x80: Archetype("尘妖",	"ダストン"),
    0x81: Archetype("炎王",	"炎王"),
    0x1081: Archetype("炎王兽",	"炎王獣"),
    0x82: Archetype("怒怒怒",	"ドドド"),
    0x83: Archetype("人偶",	"パペット"),
    0x1083: Archetype("机关傀儡",	"ギミック・パペット"),
    #setname 0x84 燃烧拳	バーニングナック
    0x1084: Archetype("燃烧拳击手",	"BK（バーニングナックラー）"),
    0x2084: Archetype("燃烧拳",	"バーニングナックル"),
    0x85: Archetype("超级防卫机器人",	"SDロボ"),
    0x86: Archetype("光天使",	"ライトエンジェル"),
    0x87: Archetype("阴影",	"アンブラル"),
    0x88: Archetype("武神",	"ウォース神"),
    0x89: Archetype("洞",	"ホール"),
    #setname 0x8a 虫惑	蟲惑
    0x108a: Archetype("虫惑魔",	"蟲惑魔"),
    0x8b: Archetype("食恶",	"マリスボラス"),
    #setname 0x8c 德鲁伊	ドルイド
    0x8d: Archetype("鬼计",	"ゴーストリック"),
    0x8e: Archetype("吸血鬼",	"ヴァンパイア"),
    0x8f: Archetype("刷拉拉",	"ズババ"),
    0x90: Archetype("森罗",	"森羅"),
    0x91: Archetype("王家长眠之谷",	"ネクロバレー"),
    0x92: Archetype("纹章",	"メダリオン"),
    0x93: Archetype("电子",	"サイバー"),
    0x1093: Archetype("电子龙",	"サイバー・ドラゴン"),
    0x2093: Archetype("电子化天使",	"サイバー・エンジェル"),
    0x4093: Archetype("电子暗黑",	"サイバー・ダーク/サイバーダーク"),
    0x94: Archetype("电子科技",	"サイバネティック"),
    0x95: Archetype("升阶魔法",	"RUM"),
    0x96: Archetype("电子鱼人|非「电子」",	"フィッシュボーグ"),
    0x97: Archetype("古遗物",	"アーティファクト"),
    0x98: Archetype("魔术师",	"魔術師"),
    0x99: Archetype("异色眼",	"オッドアイズ"),
    0x9a: Archetype("超重武者",	"スーパーウエイト・ファイター"),
    0x109a: Archetype("超重武者装留",	"スーパーウエイト・ファイター・アーマー"),
    0x9b: Archetype("幻奏",	"幻奏"),
    0x109b: Archetype("幻奏的音姬",	"幻奏の音姫"),
    0x9c: Archetype("星骑士",	"テラナイト"),
    0x109c: Archetype("星辉士|星骑士",	"ステラナイト"),
    0x9d: Archetype("影依",	"シャドール"),
    0x9e: Archetype("龙星",	"竜星"),
    0x9f: Archetype("娱乐伙伴",	"EM（エンタメイト）"),
    0xa0: Archetype("传说的骑士",	"伝説の騎士"),
    0xa1: Archetype("传说之龙",	"伝説の竜"),
    #setname 0xa2 魔术	マジシャン
    0x10a2: Archetype("黑魔术",	"ブラック・マジシャン"),
    0x20a2: Archetype("魔术少女",	"マジシャン・ガール"),
    0x30a2: Archetype("黑魔术少女",	"ブラック・マジシャン・ガール"),
    0xa3: Archetype("星尘",	"スターダスト"),
    0xa4: Archetype("栗子球",	"クリボー"),
    0x10a4: Archetype("羽翼栗子球",	"ハネクリボー"),
    0xa5: Archetype("变化",	"チェンジ"),
    0xa6: Archetype("幼芽",	"スプラウト"),
    0xa7: Archetype("阿托利斯",	"アルトリウス"),
    0xa8: Archetype("兰斯洛特",	"ランスロット"),
    0xa9: Archetype("毛绒动物",	"ファーニマル"),
    0xaa: Archetype("机壳",	"クリフォート"),
    0x10aa: Archetype("隐藏的机壳",	"アポクリフォート"),
    0xab: Archetype("文具电子人|非「电子」",	"ブンボーグ"),
    0xac: Archetype("哥布林",	"ゴブリン"),
    0x10ac: Archetype("哥布林骑手",	"ゴブリンライダー"),
    0xad: Archetype("魔玩具",	"デストーイ"),
    0xae: Archetype("契约书",	"契約書"),
    0xaf: Archetype("DD",	"DD"),
    0x10af: Archetype("DDD",	"DDD"),
    0xb0: Archetype("加特姆士",	"ガトムズ"),
    0xb1: Archetype("彼岸",	"彼岸"),
    0xb2: Archetype("超级运动员",	"U.A."),
    0xb3: Archetype("妖仙兽",	"妖仙獣"),
    0xb4: Archetype("影灵衣",	"影霊衣"),
    0xb5: Archetype("灵兽",	"霊獣"),
    0x10b5: Archetype("灵兽使",	"霊獣使い"),
    0x20b5: Archetype("精灵兽",	"精霊獣"),
    #0x30b5 精灵兽使	精霊獣使い
    0x40b5: Archetype("圣灵兽骑",	"聖霊獣騎"),
    0xb6: Archetype("外神",	"外神"),
    0xb7: Archetype("旧神",	"旧神"),
    0xb8: Archetype("古神",	"古神"),
    0xb9: Archetype("烈焰加农炮",	"ブレイズ・キャノン"),
    0xba: Archetype("急袭猛禽",	"RR（レイド・ラプターズ）"),
    0xbb: Archetype("狱火机",	"インフェルノイド"),
    0xbc: Archetype("人造人",	"人造人間"),
    0xbd: Archetype("暗黑骑士 盖亚",	"暗黒騎士ガイア"),
    0xbe: Archetype("帝王",	"帝王"),
    0xbf: Archetype("灵使",	"霊使い"),
    0xc0: Archetype("凭依",	"憑依"),
    0x10c0: Archetype("凭依装着",	"憑依装着"),
    0xc1: Archetype("PSY骨架",	"PSYフレーム"),
    0x10c1: Archetype("PSY骨架装备",	"PSYフレームギア"),
    0xc2: Archetype("动力工具",	"パワー・ツール"),
    0xc3: Archetype("锋利小鬼",	"エッジインプ"),
    0xc4: Archetype("神数",	"セフィラ"),
    0xc5: Archetype("炼狱",	"煉獄"),
    0xc6: Archetype("娱乐法师",	"Em（エンタメイジ）"),
    0xc7: Archetype("龙剑士",	"竜剣士"),
    0xc8: Archetype("点火骑士",	"イグナイト"),
    0xc9: Archetype("芳香",	"アロマ"),
    0xca: Archetype("魔装战士",	"魔装戦士"),
    0xcb: Archetype("以太神兵龙",	"イーサルウェポン"),
    0xcc: Archetype("占术姬",	"占術姫"),
    0xcd: Archetype("水伶女",	"アクアアクトレス"),
    0xce: Archetype("水族馆",	"アクアリウム"),
    0xcf: Archetype("混沌",	"カオス"),
    0x10cf: Archetype("混沌战士",	"カオス・ソルジャー"),
    0xd0: Archetype("威风妖怪",	"マジェスペクター"),
    0xd1: Archetype("灰篮",	"グレイドル"),
    0xd2: Archetype("星际仙踪",	"Kozmo"),
    0xd3: Archetype("坏兽",	"壊獣"),
    0xd4: Archetype("伯吉斯异兽",	"バージェストマ"),
    0xd5: Archetype("但丁",	"ダンテ"),
    0xd6: Archetype("破坏剑",	"破壊剣"),
    0xd7: Archetype("破坏之剑士",	"バスター・ブレイダー"),
    0xd8: Archetype("雾动机龙",	"ダイナミスト"),
    0xd9: Archetype("不知火",	"不知火"),
    0x10d9: Archetype("妖刀-不知火",	"妖刀－不知火"),
    0xda: Archetype("龙魔王",	"竜魔王"),
    0xdb: Archetype("幻影",	"ファントム"),
    0x10db: Archetype("幻影骑士团",	"幻影騎士団"),
    0xdc: Archetype("超级量子",	"超量"),
    0x10dc: Archetype("超级量子战士",	"超量士"),
    0x20dc: Archetype("超级量子机兽",	"超量機獣"),
    0xdd: Archetype("青眼",	"ブルーアイズ"),
    0xde: Archetype("艾克佐迪亚",	"エクゾディア"),
    0xdf: Archetype("月光",	"ムーンライト"),
    0xe0: Archetype("无形噬体",	"アモルファージ"),
    0xe1: Archetype("炼装",	"メタルフォーゼ"),
    0xe2: Archetype("三形金字塔",	"トラミッド"),
    0xe3: Archetype("方界",	"方界"),
    0xe4: Archetype("精灵剑士",	"エルフの剣士"),
    0xe5: Archetype("光波",	"サイファー"),
    0x10e5: Archetype("光波龙",	"サイファー・ドラゴン"),
    0xe6: Archetype("花札卫",	"花札衛"),
    0xe7: Archetype("沉默剑士",	"サイレント・ソードマン"),
    0xe8: Archetype("沉默魔术师",	"サイレント・マジシャン"),
    0xe9: Archetype("磁石战士",	"磁石の戦士(じしゃくのせんし)"),
    0xea: Archetype("水晶机巧|非「机巧」",	"クリストロン"),
    0xeb: Archetype("化合兽",	"化合獣"),
    #0xec	魔界	魔界
    0x10ec: Archetype("魔界剧团",	"魔界劇団"),
    0x20ec: Archetype("魔界台本",	"魔界台本"),
    0xed: Archetype("地中族",	"サブテラー"),
    0x10ed: Archetype("地中族邪界",	"サブテラーマリス"),
    0xee: Archetype("秘旋谍",	"SPYRAL"),
    0x10ee: Archetype("秘旋谍装备",	"SPYRAL GEAR"),
    0x20ee: Archetype("秘旋谍任务",	"SPYRAL MISSION"),
    0xef: Archetype("堕天使",	"堕天使"),
    0xf0: Archetype("风魔女",	"WW（ウィンド・ウィッチ）"),
    0xf1: Archetype("十二兽",	"十二獣"),
    0xf2: Archetype("灵摆",	"ペンデュラム"),
    0x10f2: Archetype("灵摆龙",	"ペンデュラム・ドラゴン"),
    0x20f2: Archetype("灵摆读阵",	"ペンデュラムグラフ"),
    0xf3: Archetype("捕食",	"プレデター"),
    0x10f3: Archetype("捕食植物",	"捕食植物"),
    0xf4: Archetype("召唤兽",	"召喚獣"),
    0xf5: Archetype("甘多拉",	"ガンドラ"),
    0xf6: Archetype("摩天楼",	"摩天楼"),
    0xf7: Archetype("抒情歌鸲",	"LL（リリカル・ルスキニア）"),
    #0xf8 霸王	覇王
    0x10f8: Archetype("霸王门",	"覇王門"),
    0x20f8: Archetype("霸王眷龙",	"覇王眷竜"),
    0xf9: Archetype("真龙",	"真竜"),
    0xfa: Archetype("幻煌龙",	"幻煌龍"),
    0xfb: Archetype("淘气仙星",	"トリックスター"),
    0xfc: Archetype("刚鬼",	"剛鬼"),
    0xfd: Archetype("星杯",	"星杯"),
    0xfe: Archetype("星遗物",	"星遺物"),
    0xff: Archetype("幻透翼",	"クリアウィング"),
    0x100: Archetype("结合术",	"ボンディング"),
    0x101: Archetype("码语者",	"コード・トーカー"),
    0x102: Archetype("弹丸",	"ヴァレット"),
    0x103: Archetype("幻变骚灵",	"オルターガイスト"),
    0x104: Archetype("机怪虫",	"クローラー"),
    0x105: Archetype("玄化",	"メタファイズ"),
    0x106: Archetype("复仇死者",	"ヴェンデット"),
    0x107: Archetype("方程式运动员",	"F.A."),
    0x108: Archetype("魔弹",	"魔弾"),
    0x109: Archetype("天气",	"天気"),
    0x10a: Archetype("珀耳修斯",	"パーシアス"),
    0x10b: Archetype("廷达魔三角",	"ティンダングル"),
    0x10c: Archetype("机界骑士",	"ジャックナイツ"),
    0x10d: Archetype("魔导兽|非「魔导」",	"魔導獣"),
    0x10e: Archetype("进化药",	"進化薬"),
    0x10f: Archetype("枪管",	"ヴァレル"),
    0x110: Archetype("纳祭",	"サクリファイス"),
    0x1110: Archetype("眼纳祭神",	"アイズ・サクリファイス"),
    0x111: Archetype("武装龙",	"アームド・ドラゴン"),
    0x112: Archetype("幻崩",	"トロイメア"),
    0x113: Archetype("灵神",	"霊神"),
    0x114: Archetype("空牙团",	"空牙団"),
    0x115: Archetype("闪刀",	"閃刀"),
    0x1115: Archetype("闪刀姬",	"閃刀姫"),
    0x116: Archetype("圣像骑士",	"パラディオン"),
    0x117: Archetype("魔神仪",	"魔神儀"),
    0x118: Archetype("电脑网",	"サイバネット"),
    0x119: Archetype("转生炎兽",	"サラマングレイト"),
    0x11a: Archetype("恐龙摔跤手",	"ダイナレスラー"),
    0x11b: Archetype("自奏圣乐",	"オルフェゴール"),
    0x11c: Archetype("雷龙",	"サンダー·ドラゴン"),
    0x11d: Archetype("禁忌的",	"禁じられた"),
    0x11e: Archetype("未界域",	"未界域"),
    0x11f: Archetype("奈芙提斯",	"ネフティス"),
    0x120: Archetype("调皮宝贝",	"プランキッズ"),
    0x121: Archetype("魔妖",	"魔妖"),
    0x122: Archetype("女武神|非「武神」",	"ワルキューレ"),
    0x123: Archetype("蔷薇",	"ローズ"),
    0x1123: Archetype("蔷薇龙",	"ローズ・ドラゴン"),
    0x124: Archetype("机械天使",	"機械天使"),
    0x125: Archetype("笑容",	"スマイル"),
    0x126: Archetype("时间潜行者",	"クロノダイバー"),
    0x127: Archetype("无限起动",	"無限起動"),
    0x128: Archetype("魔女术",	"ウィッチクラフト"),
    0x129: Archetype("咒眼",	"呪眼"),
    0x12a: Archetype("恩底弥翁",	"エンディミオン"),
    0x12b: Archetype("海晶少女",	"マリンセス"),
    0x12c: Archetype("天威",	"天威"),
    0x12d: Archetype("斯摩夫",	"シムルグ"),
    0x12e: Archetype("占卜魔女",	"占い魔女"),
    0x12f: Archetype("蜂军",	"B・F（ビー・フォース）"),
    0x130: Archetype("破械",	"破械"),
    0x1130: Archetype("破械神",	"破械神"),
    0x131: Archetype("梦魔镜",	"夢魔鏡"),
    0x132: Archetype("斩机",	"斬機"),
    0x133: Archetype("半龙女仆",	"ドラゴンメイド"),
    0x134: Archetype("王战",	"ジェネレイド"),
    0x135: Archetype("@火灵天星",	"@イグニスター"),
    0x136: Archetype("“艾”",	"Ai（アイ）"),
    0x137: Archetype("战华",	"戦華"),
    0x138: Archetype("巨石遗物",	"メガリス"),
    0x139: Archetype("守护神官",	"守護神官"),
    0x13a: Archetype("拟声",	"オノマト"),
    0x13b: Archetype("叛逆",	"リベリオン"),
    0x13c: Archetype("代码破坏者",	"コードブレイカー"),
    0x13d: Archetype("星义",	"ネメシス"),
    0x13e: Archetype("巴巴罗斯",	"バルバロス"),
    0x13f: Archetype("海造贼",	"海造賊"),
    0x140: Archetype("魔救",	"アダマシア"),
    0x141: Archetype("六花",	"六花"),
    #setname 0x142 黄金国	エルド
    0x1142: Archetype("黄金国巫妖",	"エルドリッチ"),
    0x2142: Archetype("黄金国永生药",	"エルドリクシル"),
    0x143: Archetype("黄金乡",	"黄金郷"),
    0x144: Archetype("幻魔",	"幻魔"),
    0x1144: Archetype("三幻魔",	"三幻魔"),
    0x145: Archetype("教导",	"ドラグマ"),
    0x146: Archetype("童话动物",	"メルフィー"),
    0x147: Archetype("波波",	"ポータン"),
    0x148: Archetype("罗兰",	"ローラン"),
    0x149: Archetype("化石",	"化石"),
    0x14a: Archetype("源数",	"ヌメロン"),
    0x114a: Archetype("源数之门",	"ゲート・オブ・ヌメロン"),
    0x14b: Archetype("机块",	"機塊"),
    #setname 0x14c 灵术	霊術
    0x314c: Archetype("地灵术",	"地霊術"),
    0x514c: Archetype("水灵术",	"水霊術"),
    0x614c: Archetype("火灵术",	"火霊術"),
    0x914c: Archetype("风灵术",	"風霊術"),
    #setname 0xa14c 光灵术	光霊術
    #setname 0xc14c 暗灵术	闇霊術
    0x14d: Archetype("铁兽",	"トライブリゲード"),
    0x14e: Archetype("电脑堺",	"電脳堺"),
    0x114e: Archetype("电脑堺门",	"電脳堺門"),
    0x14f: Archetype("双天",	"双天"),
    0x150: Archetype("大贤者",	"マギストス"),
    #setname 0x151 双子	Twin
    0x1151: Archetype("直播☆双子",	"Live☆Twin"),
    0x2151: Archetype("邪恶★双子",	"Evil★Twin"),
    0x152: Archetype("姬丝基勒",	"キスキル"),
    0x153: Archetype("璃拉",	"リィラ"),
    0x154: Archetype("龙辉巧",	"ドライトロン"),
    0x155: Archetype("护宝炮妖",	"スプリガンズ"),
    0x156: Archetype("治安战警队",	"S－Force"),
    0x157: Archetype("秘异三变",	"ミュートリア"),
    #setname 0x158 圣	サン
    0x1158: Archetype("圣蔓",	"サンヴァイン"),
    0x2158: Archetype("圣天树",	"サンアバロン"),
    0x4158: Archetype("圣种",	"サンシード"),
    0x159: Archetype("圣夜骑士",	"ホーリーナイツ"),
    0x15a: Archetype("人偶怪兽",	"ドール・モンスター"),
    0x15b: Archetype("惊乐",	"アメイズメント"),
    0x15c: Archetype("游乐设施",	"アトラクション"),
    0x15d: Archetype("烙印",	"烙印"),
    0x15e: Archetype("降阶魔法",	"RDM"),
    0x15f: Archetype("战吼",	"ウォークライ"),
    0x160: Archetype("原质炉",	"マテリアクトル"),
    0x161: Archetype("溟界",	"溟界"),
    0x162: Archetype("七音服",	"ドレミコード"),
    0x1162: Archetype("大钢琴之七音服",	"グランドレミコード"),
    0x163: Archetype("北极天熊",	"ベアルクティ"),
    0x164: Archetype("死狱乡",	"デスピア"),
    0x165: Archetype("魔键",	"魔鍵"),
    0x166: Archetype("军贯",	"軍貫"),
    0x1167: Archetype("森之圣兽",	"森の聖獣"),
    0x2167: Archetype("森之圣灵",	"森の聖霊"),
    0x168: Archetype("隐形水母怪",	"ステルス・クラーゲン"),
    0x169: Archetype("原数天灵",	"ヌメロニアス"),
    0x16a: Archetype("编号系",	"ナンバーズ"),
    0x16b: Archetype("相剑",	"相剣"),
    0x16c: Archetype("冰水",	"氷水"),
    0x16d: Archetype("随风旅鸟",	"ふわんだりぃず"),
    0x16e: Archetype("拓扑",	"トポロジック"),
    0x16f: Archetype("许珀里翁",	"ヒュペリオン"),
    0x170: Archetype("骑甲虫",	"ビートルーパー"),
    0x171: Archetype("朋克",	"P.U.N.K."),
    0x172: Archetype("救祓少女",	"エクソシスター"),
    0x173: Archetype("恐啡肽狂龙",	"ダイノルフィア"),
    0x174: Archetype("恶魔娘",	"悪魔嬢"),
    0x175: Archetype("七皇",	"セブンス"),
    0x176: Archetype("异晶人的",	"バリアンズ"),
    0x177: Archetype("海龙神",	"リバイアサン"),
    0x178: Archetype("潜海",	"シー・ステルス"),
    0x179: Archetype("兽带斗神",	"セリオンズ"),
    0x17a: Archetype("恐吓爪牙族",	"スケアクロー"),
    0x17b: Archetype("野蛮人",	"バーバリアン"),
    0x17c: Archetype("书灵师",	"リブロマンサー"),
    0x17d: Archetype("群豪",	"ヴァリアンツ"),
    0x17e: Archetype("拉比林斯迷宫",	"ラビュリンス"),
    0x117e: Archetype("拉比林斯迷宫欢迎",	"ウェルカム・ラビュリンス"),
    0x17f: Archetype("神碑",	"神碑"),
    0x180: Archetype("卫星闪灵",	"スプライト"),
    0x181: Archetype("珠泪哀歌族",	"ティアラメンツ"),
    0x182: Archetype("春化精",	"春化精"),
    0x183: Archetype("悠悠",	"もけもけ"),
    0x184: Archetype("翼侠",	"ウィングマン"),
    #setname 0x185 涂鸦	らくがき
    0x1185: Archetype("涂鸦兽",	"らくがきじゅう"),
    0x2185: Archetype("涂鸦本",	"らくがきちょう"),
    0x186: Archetype("G石人",	"Gゴーレム"),
    0x187: Archetype("桥梁",	"架け橋"),
    0x188: Archetype("深渊之兽",	"ビーステッド"),
    0x189: Archetype("俱舍怒威族",	"クシャトリラ"),
    0x18a: Archetype("魊影",	"ゴーティス"),
    0x18b: Archetype("救援ACE队",	"R－ACE"),
    0x18c: Archetype("纯爱妖精",	"ピュアリィ"),
    0x18d: Archetype("御巫",	"御巫"),
    0x18e: Archetype("仪水镜",	"儀水鏡"),
    0x18f: Archetype("防火",	"ファイアウォール"),
    0x190: Archetype("末那愚子族",	"マナドゥム"),
    0x191: Archetype("妮穆蕾莉娅",	"ネムレリア"),
    0x192: Archetype("黄金荣耀",	"GP（ゴールド・プライド）"),
    0x193: Archetype("迷宫壁",	"ラビリンス・ウォール"),
    0x194: Archetype("至爱",	"フェイバリット"),
    0x195: Archetype("征服斗魂",	"VS（ヴァンキッシュ・ソウル）"),
    0x196: Archetype("新式魔厨",	"ヌーベルズ"),
    0x197: Archetype("食谱",	"レシピ"),
    0x198: Archetype("维萨斯",	"ヴィサス"),
    0x199: Archetype("反击",	"カウンター"),
    0x19a: Archetype("吠陀",	"ヴェーダ"),
    0x19b: Archetype("迪亚贝尔",	"ディアベル"),
    0x119b: Archetype("迪亚贝尔斯塔尔",	"ディアベルスター"),
    0x19c: Archetype("蛇眼",	"スネークアイ"),
    0x19d: Archetype("荷鲁斯",	"ホルス"),
    0x119d: Archetype("荷鲁斯之黑炎龙",	"ホルスの黒炎竜"),
    0x19e: Archetype("罪宝",	"罪宝"),
    0x19f: Archetype("圣菓使",	"聖菓使"),
    0x1a0: Archetype("哈特",	"ハート"),
    0x1a1: Archetype("莫忘",	"メメント"),
    0x1a2: Archetype("百夫长骑士",	"センチュリオン"),
    0x1a3: Archetype("异响鸣",	"ヴァルモニカ"),
    0x1a4: Archetype("提斯蒂娜",	"ティスティナ"),
    0x1a5: Archetype("于贝尔",	"ユベル"),
    0x1a6: Archetype("肃声",	"粛声"),
    0x1a7: Archetype("白斗气",	"ホワイト・オーラ"),
    0x1a8: Archetype("玩具",	"トイ"),
    0x1a9: Archetype("灿幻",	"燦幻"),
    0x1aa: Archetype("天杯龙",	"天盃龍"),
    0x1ab: Archetype("蕾祸",	"蕾禍"),
    0x1ac: Archetype("飞龙炎",	"サラマンドラ"),
    0x1ad: Archetype("灰灭",	"灰滅"),
    0x1ae: Archetype("千年",	"千年/ミレニアム"),
    0x1af: Archetype("艾格佐德",	"エグゾード"),
    0x1b0: Archetype("刻魔",	"デモンスミス"),
    0x1b1: Archetype("白森林",	"白き森"),
    0x1b2: Archetype("欢聚友伴",	"マルチャミー"),
    0x1b3: Archetype("徽记",	"エンブレーマ"),
    0x1b4: Archetype("时空",	"タキオン"),
    0x1b5: Archetype("蓝泪",	"青い涙"),
    0x1b6: Archetype("石版",	"石版"),
    0x1b7: Archetype("迷拟宝箱鬼",	"ミミグル"),
    0x1b8: Archetype("鲨",	"シャーク"),
    0x11b8: Archetype("鲨龙兽",	"シャーク・ドレイク"),
    0x1b9: Archetype("原石",	"原石"),
    0x1ba: Archetype("金属化",	"メタル化"),
    0x1bb: Archetype("魔瞳",	"モルガナイト"),
    0x1bc: Archetype("蓟花",	"アザミナ"),
    0x1bd: Archetype("祝台",	"祝台"),
    0x1be: Archetype("雷火沸动",	"ライゼオル"),
    0x1bf: Archetype("码丽丝",	"M∀LICE"),
    0x1c0: Archetype("龙华",	"竜華"),
    0x1c1: Archetype("阿尔戈☆群星",	"ARG☆S"),
    0x1c2: Archetype("喷水引擎",	"アクア・ジェット"),
    0x1c3: Archetype("巳剑",	"巳剣"),
    0x1c4: Archetype("征龙",	"征竜"),
    0x1c5: Archetype("再世",	"リジェネシス"),
    0x1c6: Archetype("统王",	"ドミナス"),
    0x1c7: Archetype("塞勒凯特",	"セルケト"),
    0x1c8: Archetype("阿匹卜",	"アポピス"),
    0x1c9: Archetype("星辰",	"ドラゴンテイル"),
    0x1ca: Archetype("味美喵",	"ヤミー"),
    0x1cb: Archetype("K9",	"K9"),
    0x1cc: Archetype("瞬间移动",	"テレポート"),
    0x1cd: Archetype("神艺",	"アルトメギア"),
    0x1ce: Archetype("狱神",	"獄神"),
    0x1cf: Archetype("奏悦机组",	"R.B."),
    0x1d0: Archetype("死伟王",	"死偉王"),
    0x1d1: Archetype("绚岚",	"絢嵐"),
    0x1d2: Archetype("终刻",	"ドゥームズ"),
    0x1d3: Archetype("不可见之手",	"ヘカトンケイル"),
    0x1d4: Archetype("纠罪巧",	"糾罪巧"),
    0x1d5: Archetype("杀手级调整曲",	"キラーチューン"),
    0x1d6: Archetype("树熊",	"コアラ"),
    0x1d7: Archetype("艾克莉西娅",	"エクレシア"),
    0x1d8: Archetype("耀圣",	"エルフェンノーツ"),
    0x1d9: Archetype("磁力",	"マグネット"),
    0x1da: Archetype("世界末日",	"エンド・オブ・ザ・ワールド"),
    0x1db: Archetype("妖精传姬",	"妖精伝姫"),
    0x1dc: Archetype("道化一座",	"道化の一座"),
    0x1dd: Archetype("GMX",	"GMX"),
    0x1de: Archetype("暗黑调整",	"DT"),
    0x1df: Archetype("雷盟",	"ブリッツクリーク"),
    0x1e0: Archetype("预幻",	"テオリアライズ"),
    0x1e1: Archetype("阿莱斯特",	"アレイスター")
}

# Pre-computed index: root code → list of (full_code, Archetype).
_archetypes_by_root_raw: dict[int, list[tuple[int, Archetype]]] = defaultdict(list)
for _code, _arch in ARCHETYPES.items():
    _archetypes_by_root_raw[_code & 0x0FFF].append((_code, _arch))
ARCHETYPES_BY_ROOT: dict[int, list[tuple[int, Archetype]]] = dict(_archetypes_by_root_raw)
