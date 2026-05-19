# delaware-law-validator

A local-first, distributable, and auditable Delaware legal material retrieval and citation validation tool.

## Positioning

This project is not a contract review tool and does not replace lawyer review.

Its role is narrower: it gives an AI agent a verification layer for Delaware legal materials. When a contract, memo, or draft mentions a Delaware statute, court rule, regulation, chapter, title, or citation, the agent should use this tool to check whether that legal material actually exists, whether it is within the current coverage, and whether it can be traced to an official source before relying on it.

The tool can say things like:

- a citation was found in the local data pack or official Delaware source
- a citation was not detected in the current database
- a reference is too broad for a specific legal conclusion
- a regulation was fetched from an official source and cached at a specific time
- a requested material is outside the current coverage

The tool should not be used to say that a contract is legally sufficient, commercially appropriate, enforceable, or complete. It verifies legal materials; it does not make the final legal judgment.

第一版覆盖：

- Delaware Constitution
- Delaware Code Title 1-31
- Selected Delaware Court Rules

第一版不覆盖：

- opinions / cases
- Westlaw、Lexis、Bloomberg Law 等付费法律数据库

Delaware Administrative Code 不打进主数据包。它通过官方站点建立轻量索引，并在需要某一条 regulation 正文时才按需抓取官方 PDF、抽取文字、缓存 30 天。

## Build data pack

```bash
python -m delaware_law_skill.cli build --source "/path/to/delaware/markdown/files"
python -m delaware_law_skill.cli build \
  --source "/path/to/delaware/code" \
  --court-rules-source "/path/to/court/rules/md"
```

## Use

```bash
python3 -m delaware_law_skill.cli lookup "6 Del. C. § 17-407"
python3 -m delaware_law_skill.cli lookup "Title 6, Chapter 12C"
python3 -m delaware_law_skill.cli lookup "Court of Chancery Rule 12(b)(6)"
python3 -m delaware_law_skill.cli lookup "D.R.E. 403"
python3 -m delaware_law_skill.cli search "limited partnership distribution"
python3 -m delaware_law_skill.cli validate "as permitted by Section 17-406 of the Delaware Act"
python3 -m delaware_law_skill.cli review "Professional reliance under 6 Del. C. § 17-406."
```

Delaware Administrative Code:

```bash
python3 -m delaware_law_skill.cli admin-refresh-index --title 24
python3 -m delaware_law_skill.cli admin-search "24 DE Admin. Code 3900" --title 24
python3 -m delaware_law_skill.cli admin-lookup "24 DE Admin. Code 3900"
python3 -m delaware_law_skill.cli admin-freshness 40
```

`admin-refresh-index` 只刷新索引，不全量下载 PDF。`admin-search` / `admin-lookup` 命中具体条目后，才通过 Delaware 官方接口解析 PDF UUID、下载单条 PDF、抽取正文并缓存。缓存默认 30 天；过期后会重新访问官方来源并比较 hash，hash 变化时保留旧版本。

Validate a document:

```bash
python3 -m delaware_law_skill.cli review --file "/path/to/document.docx"
python3 -m delaware_law_skill.cli validate --file "/path/to/document.md"
python3 -m delaware_law_skill.cli validate --file "/path/to/document.docx"
```

## Data files

Generated files live under `data/`:

- `delaware_law_data_vX.Y.Z.sqlite`
- `manifest.json`
- `coverage-report.json`
- `delaware_law_data_vX.Y.Z.sqlite.sha256`
- `raw_md/`
- `raw_court_rules/`
- `admin_code/` if the online Delaware Administrative Code index/cache has been used

GitHub repo should contain code and a small sample only. Full data packs should be published through GitHub Releases.

Create a release zip:

```bash
python3 scripts/package_release.py
```

## Important boundary

This tool retrieves and checks legal materials. It is not an official legal database, does not provide legal advice, and does not guarantee final legal conclusions. Formal delivery still requires checking official sources or lawyer review.

Delaware source layering:

- Delaware Code: statutory current law in the local data pack
- Delaware Administrative Code: `regulation_current`, official online index plus lazy PDF cache
- Laws of Delaware: session laws
- Bills & Resolutions: pending bills only, not current law
- Delaware Register of Regulations: regulatory update checking only, not mixed into current Administrative Code unless final/effective status is separately verified
