from __future__ import annotations

PROFESSIONS = {
    "retired_soldier": {
        "label": "Retired Soldier",
        "label_zh": "退役士兵",
        "background_zh": "退伍后难以适应平静生活，身上仍带着旧战场的阴影。",
        "skills": {"firearms": 60, "survival": 40, "intimidation": 50},
    },
    "police": {
        "label": "Police",
        "label_zh": "警察",
        "background_zh": "习惯于追踪线索与维持秩序，对危险场景有敏锐直觉。",
        "skills": {"law": 50, "spot_hidden": 40, "firearms": 50},
    },
    "doctor": {
        "label": "Doctor",
        "label_zh": "医生",
        "background_zh": "长期直面生死，对人体与创伤处理经验丰富。",
        "skills": {"medicine": 70, "first_aid": 60, "psychology": 30},
    },
    "professor": {
        "label": "Professor",
        "label_zh": "大学教授",
        "background_zh": "学术生涯让你对古老知识与研究方法颇有心得。",
        "skills": {"library_use": 60, "history": 50, "research": 50},
    },
    "private_detective": {
        "label": "Private Detective",
        "label_zh": "私人侦探",
        "background_zh": "擅长跟踪与盘问，在灰色地带游走。",
        "skills": {"psychology": 40, "spot_hidden": 60, "law": 40},
    },
    "journalist": {
        "label": "Journalist",
        "label_zh": "记者",
        "background_zh": "追逐真相与独家消息，对人心与舆论极其敏感。",
        "skills": {"persuade": 50, "research": 60, "fast_talk": 40},
    },
    "occult_researcher": {
        "label": "Occult Researcher",
        "label_zh": "神秘学研究者",
        "background_zh": "你相信世界背后存在超自然真相，并试图证明它。",
        "skills": {"occult": 70, "mythos": 20, "history": 40},
    },
    "engineer": {
        "label": "Engineer",
        "label_zh": "工程师",
        "background_zh": "对机械与结构了然于心，能快速分析故障根源。",
        "skills": {"mechanical_repair": 60, "electrical_repair": 50},
    },
    "archaeologist": {
        "label": "Archaeologist",
        "label_zh": "考古学家",
        "background_zh": "常年与遗迹为伍，对古文明与遗物极其敏感。",
        "skills": {"archaeology": 60, "history": 50, "spot_hidden": 30},
    },
    "lawyer": {
        "label": "Lawyer",
        "label_zh": "律师",
        "background_zh": "熟悉法律与谈判，擅长在规则中寻找突破口。",
        "skills": {"law": 70, "persuade": 40, "credit_rating": 50},
    },
    "nurse": {
        "label": "Nurse",
        "label_zh": "护士",
        "background_zh": "照护经验让你冷静细致，能稳定他人情绪。",
        "skills": {"first_aid": 70, "medicine": 40, "psychology": 30},
    },
    "photojournalist": {
        "label": "Photojournalist",
        "label_zh": "摄影记者",
        "background_zh": "用镜头记录真相，擅长在混乱中捕捉关键信息。",
        "skills": {"photography": 70, "spot_hidden": 40, "sneak": 30},
    },
}
