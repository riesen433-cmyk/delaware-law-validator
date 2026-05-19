"""
Delaware 法律领域注册表 — 驱动跨类型引用检测。

所有实体类型、法院规则集、UCC Article 之间的映射关系集中在这里。
Topic review 函数遍历注册表条目来检测不匹配，而不是每个场景写一个 if。

添加新的实体类型 / 法院 / UCC Article 时只需新增注册表条目，
不会新增 if 分支。
"""

# ── Entity Type Registry ────────────────────────────────────────────────────
# 每个 Delaware business entity type 对应一个 Title + Chapter。
# 当文本的语境（context_terms）匹配某个 entity type，但引用的条文
# 属于另一个 entity type 的 chapter 时 → 报跨类型错误。

ENTITY_TYPE_REGISTRY: list[dict] = [
    {
        "entity_type": "lp",
        "label": "LP (Limited Partnership)",
        "act": "DRULPA",
        "title": 6,
        "chapter": "17",
        "chapter_slug": "Limited Partnerships",
        "context_terms": {
            "limited partnership", "drulpa",
            "delaware revised uniform limited partnership act",
        },
        "citation_pattern": r"\b6\s+Del\.?\s*C\.?\s*§\s*17-\d+",
    },
    {
        "entity_type": "llc",
        "label": "LLC (Limited Liability Company)",
        "act": "DLLCA",
        "title": 6,
        "chapter": "18",
        "chapter_slug": "Limited Liability Company Act",
        "context_terms": {
            "limited liability company", "llc", "dllca",
            "delaware limited liability company act",
        },
        "citation_pattern": r"\b6\s+Del\.?\s*C\.?\s*§\s*18-\d+",
    },
    {
        "entity_type": "gp",
        "label": "GP (General Partnership)",
        "act": "DRUPA",
        "title": 6,
        "chapter": "15",
        "chapter_slug": "General Partnerships",
        "context_terms": {
            "general partnership", "drupa",
            "delaware revised uniform partnership act",
        },
        "citation_pattern": r"\b6\s+Del\.?\s*C\.?\s*§\s*15-\d+",
    },
    {
        "entity_type": "corporation",
        "label": "Corporation (DGCL)",
        "act": "DGCL",
        "title": 8,
        "chapter": None,
        "chapter_slug": "Delaware General Corporation Law",
        "context_terms": {
            "corporation", "dgcl", "delaware general corporation law",
            "board of directors", "stockholder", "shareholder",
        },
        "citation_pattern": r"\b8\s+Del\.?\s*C\.?\s*§\s*\d+",
    },
]

# ── Court Rule Registry ─────────────────────────────────────────────────────
# 每个 Delaware court 对应一个 rule set。
# 当文本语境提及某个 court，但引用的 rule 属于另一个 court 的 rule set 时
# → 报跨法院错误。

COURT_RULE_REGISTRY: list[dict] = [
    {
        "court_key": "chancery",
        "name": "Court of Chancery",
        "rule_set_doc_id": "court-rule-chancery",
        "citation_prefix": "Del. Ch. Ct. R.",
        "context_terms": {
            "court of chancery", "chancery court",
            "chancery action", "chancery proceeding",
        },
        "citation_pattern": r"Del\.?\s*Ch\.?\s*Ct\.?\s*R\.?\s*[0-9]",
    },
    {
        "court_key": "superior",
        "name": "Superior Court",
        "rule_set_doc_id": "court-rule-superior-civil",
        "citation_prefix": "Del. Super. Ct. Civ. R.",
        "context_terms": {
            "superior court",
        },
        "citation_pattern": r"Del\.?\s*Super\.?\s*Ct\.?\s*Civ\.?\s*R\.?\s*[0-9]",
    },
    {
        "court_key": "supreme",
        "name": "Supreme Court",
        "rule_set_doc_id": "court-rule-supreme",
        "citation_prefix": "Del. Supr. Ct. R.",
        "context_terms": {
            "supreme court",
        },
        "citation_pattern": r"Del\.?\s*Supr\.?\s*Ct\.?\s*R\.?\s*[0-9]",
    },
    {
        "court_key": "family",
        "name": "Family Court",
        "rule_set_doc_id": "court-rule-family-civil",
        "citation_prefix": "Del. Fam. Ct. Civ. R.",
        "context_terms": {
            "family court",
        },
        "citation_pattern": r"Del\.?\s*Fam\.?\s*Ct\.?\s*Civ\.?\s*R\.?\s*[0-9]",
    },
    {
        "court_key": "common-pleas",
        "name": "Court of Common Pleas",
        "rule_set_doc_id": "court-rule-common-pleas-civil",
        "citation_prefix": "Del. Ct. Com. Pl. Civ. R.",
        "context_terms": {
            "court of common pleas", "common pleas court",
        },
        "citation_pattern": r"Del\.?\s*Ct\.?\s*Com\.?\s*Pl\.?\s*Civ\.?\s*R\.?\s*[0-9]",
    },
]

# ── UCC Article Registry ────────────────────────────────────────────────────
# 记录每个 UCC Article 的主题领域和容易混淆的 Article。
# 当 Article X 的 section 被 Article Y 的主题语境引用时 → 报 UCC 跨 Article 错误。

UCC_ARTICLE_REGISTRY: list[dict] = [
    {
        "article": "2",
        "label": "Sales / Sale of Goods",
        "topic_terms": {
            "warranty", "warranty disclaimer", "merchantability",
            "implied warranty", "warranty of fitness",
            "sale of goods", "goods", "contract for sale",
        },
        "section_pattern": r"2-\d+",
    },
    {
        "article": "9",
        "label": "Secured Transactions",
        "topic_terms": {
            "security interest", "perfection", "perfected",
            "financing statement", "collateral", "priority",
            "control", "secured transaction",
        },
        "section_pattern": r"9-\d+",
    },
    {
        "article": "2A",
        "label": "Leases",
        "topic_terms": {
            "lease", "leases", "finance lease",
        },
        "section_pattern": r"2A-\d+",
    },
    {
        "article": "7",
        "label": "Documents of Title",
        "topic_terms": {
            "document of title", "warehouse receipt", "bill of lading",
        },
        "section_pattern": r"7-\d+",
    },
    {
        "article": "8",
        "label": "Investment Securities",
        "topic_terms": {
            "investment security", "stock certificate", "broker",
        },
        "section_pattern": r"8-\d+",
    },
]

# ── Known cross-Title numbering traps ───────────────────────────────────────
# 有些 Section 编号约定俗成地属于某个 Title，当它们出现在错误的 Title 下
# 时，很可能是引用者把编号体系搞混了。
# 例如：§ 170 是 DGCL (Title 8) 的分红条款，不应出现在 Title 6 (LP) 下。

CROSS_TITLE_NUMBER_TRAPS: list[dict] = [
    {
        "label": "DGCL § 170 dividends → DRULPA",
        "wrong_title": 6,
        "wrong_section": "17-170",
        "right_citation": "8 Del. C. § 170",
        "reason": "DGCL § 170（dividends/solvency）被错误套入 DRULPA 编号体系；LP 分配/偿付能力限制应查 § 17-607。",
        "suggestions": [
            ("6 Del. C. § 17-607", "Limitations on distribution"),
        ],
        "context_terms": {
            "solvency", "dividend", "distribution", "asset",
            "liability", "liabilities", "偿付能力", "分配",
        },
    },
    {
        "label": "§ 17-406 is remedies for breach, not professional reliance",
        "wrong_title": 6,
        "wrong_section": "17-406",
        "right_citation": "6 Del. C. § 17-407",
        "reason": "§ 17-406 是 breach of partnership agreement 的救济条款；professional reliance 应在 § 17-407。",
        "suggestions": [
            ("6 Del. C. § 17-407", "Reliance on reports and information by limited partner"),
        ],
        "context_terms": {
            "rely", "reliance", "opinion", "report", "professional",
            "expert", "information", "信赖", "依赖", "意见", "报告", "专业",
        },
    },
    {
        "label": "§ 17-1101 is LP statute (DRULPA), not LLC Act",
        "wrong_title": 6,
        "wrong_section": "17-1101",
        "right_citation": "6 Del. C. § 18-1101",
        "reason": "§ 17-1101 是 DRULPA（LP）条文；LLC fiduciary waiver 应在 Title 6 Chapter 18（DLLCA）。",
        "suggestions": [
            ("6 Del. C. § 18-1101", "Construction and application of chapter and limited liability company agreement"),
        ],
        "context_terms": {
            "llc", "limited liability company", "dllca", "fiduciary",
            "waiver", "member", "manager",
        },
    },
    {
        "label": "§ 17-607(b) is partner return liability, not asset/liability test",
        "wrong_title": 6,
        "wrong_section": "17-607",
        "subsection": "(b)",
        "right_citation": "6 Del. C. § 17-607(a)",
        "reason": "§ 17-607(b) 是 LP partner 对不当分配的返还责任；asset/liability ratio test 在 § 17-607(a)。",
        "suggestions": [
            ("6 Del. C. § 17-607(a)", "Limitations on distribution — asset/liability test"),
        ],
        "context_terms": {
            "solvency", "asset", "liability", "ratio", "fair value",
            "distribution", "total assets", "total liabilities",
            "偿付能力", "资产", "负债",
        },
    },
    {
        "label": "§ 3920 is social work telehealth, not general telehealth",
        "wrong_title": 24,
        "wrong_section": "3920",
        "right_citation": "24 Del. C. § 6002",
        "reason": "§ 3920 是社会工作者 telehealth 条文；一般健康护理 telehealth 应在 Chapter 60 (§ 6002)。",
        "suggestions": [
            ("24 Del. C. § 6002", "Definitions relating to telehealth"),
            ("24 Del. C. § 6004", "Standard of care"),
        ],
        "context_terms": {
            "telehealth", "telemedicine", "remote health", "health-care",
            "healthcare", "medical", "physician",
        },
    },
    {
        "label": "Public works bonds should reference Title 29 procurement, not Title 18 insurance",
        "wrong_title": 18,
        "wrong_section": None,
        "right_citation": "29 Del. C. ch. 69",
        "reason": "公共工程履约保证金/付款保证金应引用 Title 29 采购规则，而非 Title 18 保险法。",
        "suggestions": [
            ("29 Del. C. ch. 69", "State Procurement"),
            ("29 Del. C. § 6961", "Small public works contract procedures"),
            ("29 Del. C. § 6962", "Large public works contract procedures"),
        ],
        "context_terms": {
            "performance bond", "payment bond", "bid bond",
            "public works", "construction bond", "contractor",
        },
    },
    {
        "label": "Chapter 30 is mental health, not social work — social work is Chapter 39",
        "wrong_title": 24,
        "wrong_section": None,
        "right_citation": "24 Del. C. ch. 39",
        "reason": "Chapter 30 是 mental health / chemical dependency；social work 应在 Chapter 39。",
        "suggestions": [
            ("24 Del. C. ch. 39", "Board of Social Work Examiners"),
        ],
        "context_terms": {
            "social work", "social worker",
        },
    },
    {
        "label": "Underground utility damage prevention should be Title 26 Chapter 8, not Title 26 Chapter 12",
        "wrong_title": 26,
        "wrong_section": None,
        "right_citation": "26 Del. C. ch. 8",
        "reason": "地下公用设施损坏预防应在 Title 26 Chapter 8；Chapter 12 是其他内容。",
        "suggestions": [
            ("26 Del. C. ch. 8", "Underground Utility Damage Prevention and Safety"),
            ("26 Del. C. § 801", "Purpose; citation; construction"),
        ],
        "context_terms": {
            "underground utility", "utility damage", "excavat",
            "damage prevention", "one-call", "one call",
        },
    },

    # ── Title 12 Trust & Estates domain traps ────────────────────────────
    {
        "label": "§ 3528 is invade principal/income, NOT decanting",
        "wrong_title": 12,
        "wrong_section": "3528",
        "right_citation": "12 Del. C. § 3525",
        "reason": "§ 3528 是受托人动用本金或收益的权限，不是无限制 decanting 授权。Decanting 应查 § 3525/§ 3526。",
        "suggestions": [
            ("12 Del. C. § 3525", "Decanting — distribution to second trust"),
            ("12 Del. C. § 3526", "Decanting — fiduciary duties"),
        ],
        "context_terms": {
            "decant", "decanting", "second trust", "modify trust", "modify any trust",
            "distributing all trust property", "without consent", "trust protector",
        },
    },
    {
        "label": "§ 3549 is marital deduction gift, NOT cy pres",
        "wrong_title": 12,
        "wrong_section": "3549",
        "right_citation": "12 Del. C. § 3541",
        "reason": "§ 3549 是婚姻扣除赠与（税务合规），不是 cy pres 原则。Cy pres 应在 § 3541。",
        "suggestions": [
            ("12 Del. C. § 3541", "Cy pres rule for charitable trusts"),
        ],
        "context_terms": {
            "cy pres", "cy-pres", "charitable purpose", "charitable trust",
            "impossible or impracticable", "another charitable purpose",
        },
    },
    {
        "label": "§ 1130 is Definitions, NOT unclaimed property reporting",
        "wrong_title": 12,
        "wrong_section": "1130",
        "right_citation": "12 Del. C. ch. 11",
        "reason": "§ 1130 是 Definitions 条目，不是 unclaimed property 报告要求。",
        "suggestions": [
            ("12 Del. C. ch. 11", "Unclaimed Property"),
        ],
        "context_terms": {
            "unclaimed property", "escheat", "escheator", "report and remit",
            "abandoned property",
        },
    },
    {
        "label": "§ 2321 is consent by parent (adoption), NOT full minor guardianship",
        "wrong_title": 13,
        "wrong_section": "2321",
        "right_citation": "13 Del. C. ch. 23",
        "reason": "§ 2321 是 adoption 中的父母同意条款，不是全面的 minor guardianship 框架。",
        "suggestions": [
            ("13 Del. C. ch. 23", "Guardianship of minors"),
        ],
        "context_terms": {
            "guardianship", "minor", "minor child", "guardian of a minor",
            "full authority", "personal and financial affairs",
        },
    },
    {
        "label": "§ 1901 is personal property of estate, NOT spousal elective share",
        "wrong_title": 12,
        "wrong_section": "1901",
        "right_citation": "12 Del. C. § 901",
        "reason": "§ 1901 是关于 estate 中个人财产的认定，不是配偶 elective share 计算条款。Elective share 应在 § 901。",
        "suggestions": [
            ("12 Del. C. § 901", "Right to elective share"),
        ],
        "context_terms": {
            "elective share", "surviving spouse", "spousal elective",
            "one-third", "marital share",
        },
    },
    {
        "label": "§ 3313 is investment advisers for directed trusts, NOT trust modification/revocation",
        "wrong_title": 12,
        "wrong_section": "3313",
        "right_citation": "12 Del. C. ch. 33",
        "reason": "§ 3313 是 directed trust 的投资顾问条款，不是 settlor 修改或撤销信托的授权。",
        "suggestions": [
            ("12 Del. C. ch. 33", "Trust Administration"),
        ],
        "context_terms": {
            "modify", "revoke", "revocation", "settlor", "modification",
            "written instrument", "change trust",
        },
    },
    {
        "label": "§ 3302 is degree of care for trustees, NOT power of attorney",
        "wrong_title": 12,
        "wrong_section": "3302",
        "right_citation": "12 Del. C. ch. 49A",
        "reason": "§ 3302 是受托人注意义务标准，不是 durable power of attorney 下的代理人权限。",
        "suggestions": [
            ("12 Del. C. ch. 49A", "Durable Personal Powers of Attorney Act"),
            ("12 Del. C. § 49A-101", "Short title"),
        ],
        "context_terms": {
            "power of attorney", "agent", "durable power", "make gifts",
            "change beneficiary", "beneficiary designation",
        },
    },
    {
        "label": "§ 501 is intestate succession, NOT guardianship or estate administration",
        "wrong_title": 12,
        "wrong_section": "501",
        "right_citation": "12 Del. C. § 3901",
        "reason": "§ 501 是 intestate succession（无遗嘱继承），不是 adult guardianship 或 estate administration。",
        "suggestions": [
            ("12 Del. C. § 3901", "Appointment of guardians for persons with disabilities"),
            ("12 Del. C. ch. 15", "Letters Testamentary and Letters of Administration"),
        ],
        "context_terms": {
            "guardianship", "guardian", "person with disabilities",
            "disabled person", "intellectual disabilities", "personal representative",
            "administer the estate", "collecting assets", "paying debts",
        },
    },
    {
        "label": "§ 2501 is Advance Health-Care Directive Act title, NOT anatomical gifts",
        "wrong_title": 16,
        "wrong_section": "2501",
        "right_citation": "16 Del. C. § 2712",
        "reason": "§ 2501 是 Advance Health-Care Directive Act 的 short title，不是 anatomical gifts。Anatomical gifts 应在 Chapter 27。",
        "suggestions": [
            ("16 Del. C. § 2712", "Making, amending, revoking, and refusing anatomical gift"),
        ],
        "context_terms": {
            "anatomical gift", "organ donation", "transplantation",
            "body", "tissues", "organs", "deceased donor",
        },
    },
    {
        "label": "6 Del. C. § 5001 is Title 6 Definitions, digital asset fiduciary access is Title 12 Chapter 50",
        "wrong_title": 6,
        "wrong_section": "5001",
        "right_citation": "12 Del. C. § 5001",
        "reason": "Title 6 § 5001 是 Commerce and Trade 的定义条款；digital asset fiduciary access 应在 Title 12 Chapter 50。",
        "suggestions": [
            ("12 Del. C. § 5001", "Short title — Fiduciary Access to Digital Assets Act"),
        ],
        "context_terms": {
            "digital asset", "digital assets", "fiduciary access",
            "trustee", "personal representative", "agent",
            "decedent", "principal",
        },
    },
]
