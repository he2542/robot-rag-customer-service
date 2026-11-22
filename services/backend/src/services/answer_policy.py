"""Source-ID validation and explicit prohibited-action checks."""
import re
import json


_SOURCE_GROUP = re.compile(r"\[([^\]\n]*)\]")
_ACTION = re.compile(
    r"(?:插拔|拔出|拔下|拔掉|重新连接|重新安装).{0,5}电池"
    r"|(?:检查|检测|拆卸|拆解|拆开|润滑|加油|滴加).{0,12}(?:电机|轴承|排线|内部电路)"
    r"|(?:电机|轴承).{0,12}(?:滴加|润滑油|加油)"
    r"|(?:轻拉|拉扯|拔插|插拔).{0,8}(?:排线|连接处|内部电线)"
    r"|(?:关闭|禁用|绕过).{0,8}(?:碰撞保护|安全保护|防跌落)"
)
_BOUNDARY = re.compile(r"不要|不可|不得|不能|不建议|请勿|切勿|禁止|交给|交由|专业人员|专业售后|联系.{0,5}售后")

SAFETY_ANSWER = "涉及内部电机、排线、电池连接或安全保护的检查与处理，请停止相关操作并联系专业售后，不要自行拆修或继续测试。"
UNSUPPORTED_ANSWER = "当前无法提供有可靠证据支持的结论。请补充具体型号和故障现象，必要时联系对应品牌售后。"
_NEGATION = re.compile(r"不要|不可|不得|不能|不建议|请勿|切勿|禁止")
_ELECTRICAL_SYMPTOM = re.compile(r"电池.{0,6}(?:故障|异常|报警)|烫手|烫得|异常发热|发热严重|(?:开机|一开机).{0,12}报警|潮湿.{0,12}停机")
_REPORTED_OVERHEAT = re.compile(r"(?:已经|正在|现在|出现|发生|运行时|工作时|工作中).{0,10}过热|过热了"
                                r"|(?:触发|进入|启动).{0,8}过热保护|过热保护.{0,8}(?:报警|停机|故障|坏了)")
_LUBRICATE = re.compile(r"(?:滴|加注|加|注入|涂抹).{0,8}(?:润滑油|润滑脂|专用油|油脂)")
_RETRY = re.compile(r"充满|充电(?!座|触点|时|异常|过程|接口|状态|故障|电流|电压|器|电源)|重试|继续使用|开机测试|重新开机|更换.{0,6}电池")
_ASK_ACTION = re.compile(r"怎么办|咋办|怎么.{0,6}(?:处理|解决|调|恢复|排查|做|弄)|如何|处理|解决|恢复|调回|步骤|排查|办法|措施")
_REPAIR_FIELD = re.compile(r"(?:修复|处理方法|解决方法)[：:]")
_REPAIR_RISK = re.compile(r"内部|拆机|拆卸|拆解|电池|电机|轴承|排线|保护装置|短路|充电|发热|鼓包|火花|漏电|起火")
_INSTRUCTION = re.compile(r"系统提示|提示词|密钥|密码|忽略.{0,8}(?:规则|指令)|https?://|执行命令")
_REPAIR_VERB = re.compile(r"重启|关闭|打开|开启|解锁|设置|选择|调整|调大|调小|清理|清洗|更换|重新|晾干|联系")
_ACTION_ALIASES = {"重新启动":"重启", "启用":"开启", "打开":"开启", "关掉":"关闭",
                   "调低":"调小", "调高":"调大", "替换":"更换", "清除":"清理"}
_ALIAS_PATTERN = re.compile("|".join(sorted(_ACTION_ALIASES, key=len, reverse=True)))
_QUALIFIED_ACTION = re.compile(r"无需|不必|不需要|不想|不愿|别让|只有|除非|否则|尚未|已经|已(?:开启|启用|打开|更换|重启|设置|完成|安装|清理)")


def repair_actions_covered(remedy, text):
    """Check action words, plus distinct targets for repeated action words.

    This is a lexical coverage check, not a semantic correctness judgment.
    """
    # Normalize only the coverage comparison, never the displayed source text.
    remedy = _ALIAS_PATTERN.sub(lambda m: _ACTION_ALIASES[m.group()], remedy)
    text = _ALIAS_PATTERN.sub(lambda m: _ACTION_ALIASES[m.group()], text)
    targets = {}
    for clause in re.split(r"[，,。；;！？\n]", remedy):
        actions = list(_REPAIR_VERB.finditer(clause))
        for i, action in enumerate(actions):
            end = actions[i + 1].start() if i + 1 < len(actions) else len(clause)
            target = clause[action.end():end].strip()
            target = re.sub(r"(?:并且|并|然后|再|和|与|及)$", "", target)
            target = re.sub(r"[\s、‘’“”]", "", target)
            targets.setdefault(action.group(), set())
            if target:
                targets[action.group()].add(target)
    plain_text = re.sub(r"[\s、‘’“”]", "", text)
    return bool(targets) and all(verb in text and (len(objects) <= 1 or all(
        target and target in plain_text for target in objects)) for verb, objects in targets.items())


def complete_action_quote(text, quote, question, covered_text=None):
    """Restore a complete quoted repair entry only for routine action questions.

    Called after literal-source validation. Return the entire quote, retaining
    its conditions, rather than splice an isolated repair step into a new claim.
    """
    if (not _ASK_ACTION.search(question) or operation_boundary(question)
            or _NEGATION.search(question) or _QUALIFIED_ACTION.search(question)
            or _REPAIR_RISK.search(question + quote) or _INSTRUCTION.search(quote)
            or _positive_actions(quote, _ACTION) or not quote.rstrip().endswith(("。", "！", "？"))):
        return text
    if len(re.findall(r"(?m)^\s*\d+[.、]", quote)) > 1:
        return text
    repairs = list(_REPAIR_FIELD.finditer(quote))
    structured = (len(repairs) == 1 and "故障现象" in quote and "检测" in quote
                  and bool(quote[repairs[0].end():].strip(" 。")))
    conditional = not repairs and bool(re.search(r"若[^。！？\n]+[，,]可", quote))
    if not (structured or conditional):
        return text
    remedy = quote[repairs[0].end():] if structured else quote[quote.index("若"):]
    covered = text if covered_text is None else covered_text
    if (not _REPAIR_VERB.search(remedy) or repair_actions_covered(remedy, covered)
            or _NEGATION.search(covered) or _QUALIFIED_ACTION.search(covered)):
        return text
    # Preserve any conditions introduced in the claim as well as in the quote.
    condition = re.search(r"如果|若|仅限|仅在|当|型号|适用于", covered)
    if condition and covered[condition.start():].strip() not in quote:
        return text
    return re.sub(r"^\s*\d+[.、]\s*", "", quote.strip())


def electrical_symptom(question):
    if _ELECTRICAL_SYMPTOM.search(question) or _REPORTED_OVERHEAT.search(question):
        return True
    # A protection feature alone does not report an active overheating fault.
    return '过热' in question and not re.search(r'过热.{0,16}保护|保护.{0,16}过热',question)


def unsafe_lubrication(text):
    # Carry the named component across commas/semicolons within one sentence.
    # A later warning does not authorize an earlier user operation.
    for sentence in re.split(r'[。！？\n]',text):
        internal_target=False
        for clause in re.split(r'[，,；;]|但|而是|而应',sentence):
            if re.search(r'电机|轴承',clause):
                internal_target=True
            action=_LUBRICATE.search(clause)
            if internal_target and action:
                prefix=clause[:action.start()]
                professional=re.search(r'(?:专业售后|专业人员|售后人员|售后工程师).{0,10}$',prefix)
                if not _NEGATION.search(prefix) and not professional:
                    return True
    return False


def operation_boundary(question):
    if electrical_symptom(question):
        return "请先停止使用和充电，联系专业售后；不要自行拆修或继续通电测试。"
    if re.search(r"电线|排线", question) and re.search(r"安全|注意|检查|保养|维护|损坏|破损|松动|看看", question):
        return "先断电，仅目视检查无需拆机即可看到的外露电源线；内部排线和插接件的检查交由专业售后，不要拉扯、插拔或自行拆机。"
    if re.search(r"电机.{0,15}(?:响|故障|异常|卡顿)|轴承.{0,12}(?:保养|润滑|卡顿|检查)|(?:检查|检测|维修|拆).{0,8}(?:电机|轴承)|拖布.{0,12}(?:咔咔|异响|怪声)", question):
        return "请先停止异常运行；内部电机、轴承的检查由专业售后执行，不要自行拆修或润滑。"
    return ""


def _positive_actions(text, pattern):
    return [m for clause in re.split(r"[，,。；;！？\n]", text) if not _NEGATION.search(clause)
            for m in pattern.finditer(clause)]


def quote_in_source(quote, source):
    # Only presentation differences: no punctuation, numbers, words or negations
    # are removed. A copied subclause may acquire a Markdown list marker.
    def plain(value):
        value = re.sub(r"(?m)^\s*[-*]\s+", "", value.replace("**", ""))
        return re.sub(r"\s+", " ", value).strip()
    canonical = plain(quote)
    return len(canonical) >= 6 and (quote in source or canonical in plain(source))


def verified_claim_entries(claims, references, question):
    """Recover only separately located complete numbered source lines.

    The generated merged assertion is discarded; source conditions are copied.
    """
    def plain(line):
        return re.sub(r'\s+',' ',line.replace('**','')).strip()
    for claim in claims:
        if not isinstance(claim,dict):
            continue
        text,quote=claim.get('text'),claim.get('quote')
        if (not isinstance(text,str) or not text.strip() or len(text)>4000
                or not isinstance(quote,str) or not 6<=len(quote.strip())<=400):
            continue
        if any(quote_in_source(quote.strip(),s['excerpt']) for s in references):
            yield {'text':text,'quote':quote,'extractive':False}
            continue
        # Restriction questions benefit from separate original conditions. Do
        # not add procedures to troubleshooting answers from stitched quotes.
        if not re.search(r'使用限制|哪些限制|什么限制|注意事项|适用条件|使用要求|维护.{0,8}要求',question):
            continue
        lines=quote.strip().splitlines()
        if not 2<=len(lines)<=4:
            continue
        recovered=[]
        for line in lines:
            if not re.fullmatch(r'\d+[.、]\s*\S[^\n]*[。！？]',line.strip()):
                break
            matches=[s for s in references if any(plain(line)==plain(original) for original in s['excerpt'].splitlines())]
            if len(matches)!=1:
                break
            original=next(original for original in matches[0]['excerpt'].splitlines() if plain(line)==plain(original))
            recovered.append({'text':re.sub(r'^\s*\d+[.、]\s*','',original),'quote':original,'extractive':True})
        else:
            yield from recovered


def normalize_citations(text, allowed):
    def replace(match):
        body = match.group(1).strip()
        if not re.search(r"S\s*\d|^\d", body, re.I):
            return match.group(0)
        ids = re.split(r"\s*[,，、]\s*", body)
        if all(re.fullmatch(r"S\d+", item) and item in allowed for item in ids):
            return "".join(f"[{item}]" for item in dict.fromkeys(ids))
        return ""
    text = _SOURCE_GROUP.sub(replace, text)
    text = re.sub(r"(?<![A-Za-z0-9])S\d+[-－]\d+", "", text)
    return re.sub(r"\[[^\]\n]*S\s*\d[^\]\n]*$", "", text)


def finalize_answer(text, allowed):
    # A later disclaimer cannot undo an earlier explicit action recommendation.
    if unsafe_lubrication(text):
        return SAFETY_ANSWER
    for clause in re.split(r"[，,。；;！？\n]", text):
        if _ACTION.search(clause) and not _BOUNDARY.search(clause):
            return SAFETY_ANSWER
    cleaned = normalize_citations(text, allowed).strip()
    if not cleaned:
        return UNSUPPORTED_ANSWER
    cited = re.findall(r"\[(S\d+)\]", cleaned)
    clarification = re.search(r"不足以确认|无法确认|资料不足|请补充|请提供|请确认|请问|[?？]$", cleaned)
    return cleaned if cited or clarification else UNSUPPORTED_ANSWER


def render_context_answer(raw, references, question=""):
    """Locate literal supporting quotes and allocate citations in application code."""
    references = references if isinstance(references, list) else []
    allowed = {item["id"] for item in references}
    boundary = operation_boundary(question)
    def with_boundary(answer):
        return boundary + "\n\n" + answer if boundary and boundary not in answer else answer
    try:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        value = json.loads(text)
        if not isinstance(value, dict):
            return UNSUPPORTED_ANSWER
        decision = value.get("decision")
        if decision == "refer":
            return with_boundary("请联系专业售后，不要自行拆解、检查内部部件或绕过保护装置。")
        if decision == "insufficient":
            return with_boundary("当前知识库不足以确认。请补充具体型号和问题细节，或查看对应型号官方说明。")
        if decision == "clarify":
            question = value.get("question")
            if not isinstance(question, str) or not question.strip() or len(question) > 250:
                return UNSUPPORTED_ANSWER
            return with_boundary(finalize_answer(question.strip(), set())) if re.search(r"[?？]|请提供|请补充|请确认|请问", question) else with_boundary(UNSUPPORTED_ANSWER)
        claims = value.get("claims")
        if decision not in {"answer", "conflict"} or not isinstance(claims, list) or not 1 <= len(claims) <= 20:
            return UNSUPPORTED_ANSWER
        paragraphs, safety_rejected, recovered_used = [], False, False
        for claim in verified_claim_entries(claims,references,question):
            if not isinstance(claim, dict):
                continue
            text, quote = claim.get("text"), claim.get("quote")
            if (not isinstance(text, str) or not text.strip() or len(text) > 4000
                    or not isinstance(quote, str) or not 6 <= len(quote.strip()) <= 400):
                continue
            matches = [item["id"] for item in references if quote_in_source(quote.strip(), item["excerpt"])]
            if not matches:
                continue
            if claim['extractive'] and (_positive_actions(text,re.compile(r'拆卸|拆解|拆机|拆开|拉扯|插拔'))
                                        or _positive_actions(text,_LUBRICATE) or unsafe_lubrication(text)):
                safety_rejected=True
                continue
            if decision == "answer" and not claim['extractive']:
                covered_text = "\n".join(c["text"] for c in claims if isinstance(c, dict)
                                         and c.get("quote") == quote and isinstance(c.get("text"), str))
                text = complete_action_quote(text, quote, question, covered_text)
            # Ignore embedded citation syntax; only the separately validated IDs count.
            clean = re.sub(r"\[[^\]\n]*S\s*\d[^\]\n]*\]", "", text)
            clean = re.sub(r"(?<![A-Za-z0-9])S\d+[-－]\d+", "", clean).strip()
            if electrical_symptom(question) and _positive_actions(clean, _RETRY):
                # Keep only an independently stated cause, never charging/retry steps.
                clean = "；".join(part for part in re.split(r"[；;。]", clean)
                                 if re.search(r"可能|原因|导致", part)
                                 and not _positive_actions(part, _RETRY) and not _positive_actions(part, _ACTION)).strip()
                safety_rejected = True
                if not clean:
                    continue
            candidate = finalize_answer(clean + " " + f"[{matches[0]}]", allowed)
            if candidate == SAFETY_ANSWER:
                actions = _positive_actions(clean, _ACTION)
                if actions and all(m.group().startswith(("检查", "检测")) for m in actions) and not unsafe_lubrication(clean):
                    paragraphs.append("专业售后检查项：" + clean + f" [{matches[0]}]")
                else:
                    safety_rejected = True
            elif candidate != UNSUPPORTED_ANSWER:
                paragraphs.append(candidate)
                recovered_used = recovered_used or claim['extractive']
        if not paragraphs:
            return with_boundary(SAFETY_ANSWER if safety_rejected else UNSUPPORTED_ANSWER)
        paragraphs = list(dict.fromkeys(paragraphs))
        if safety_rejected:
            paragraphs.append(SAFETY_ANSWER)
        prefix = "资料中的适用条件或说明存在差异：\n\n" if decision == "conflict" else ""
        if recovered_used and not prefix:
            prefix="部分内容按资料原文分别列出，请保留各自适用条件：\n\n"
        return with_boundary(prefix + "\n\n".join(paragraphs))
    except (ValueError, TypeError):
        return UNSUPPORTED_ANSWER
