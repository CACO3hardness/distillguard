---
name: distillguard
description: >
  人格提取的合规闸门。在把离职同事的聊天记录、邮件、工作文档交给蒸馏工具
  （distilly、同事.skill，或任何自建的蒸馏脚本与 agent 流程）之前先过一遍材料，
  按三层边界分类，
  拦截含第三人表达与私人内容的部分，检查同意是否成立，并在产出端生成成分表、
  有效期与审计留痕。适用于：人格提取、技能包提取、同事.skill、distilly、
  离职交接、persona 蒸馏、work.md 生成、经验沉淀、知识交接。
metadata:
  version: "0.1.0"
  license: "MIT"
  companion: "distilly / colleague-skill"
---

# DistillGuard · 蒸馏护栏

本 skill 不负责提取，负责**决定什么可以进入提取**。

它解决的问题不是"数据合不合规"，而是提取这种行为的三个缺口：规则里没有它的位置（命名错位）、
同意在压力峰值上取得（同意错位）、劳动关系终止后技能包还在运行（时间错位）。

## 硬规则

1. **先过闸，再提取。** 任何材料进入蒸馏流程之前必须经过本 skill，产出 `approved/` 目录。
   蒸馏只允许读取 `approved/`。原始目录 `raw/` 不得直接作为输入。
2. **失败即拦截。** 字段缺失、判断不了、拿不准，一律按"禁止"处理并记录，不做放行推断。
3. **不得代填。** 材料清单由使用者填写，本 skill 只做校验与清点，不替使用者猜测某份材料是否含第三人信息。
4. **结论不等于许可。** 本 skill 输出的是风险提示与检查清单，不构成法律意见。

## 三道闸

| 闸门 | 对应缺口 | 命令 | 产出 |
|---|---|---|---|
| 入库闸 | 命名错位 | `guard.py gate` | `approved/`、`blocked.json`、`合规记录.md` |
| 授权闸 | 同意错位 | `guard.py gate`（内置） | 授权缺口清单 |
| 出厂闸 | 时间错位 | `guard.py seal` | `成分表.md`、`audit.json` |
| 出包核查 | 越界使用 | `guard.py audit` | 拦截材料是否混入产出 |

### 入库闸

按三层边界处理材料：

- **可提取**：制度化流程与标准、岗位说明书、已公开资料、与他人无关的操作方法 → 直接进入 `approved/`
- **需单独书面同意**：个人判断偏好、沟通风格、优先级排序依据、非职务形成的个人方法论 → 五项要件齐全才放行
- **禁止提取**：与工作无关的私人表达、他人隐私、可识别身份的表达习惯、当事人明确拒绝的部分 → 永不进入 `approved/`

含第三人表达的材料属于禁止层，不因"已脱敏"自动放行——必须先脱敏，再由使用者重新申报。

清单申报会与扫描结果交叉核对：正文里扫到手机号、邮箱、身份证号、QQ/微信号，
或命中 `rules/watchlist.txt` 的姓名，而清单写的是"不含第三人"，判为申报冲突并拦截（RF-10）。
此外还会解析 `我：` / `小王：` 这类说话人结构，出现第二个说话人即判 RF-11；
把说话人与"老张""小王"等称谓提成 `watchlist_candidates.txt` 供人工确认。
清单用 `attributes` 申报属性，拼起来能定位到人的组合判 RF-12。扫描只做交叉核对，不替使用者判断。

### 授权闸

单独同意必须同时满足五项，缺一项即挂起：

1. 单独签署，不与其他条款合并
2. 明确用途、范围与期限，不得概括
3. 取得时点不在离职谈判、离职证明办理、背景调查期间
4. 对价单独计列，不与工资奖金混同
5. 可撤回，且有可查验的退出通道

"业务优化""管理提升""公司所有""不可撤销""永久授权"这类表述判为概括性授权，打回重签。

### 出厂闸

技能包出厂前必须写清四件事，缺一件不予出厂：

1. **成分表**：材料来源、材料类型、授权范围、到期时间
2. **有效期**：到期即失效，续用需重新取得同意
3. **删除义务**：约定期限内删除个人痕迹，并提供可查验的确认方式
4. **审计留痕**：保存授权范围与调用记录，使越界使用可被识别

`seal` 同时签发一个编号（如 `DG-20261114-79F302CD`），写进 `audit.json` 与成分表，
并以零宽字符嵌入成分表末尾。调用方用 `guard.py log-call` 登记每次使用，
`audit` 会读出签发编号并标出超期调用。

## 快速开始

```bash
# 1. 写材料清单（见 examples/*/materials.yaml）
# 2. 过闸
python scripts/guard.py gate --manifest examples/case_block/materials.yaml \
    --src examples/case_block/raw --out examples/case_block/run

# 3. 出厂
python scripts/guard.py seal --run examples/case_block/run \
    --package examples/case_block/skill_package

# 4. 核查产出里是否混入被拦截的材料
python scripts/guard.py audit --run examples/case_block/run \
    --package examples/case_block/skill_package
```

清单不知道怎么填时，先用申报引导员：

```bash
python scripts/guide.py survey --src raw --out guide     # 出三个问题
python scripts/guide.py build --draft guide/draft.yaml \
    --answers guide/answers.yaml --out materials.yaml
python scripts/guide.py explain --run run                # 解释每条拦截
```

引导员只负责问与写清单，不参与判断；它写出的清单仍要经过同一套闸门。

如果下游是 agent 而不是命令，改用交接包：

```bash
python scripts/handoff.py --run examples/case_consent/run \
    --out examples/case_consent/handoff --tool "任意蒸馏工具"
```

产出 `materials/`、`CONTRACT.md`、`POLICY.yaml`、`materials.json`。把整个目录交给下游，
它读不到原始材料，因为原始目录不在包里。

## 强制约束（推荐）

单跑 `gate` 只保证产出了 `approved/`，下游是否真的只读这个目录，取决于调用方。
要把它变成代码约束，用 wrapper：

```bash
python scripts/run_guarded.py \
    --manifest examples/case_consent/materials.yaml \
    --src examples/case_consent/raw \
    --workdir examples/case_consent/run \
    --package examples/case_consent/skill_package \
    -- python examples/mock_distill.py --out ../skill_package
```

wrapper 把下游进程的工作目录放在 `run/`，只通过 `DISTILLGUARD_MATERIALS` 给出 `approved/` 的路径；
存在挂起材料时下游不会启动；默认在运行期间把原始目录改名，结束后自动恢复，要关掉用 `--no-lock`。

退出码：`0` 全部放行；`2` 存在被拦截项；`3` 存在授权缺口或出厂条件不满足。

## 材料清单字段

| 字段 | 取值 | 说明 |
|---|---|---|
| `id` | 字符串 | 材料编号，如 `M01` |
| `path` | 相对路径 | 相对 `--src` 的路径 |
| `type` | `process_doc` / `public` / `work_doc` / `note` / `chat` / `email` / `self_description` / `other` | 材料类型 |
| `author` | `self` / `other` / `mixed` | 谁产出的 |
| `contains_third_party` | 布尔 | 是否含第三人的姓名、观点、隐私或可反推身份的内容 |
| `contains_personal_expression` | 布尔 | 是否含与工作无关的私人表达 |
| `contains_identifiable_style` | 布尔 | 是否含可识别或复现特定个人身份的表达习惯 |
| `subject_refused` | 布尔 | 当事人是否明确拒绝交出 |
| `consent` | `none` / `blanket` / `separate` / `not_applicable` | 授权形态 |
| `consent_terms` | 字符串 | 同意文本摘录，用于概括授权识别 |
| `consent_at_exit_process` | 布尔 | 是否在离职谈判或离职证明办理期间取得 |
| `consideration_listed` | 布尔 | 对价是否单独计列 |
| `revocable` | 布尔 | 是否可撤回且有退出通道 |
| `scope` / `expiry` | 字符串 | 授权范围与到期时间 |

## 不做什么

- **不做自动第三人识别**。文本里的姓名、账号只能靠模式扫描提示，最终以清单申报为准；拿不准就拦截。
- **不生成同意书**。它检查同意，不替企业起草。
- **不判断法律效力**。它标出缺口，效力由法务与司法判断。
- **不替代提取工具**。它只产出 `approved/`，提取仍由 distilly 等工具完成。

## 研究依据

本 skill 的规则来自研究报告《人格提取：离职场景的规范困境》：
三层边界与离职后义务见报告第四章表 7、表 12；同意五项实质审查见第四章结论二；
时间错位的两项具体设计（技能包有效期、随调用显示的成分表）见第四章（一）3。
