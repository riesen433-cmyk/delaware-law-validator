---
name: delaware-law-validator
description: Use when handling Delaware law, Delaware Code, Delaware Constitution, Delaware court rules, D.R.E., DRULPA, DGCL, Delaware LP/LLC/corporate statutes, or checking Delaware legal citations. The agent must call the local lookup/search/validate tool before citing Delaware law or Delaware court rules and must warn when requested materials are outside the local data pack coverage.
---

# Delaware Law Validator

Use this skill whenever the user asks about Delaware law, drafts or reviews Delaware-law documents, or asks you to verify Delaware legal citations.

## Positioning

This skill is a legal-material verification layer for an agent. It is not a contract review tool, does not replace lawyer review, and must not be presented as legal advice.

The skill gives the agent a way to check whether Delaware legal materials mentioned in a document actually exist and are traceable to covered or official sources. It verifies citations and source coverage; it does not decide whether the contract as a whole is legally sufficient, commercially appropriate, enforceable, or complete.

Use this skill to answer narrow verification questions:

- Does this Delaware Code section, court rule, or Administrative Code regulation exist?
- Is this citation within the local data pack or official online Administrative Code workflow?
- Is the cited source statutory law, court rule, current regulation, pending bill, session law, or outside coverage?
- Is the reference too broad, such as an entire Title or Chapter, for the legal point being made?
- Was a regulation fetched from an official source, and when was it cached?

Do not use this skill to conclude that a contract clause is valid, enforceable, market, complete, or legally sufficient. After verification, the agent should still describe the result as citation/material checking and preserve any need for official-source review or lawyer review.

## AI citation extraction

This skill does **not** call any external LLM API. The agent (Claude) performs citation extraction directly using its own capabilities.

When reviewing a document or contract text for Delaware legal citations:

1. **Extract**: Scan the text and identify ALL legal citations in any format — statutes, court rules, Admin Code references, chapter references, federal citations, other-state citations, bills, and case law.
2. **Classify**: Mark each as Delaware statute / court rule / Admin Code / federal / other-state / bill / uncovered (case law, secondary sources).
3. **Flag mismatches**: Check for known topic traps (see "Citation review behavior" below). A section may exist but be about the wrong topic.
4. **Verify**: Use the CLI `validate` or `lookup` commands to confirm every Delaware citation against the local database.
5. **Report**: Present results in the seven-category format (see "Required output behavior" below).

For the full list of known topic-mismatch traps, see `delaware_law_skill/ai_validator.py` `SYSTEM_PROMPT`.

## Core rule

Do not cite Delaware law from memory. First call the local CLI from the project root:

```bash
python3 -m delaware_law_skill.cli lookup "6 Del. C. § 17-407"
python3 -m delaware_law_skill.cli lookup "Court of Chancery Rule 12(b)(6)"
python3 -m delaware_law_skill.cli lookup "D.R.E. 403"
python3 -m delaware_law_skill.cli search "limited partnership distribution"
python3 -m delaware_law_skill.cli admin-search "24 DE Admin. Code 3900" --title 24
python3 -m delaware_law_skill.cli validate "as permitted by Section 17-406 of the Delaware Act"
```

Use exact `lookup` for a known citation. Use ordinary `search` for keywords or broad legal topics.

For a document review, run the whole file through validation first. Do not validate citations one by one unless you are doing follow-up checks:

```bash
python3 -m delaware_law_skill.cli review --file "/path/to/document.docx"
python3 -m delaware_law_skill.cli validate --file "/path/to/document.docx"
python3 -m delaware_law_skill.cli validate --file "/path/to/document.md"
```

If you are not already in the project root, use:

```bash
cd "C:\Users\黄钰纯\.claude\skills\delaware-law-skill"
```

## Coverage

The first data pack covers only:

- Delaware Constitution
- Delaware Code Title 1-31
- Selected Delaware Court Rules

Delaware Administrative Code is covered through the official online source as `regulation_current`, but it is not bundled into the main data pack. Use:

```bash
python3 -m delaware_law_skill.cli admin-refresh-index --title 24
python3 -m delaware_law_skill.cli admin-search "24 DE Admin. Code 3900" --title 24
python3 -m delaware_law_skill.cli admin-lookup "24 DE Admin. Code 3900"
```

The Administrative Code workflow first indexes official entries, then lazy-fetches one official PDF only when a specific regulation is needed. Do not guess `/api/AdminCode/` UUIDs. The UUID must come from the official Delaware Regulations site/API.

It does not cover opinions, cases, secondary sources, Westlaw, Lexis, Bloomberg Law, or other paid legal databases.

If the user asks for material outside coverage, say clearly that the current data pack does not cover it. Do not present outside material as verified by this skill.

## Required output behavior

When using Delaware legal materials, include:

- the matched citation
- the section heading
- the source URL
- the data pack version
- any coverage warning

For Delaware Administrative Code, include:

- the `DE Admin. Code` citation
- the official regulation page URL
- the official PDF/API URL when available
- `last_checked_at`
- cache `fetched_at`
- content hash/version information

For document reviews, organize the final answer in these seven groups:

1. 明显错误
2. 引用太宽泛
3. 需要查外部材料
4. 本地数据库没查到
5. 可能影响结论的相关法律
6. 已确认正确的引用
7. 本工具未覆盖的内容

Default response style:

- explain in Chinese when the user writes in Chinese
- include the relevant English legal text when quoting a statute
- state that this is citation/material verification, not legal advice

## Citation review behavior

For citation validation, use the CLI `validate` command before giving conclusions.

Treat these as high-priority warnings:

- A cited section exists, but the topic appears mismatched.
- A citation is not found in the local data pack; say the local database did not detect it, not that the law does not exist.
- A citation appears to be federal or from another state.
- The text refers to regulations, opinions, or cases.
- Court rule references should be checked locally when they fall within the selected Delaware court rules data pack.
- If a requested court rule is not found, say the current selected court rules data pack did not detect it; do not say the rule does not exist.
- Delaware Administrative Code can be cited as current regulation only when the official PDF/text was fetched or a fresh cache exists. If only the index matched, say only that a possibly relevant official entry was found.
- If citing cached Administrative Code text, state when it was fetched. If the cache is expired and refresh failed, say that the latest official version could not be confirmed.
- Do not treat Delaware Register proposed regulations as current law. The Register is only for future update checking unless a final/effective status is separately verified.
- A reference is only to an entire Title or Chapter. Treat found Chapter references as real but usually too broad for a concrete legal conclusion.
- UCC concept references such as `Article 2`, `Article 9`, and `perfection` may be implicit legal references and should be checked against the local tool.

Known first-version examples:

- `§ 17-406` exists, but it is not the professional reliance section; check `6 Del. C. § 17-407`.
- `§ 17-607(b)` is limited partner return liability; it is not an asset-to-liability ratio test. The distribution limitation is in `§ 17-607(a)`.
- `8 Del. C. § 262` exists and covers appraisal rights.
- `Title 6, Chapter 12C` exists and is Online and Personal Privacy Protection. For a specific online privacy policy obligation, check `6 Del. C. § 1205C`.
- Underground utility damage prevention belongs in `26 Del. C. ch. 8`; `26 Del. C. § 801` is Purpose; citation; construction. Do not label it Title 26 Chapter 12.
- Delaware public records / Delaware public body FOIA issues should start with `29 Del. C. ch. 100`, especially `29 Del. C. § 10003`; do not drift to federal FOIA unless the document truly concerns federal agencies.
- Public works bid/performance/payment bond issues should check Title 29 procurement rules, especially `29 Del. C. § 6927`, `§ 6961`, and `§ 6962`, not only Title 18 insurance law.
- For Title 7 environmental issues, say the Delaware Code is covered but DNREC regulations, Delaware Administrative Code, local ordinances, and administrative policy are outside this data pack.
- For computer crime / unauthorized access, `11 Del. C. § 932` is not enough by itself; check `§§ 932-938`, penalties in `§ 939`, and venue in `§ 940`.
- `Article 2 governs perfection` is likely mismatched: Article 2 is sales, while perfection/security interests usually start with UCC Article 9.
- `warranty disclaimer`, `merchantability`, and `implied warranty` should check `6 Del. C. § 2-316`, `§ 2-314`, and `§ 2-315`.
- Health-care telehealth should start with `24 Del. C. ch. 60`, especially `§ 6002` and `§ 6004`; `24 Del. C. § 3920` is social-work specific and should not be treated as a universal telehealth rule.
- Professional licensing under Title 24 must be mapped by profession: pharmacy ch. 25, medicine ch. 17, nursing ch. 19, mental health/counseling ch. 30, psychology ch. 35, social work ch. 39.
- HIPAA, FERPA, DEA, FDA, Medicare, and Medicaid are federal/outside materials; do not present them as verified by this local data pack.
- Good Samaritan / emergency immunity should be searched through related immunity terms, including `10 Del. C. § 8135` and `16 Del. C. § 4769`, rather than treated as not found solely because the phrase does not match.
