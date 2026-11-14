# DistillGuard · 蒸馏护栏

> 在蒸馏之前，决定什么可以被提取。

给"人格提取"这类工具加一道闸门：**先判断什么材料可以进去，再让蒸馏工具开工。**

它不绑定具体实现：命令行蒸馏工具、[distilly](https://github.com/titanwings/distilly)（原同事.skill）
这类 agent skill、自己写的脚本、内部流水线，都能接。

---

## 它解决什么问题

现有的合规工具基本都在管"数据能不能用"，提取这件事却卡在三个更具体的地方：

| 缺口 | 表现 | 本工具怎么处理 |
|---|---|---|
| **命名错位** | 规则里没有"提取"的位置。要求写判断依据，却不给判断以规范地位 | 按三层边界给每份材料归类，无法归类的按禁止处理 |
| **同意错位** | 同意在离职谈判期间签署，用"整理上交"替代授权请求，一条概括条款覆盖一切 | 五项实质要件逐条检查，概括用语直接打回 |
| **时间错位** | 劳动关系有终点，技能包没有。删除义务缺位 | 出厂前强制写有效期、删除义务、退出通道与审计留痕 |

它同时会输出一份**合规表演红旗清单**：概括性授权、压力峰值签署、无退出、无期限、对价未单列。
这一块是它和"帮你生成一份好看合规文件"的工具的分界线。

---

## 核心设计：闸门不是提醒，是物理入口

一个 skill 没法拦截另一个 skill 读文件。所以本工具不靠"提醒模型注意"，而是改变输入结构：

```
raw/  ──[gate]──>  approved/   ──>  蒸馏工具只读这里
                     │
                     └──> blocked.json（每条被拦下的材料与理由）
```

被拦下的材料**不会出现在 approved/ 里**，因此不可能被蒸馏读进去。合规不是一句承诺，
而是 `blocked.json` 里可以逐条核查的事实。

---

## 快速开始

需要 Python 3.9+ 与 PyYAML：

```bash
pip install pyyaml
```

仓库自带四个案例，直接跑：

```bash
# 1. 正常放行
python scripts/guard.py gate --manifest examples/case_pass/materials.yaml \
    --src examples/case_pass/raw --out examples/case_pass/run
# 入库闸：共 2 份材料，放行 2，挂起 0，拦截 0

# 2. 判断偏好 + 要件齐全的单独同意
python scripts/guard.py gate --manifest examples/case_consent/materials.yaml \
    --src examples/case_consent/raw --out examples/case_consent/run

# 3. 含第三人表达与私人内容
python scripts/guard.py gate --manifest examples/case_block/materials.yaml \
    --src examples/case_block/raw --out examples/case_block/run
# 入库闸：共 3 份材料，放行 1，挂起 0，拦截 2

# 4. 概括授权 + 离职期签署 + 无退出（最常见的真实场景）
python scripts/guard.py gate --manifest examples/case_pending/materials.yaml \
    --src examples/case_pending/raw --out examples/case_pending/run
# 入库闸：共 1 份材料，放行 0，挂起 1，拦截 0

# 5. 申报"无第三人"，正文里有手机号与邮箱
python scripts/guard.py gate --manifest examples/case_scan/materials.yaml \
    --src examples/case_scan/raw --out examples/case_scan/run

# 6. 同意要件齐全，但对话里有第二个说话人
python scripts/guard.py gate --manifest examples/case_speaker/materials.yaml \
    --src examples/case_speaker/raw --out examples/case_speaker/run

# 7. 两份材料单独看都无害，拼起来能定位到人
python scripts/guard.py gate --manifest examples/case_qi/materials.yaml \
    --src examples/case_qi/raw --out examples/case_qi/run
```

出厂与核查：

```bash
python scripts/guard.py seal  --run examples/case_consent/run \
    --package examples/case_consent/skill_package
python scripts/guard.py audit --run examples/case_consent/run \
    --package examples/case_consent/skill_package
```

退出码：`0` 全部放行；`2` 存在被拦截项；`3` 存在授权缺口或出厂条件不满足。

---

## 申报引导员（可选）

清单要人填，但多数人不知道该申报什么。`guide.py` 把它变成三个问题：

```bash
# 1. 扫目录，出草稿与问卷
python scripts/guide.py survey --src raw --out guide

# 2. 答完写进 guide/answers.yaml，生成正式清单
python scripts/guide.py build --draft guide/draft.yaml \
    --answers guide/answers.yaml --out materials.yaml

# 3. 跑完闸门后，用大白话解释每条拦截
python scripts/guide.py explain --run run
```

三个问题：

1. 这份材料是谁写的？（只有我／只有别人／我和别人都有）
2. 里面有没有别人的话、姓名、联系方式或隐私？（有／没有／不确定）
3. 这份材料主要是什么？（流程与公开资料／我个人的判断／私人内容）

三问正好对应三层边界。选"不确定"一律按含第三人处理，宁可多拦一次。

**边界**：引导员只写 `materials.yaml`，改不了闸门。它说的话不算数，闸门读的清单才算数——
人负责申报，规则负责判断，agent 负责沟通。

---

## 三道闸

### 入库闸（命名错位）

按顺序匹配，先命中先用：

| 层级 | 包含什么 | 处理 |
|---|---|---|
| **禁止提取** | 私人表达、他人隐私、可识别身份的表达习惯、当事人明确拒绝的部分 | 永不进入 approved |
| **需单独书面同意** | 个人判断偏好、沟通风格、优先级排序依据、非职务形成的个人方法论 | 五项要件齐全才放行 |
| **可提取** | 制度化流程、岗位说明书、已公开资料、与他人无关的操作方法 | 直接放行 |

命中不了任何一层，按禁止处理。

### 扫描交叉核对

清单由使用者申报，申报可能出错。工具会做四层交叉核对：

1. **联系方式**：手机号、邮箱、身份证号、QQ 号、微信号。
2. **观察名单**：`rules/watchlist.txt` 里的姓名。
3. **说话人结构**：解析 `我：` / `小王：` 这种行首结构，出现第二个说话人就说明含第三人表达——
   这是定义级的，不靠猜。同时把说话人和"老张""小王"这类称谓提成
   `watchlist_candidates.txt`，人工确认后写进观察名单，下次直接命中。
4. **准标识符组合**：清单用 `attributes` 申报每份材料含哪些属性（姓名、部门、工号、学校……），
   工具对整份语料取并集，凑齐 `rules/quasi_identifiers.yaml` 里的组合就报 RF-12。
   两份单独看都无害的材料，拼起来能定位到人，这种情况会被拦住。

扫描命中、而清单写的是 `contains_third_party: false`，判为**申报冲突**（RF-10 / RF-11）并拦截。

它不替代申报：命中不等于一定有问题，但"申报干净、正文里却有联系方式"这种情况必须停下来核对。
反过来，扫描没命中也不代表材料干净，最终仍以申报为准。

### 授权闸（同意错位）

单独同意必须同时满足五项：

1. 单独签署，不与其他条款合并
2. 明确用途、范围与期限
3. 时点自由，不在离职谈判与离职证明办理期间
4. 对价单独计列
5. 可撤回，且有可查验的退出通道

同意文本里出现"业务优化""管理提升""公司所有""不可撤销""永久授权""包括但不限于"等表述，
判为概括性授权，直接打回。

授权的到期时间会与当天比对，已过期的按挂起处理（RF-09），不会因为"文本齐全"就放行。

### 出厂闸（时间错位）

技能包出厂前必须写清：成分表（材料来源、类型、授权范围、到期时间）、有效期、删除义务、审计留痕。
有效期取各材料授权到期时间中最早的一个。有材料仍处于挂起状态，不予出厂。

### 水印与调用日志

`seal` 给每个包签发一个编号，例如 `DG-20261114-79F302CD`，写进 `audit.json` 与成分表，
并以零宽字符嵌在成分表末尾。`audit` 能把它读出来——包流出去以后，能追到是哪一次签发。

调用登记：

```bash
python scripts/guard.py log-call --package pkg --caller "研发部" --purpose "复盘查询"
```

登记时若晚于授权到期日，返回 3 并警告；`audit` 会把超期调用列为越界，返回 2。

这两样只能**追溯**，不能**阻止**：包是文本，发出去就管不住。但"哪次签发、谁在用、有没有超期"
能查到，比完全没有记录强。

### 出包核查

两层比对：

1. **哈希**：被拦下的材料原样出现在产出里，直接指名。
2. **文本重合度**：把产出里的文本与被拦截材料做 6-gram 比对，重合度 ≥ 60% 判为改写后混入。

第二层是为了对付"改几个字再塞进去"——这种情况哈希查不出来。

### 重复运行

每次 `gate` 都会重建 `approved/`，上一轮放行的材料不会被带到下一轮。这条很重要：
残留一份不该进的材料，整套机制就白做了。

---

## 材料清单怎么写

```yaml
materials:
  - id: M01
    path: 决策复盘.md              # 相对 --src 的路径
    type: note                     # process_doc/public/work_doc/note/chat/email/self_description/other
    author: self                   # self/other/mixed
    contains_third_party: false    # 是否含第三人的姓名、观点、隐私
    contains_personal_expression: false   # 是否含与工作无关的私人表达
    contains_identifiable_style: false    # 是否含可识别身份的表达习惯
    subject_refused: false         # 当事人是否明确拒绝
    consent: separate              # none/blanket/separate/not_applicable
    consent_terms: "……同意文本……"
    consent_at_exit_process: false # 是否在离职谈判期间取得
    consideration_listed: true     # 对价是否单独计列
    revocable: true                # 是否可撤回
    scope: 团队内部项目评估
    expiry: "2027-11-13"
```

清单由使用者填写，工具只做校验，不替使用者猜测某份材料是否含第三人信息。

---

## 怎么接入不同的蒸馏工具

三种接法，按下游形态选。

### 方式一：命令行工具 → wrapper

蒸馏是一个命令时，用 wrapper 包起来（下一节详述）。它管住工作目录、只给一个材料路径、
挂起时不启动。

### 方式二：agent / skill → 交接包

蒸馏由 Claude、Codex 这类 agent 按 SKILL.md 流程执行时：

```bash
python scripts/handoff.py --run run --out handoff --tool "你的工具名"
```

产出 `handoff/materials/`、`CONTRACT.md`、`POLICY.yaml`、`materials.json`。
把整个 `handoff/` 交给 agent，告诉它材料只在 `materials/`，按 `CONTRACT.md` 执行。
它读不到原始目录，不是因为它自觉，而是因为原始目录根本没交给它。

### 方式三：已有工具 → 写一个二十行的适配层

把 `materials/` 复制进下游期望的目录即可。以 distilly 为例，它的目录约定是
`colleagues/{slug}/knowledge/{docs,messages,emails}/`：

| 材料类型 | distilly 目录 |
|---|---|
| work_doc / process_doc / public / note / self_description | `knowledge/docs` |
| chat | `knowledge/messages` |
| email | `knowledge/emails` |

契约文件放到 `colleagues/{slug}/_guard/CONTRACT.md`。换别的工具，只是这张映射表变。

### 用 wrapper 把约束写死（推荐）

```bash
python scripts/run_guarded.py \
    --manifest materials.yaml --src raw \
    --workdir run --package pkg \
    -- python your_distiller.py --materials "$DISTILLGUARD_MATERIALS"
```

wrapper 保证三件事：

1. 下游进程的工作目录在 `run/` 里，**看不到 `raw/`**，相对路径 `raw/...` 直接失效；
2. 下游只拿到一个材料路径 `DISTILLGUARD_MATERIALS`，指向 `approved/`；
3. 存在挂起材料时，下游**根本不启动**。

**默认就会锁定原始目录**：运行期间把 `raw/` 改名，连绝对路径也断掉。要关掉用 `--no-lock`。

```bash
python scripts/run_guarded.py ... -- python examples/probe_raw.py
# probe_raw: 存在 = False
# probe_raw: 原始目录不可达，锁生效
# 原始目录已恢复：raw.locked-20261114-153628 -> raw
```

不加锁时同一个探针会读到 2 个文件并退出 10，wrapper 随即停止——这就是"提醒"和"约束"的区别。

要注意：同一个用户账号下，任何程序都能读这个用户能读的文件。锁只是让路径暂时消失，不是权限隔离；
真正隔离要用容器，只挂载 `approved/`。

如果进程被强杀、`raw` 停在改名状态，用 `recover` 还原：

```bash
python scripts/guard.py recover --src raw
```

用 `--allow-partial` 只提取放行部分时，建议同时给 `--reason`，理由会写进 `runlog.json` 备查。

`examples/mock_distill.py` 是一个假的蒸馏器，只从 `DISTILLGUARD_MATERIALS` 读材料，
用来演示整条链路——它代表"任意下游工具"，不是某个特定产品。

---

## 局限

- **第三人识别是结构化 + 规则，不是语义理解。** 聊天类靠说话人结构接近可靠；自由文本里的人名
  仍可能漏，只能靠观察名单与人工确认补。扫描没命中不代表干净。
- **准标识符只覆盖规则表里的组合。** 三段材料各出一个属性、单独看都无害的极端情况挡不住。
- **出场后只能追溯，不能阻止。** 水印与调用日志已实现，但它们记录的是"发生过什么"，
  不是"不许发生"。
- **不生成同意书。** 它检查同意，不替企业起草。
- **不判断法律效力。** 它标出缺口，效力由法务与司法判断。
- **不替代提取工具。** 它只决定输入边界。

---

## 测试

```bash
python -m unittest discover -s tests -v
```

25 个端到端用例，覆盖七个示例案例、申报引导、扫描冲突、说话人识别、准标识符组合、授权过期、
`approved/` 残留、改写后混入、锁目录恢复、交接包、水印与超期调用。CI 配置在 `.github/workflows/ci.yml`，
在 Python 3.9 与 3.12 上各跑一遍。

---

## 研究依据

规则来自研究报告《人格提取：离职场景的规范困境》：

- 三层边界与离职后义务：第四章表 7、表 12
- 同意的五项实质审查：第四章结论二
- 技能包有效期与成分表：第四章（一）3
- 清单被形式化的风险：第五章对方案本身的伦理反思（即本工具的"红旗"来源）

---

## 许可

MIT。规则文本与研究报告中的表述可自由引用，注明出处即可。
