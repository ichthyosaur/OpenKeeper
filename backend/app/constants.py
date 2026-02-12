from __future__ import annotations

PROFESSIONS = {
    "retired_soldier": {
        "label": "Retired Soldier",
        "label_zh": "退役士兵",
        "background_zh": "退伍后你仍习惯清点口袋里的弹匣与伤疤。你在平静的街道里听见并不存在的炮声，夜里常被旧梦惊醒。对纪律的依赖让你难以信任陌生人，但你知道在恐惧面前必须有人站在最前面。",
        "skills": {"firearms": 60, "survival": 45, "intimidation": 50, "first_aid": 30, "spot_hidden": 35, "brawl": 55},
    },
    "police": {
        "label": "Police",
        "label_zh": "警察",
        "background_zh": "你受过系统训练，习惯把现场拆解成线索与时间。街巷的气味、人的表情、证词的细微差别都不会逃过你的眼睛。你相信秩序，但也见过秩序背后隐藏的混乱。",
        "skills": {"law": 55, "spot_hidden": 55, "firearms": 50, "psychology": 35, "fast_talk": 30, "brawl": 45},
    },
    "doctor": {
        "label": "Doctor",
        "label_zh": "医生",
        "background_zh": "长期直面生死使你对痛苦保持冷静。你知道人体的脆弱，也知道人心更难缝合。你越是靠近异常，就越怀疑某些疾病并非来自自然。",
        "skills": {"medicine": 70, "first_aid": 60, "psychology": 40, "research": 40, "spot_hidden": 25, "persuade": 30},
    },
    "professor": {
        "label": "Professor",
        "label_zh": "大学教授",
        "background_zh": "你在图书馆与讲堂之间度过大半生。纸张上的墨迹比街头的声音更可信，但你也明白知识并不总是安全的。某些古籍的脚注让你隐隐不安。",
        "skills": {"library_use": 65, "history": 55, "research": 55, "occult": 25, "psychology": 20, "persuade": 30},
    },
    "private_detective": {
        "label": "Private Detective",
        "label_zh": "私人侦探",
        "background_zh": "你在灰色地带谋生，见惯了谎言与隐藏的动机。跟踪与盘问是你的本能，直觉比任何合同更可靠。你知道每个“失踪”背后都有难以见光的故事。",
        "skills": {"psychology": 45, "spot_hidden": 65, "law": 40, "fast_talk": 45, "sneak": 40, "firearms": 40},
    },
    "journalist": {
        "label": "Journalist",
        "label_zh": "记者",
        "background_zh": "你追逐真相，也追逐能让报纸卖得更好的标题。你善于从人群中提炼重点，从沉默里撬出回答。可每一次“独家”都可能把你带到更深的阴影里。",
        "skills": {"persuade": 55, "research": 60, "fast_talk": 45, "psychology": 30, "spot_hidden": 35, "photography": 30},
    },
    "occult_researcher": {
        "label": "Occult Researcher",
        "label_zh": "神秘学研究者",
        "background_zh": "你相信现实并非全部，世界边缘还有更古老的真相。禁书与逸闻让你着迷，也让你更加孤独。你知道每一次求知都可能付出代价。",
        "skills": {"occult": 75, "mythos": 25, "history": 45, "library_use": 45, "research": 40, "psychology": 25},
    },
    "engineer": {
        "label": "Engineer",
        "label_zh": "工程师",
        "background_zh": "你相信结构与逻辑，也相信问题总有可拆解的方式。机器的故障比人心更诚实，但你也见过机械无法解释的异常。面对崩塌，你更愿意亲手把它撑住。",
        "skills": {"mechanical_repair": 65, "electrical_repair": 55, "research": 40, "spot_hidden": 30, "navigate": 25, "survival": 20},
    },
    "archaeologist": {
        "label": "Archaeologist",
        "label_zh": "考古学家",
        "background_zh": "你在尘土与遗迹中寻找被遗忘的故事。每一件碎片都可能是通往过去的钥匙，也可能是被封存的诅咒。你对古文明的敬畏早已超过学术兴趣。",
        "skills": {"archaeology": 65, "history": 55, "spot_hidden": 40, "navigate": 30, "library_use": 35, "persuade": 25},
    },
    "nurse": {
        "label": "Nurse",
        "label_zh": "护士",
        "background_zh": "你习惯安抚惊恐的病人，也懂得在混乱中保持冷静。你看过太多无声的绝望，因此更愿意伸手帮助他人。某些伤口并不在皮肤之上，这一点你比任何人都清楚。",
        "skills": {"first_aid": 70, "medicine": 45, "psychology": 40, "persuade": 30, "spot_hidden": 25, "fast_talk": 20},
    },
    "painter": {
        "label": "Painter",
        "label_zh": "画家",
        "background_zh": "你以色彩与光影谋生，能从细微差别里捕捉情绪与异常。你见过的东西太多，常常怀疑现实是否不过是一层薄薄的颜料。",
        "skills": {"art": 70, "spot_hidden": 45, "psychology": 35, "persuade": 25, "history": 25, "library_use": 20},
    },
    "sculptor": {
        "label": "Sculptor",
        "label_zh": "雕塑家",
        "background_zh": "你习惯在石与金属中寻找形体，理解结构的微妙平衡。你知道某些古老雕像藏着不该存在的细节。",
        "skills": {"art": 70, "craft": 55, "spot_hidden": 30, "history": 30, "persuade": 20, "mechanical_repair": 20},
    },
    "librarian": {
        "label": "Librarian",
        "label_zh": "图书馆员",
        "background_zh": "你熟悉每一排书架的气味与阴影。卷册里的蛛丝马迹是你的世界，而现实中的喧嚣令你不安。越深的知识，越像一扇不应开启的门。",
        "skills": {"library_use": 75, "research": 55, "history": 40, "occult": 20, "spot_hidden": 25, "persuade": 25},
    },
    "antiquarian": {
        "label": "Antiquarian",
        "label_zh": "古董商",
        "background_zh": "你在旧物与传闻之间周旋，懂得如何辨别真伪。每一件古董背后都藏着故事，有些故事会咬人。你能从锈迹与灰尘里嗅出危险的味道。",
        "skills": {"credit_rating": 60, "appraisal": 60, "history": 45, "persuade": 35, "occult": 30, "spot_hidden": 25},
    },
    "author": {
        "label": "Author",
        "label_zh": "作家",
        "background_zh": "你靠文字谋生，习惯从琐碎细节里拼出真相。你知道故事会吞噬写作者，也知道某些故事不该被写下。可当异常逼近，你仍会拿起笔记录一切。",
        "skills": {"library_use": 60, "research": 60, "persuade": 40, "psychology": 35, "history": 30, "spot_hidden": 25},
    },
    "dockworker": {
        "label": "Dockworker",
        "label_zh": "码头工人",
        "background_zh": "你在潮湿与嘈杂中讨生活，手上总沾着盐与油。你了解货物与船只，也知道码头角落里藏着多少秘密。你不擅长文书，但你能扛起任何重担。",
        "skills": {"brawl": 65, "intimidation": 45, "spot_hidden": 35, "survival": 30, "mechanical_repair": 25, "sneak": 20},
    },
    "chemist": {
        "label": "Chemist",
        "label_zh": "化学师",
        "background_zh": "你熟悉药剂与反应，知道气味与沉淀背后的含义。实验室里的秩序让你安心，但现实从不遵守公式。你开始怀疑有些元素并不属于这个世界。",
        "skills": {"chemistry": 75, "medicine": 35, "research": 45, "occult": 20, "spot_hidden": 25, "library_use": 30},
    },
}
