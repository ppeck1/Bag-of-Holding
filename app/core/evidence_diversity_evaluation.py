"""Pure, explicitly judged evidence-diversity diagnostics.

No retrieval, database, policy decision, semantic label inference or runtime
integration occurs here. A reviewed claim map is bound to exact delivered text;
document concentration, repeated facts and missing/unknown evidence are separate.
The historical document-level evaluator remains an independent measurement.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import hashlib
import re
from typing import Any

SCHEMA_VERSION = 'boh.evidence-diversity.evaluation/v0.1'
CASE_KEYS = {'case_id','required_aspects','optional_aspects','evidence_judgments',
             'expects_no_answer','conflict_unresolved','passage_applicable'}
LABEL_KEYS = {'document_id','text_sha256','role','supports','policy_allowed'}
ROLES = {'direct','locator','context','irrelevant','unknown'}


class EvaluationError(ValueError):
    """The supplied measurement or its judgments cannot be trusted."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationError(message)


def _name(value: Any) -> bool:
    return isinstance(value,str) and bool(value.strip())


def validate_case(case: Mapping[str, Any]) -> None:
    """Validate explicit judgments without inventing relevance or authority."""
    _require(isinstance(case,Mapping) and set(case)==CASE_KEYS,'case fields')
    _require(_name(case['case_id']),'case identity')
    for key in ('expects_no_answer','conflict_unresolved','passage_applicable'):
        _require(type(case[key]) is bool,key+' must be boolean')
    for key in ('required_aspects','optional_aspects'):
        values=case[key]
        _require(isinstance(values,list) and all(_name(v) for v in values),'aspect list')
        _require(len(set(values))==len(values),'duplicate aspects')
    required=set(case['required_aspects']); optional=set(case['optional_aspects'])
    _require(not required & optional,'required/optional overlap')
    aspects=required|optional
    _require(not case['expects_no_answer'] or not aspects,'no-answer aspects')
    _require(case['passage_applicable'] or not aspects,'discovery aspects')
    judgments=case['evidence_judgments']
    _require(isinstance(judgments,Mapping),'evidence judgments')
    _require(case['passage_applicable'] or not judgments,'discovery passage judgments')
    for key,label in judgments.items():
        _require(_name(key) and isinstance(label,Mapping) and set(label)==LABEL_KEYS,'judgment fields')
        _require(_name(label['document_id']),'judgment document')
        digest=label['text_sha256']
        _require(isinstance(digest,str) and re.fullmatch('[a-f0-9]{64}',digest) is not None,'text digest')
        _require(isinstance(label['role'],str) and label['role'] in ROLES,'judgment role')
        _require(type(label['policy_allowed']) is bool,'judgment policy boolean')
        supports=label['supports']
        _require(isinstance(supports,Mapping) and set(supports)<=aspects,'undeclared supported aspect')
        _require(all(_name(v) for v in supports.values()),'claim anchor')
        if label['role'] in {'unknown','irrelevant','context'}:
            _require(not supports,'nonanswer/unknown support')
        if label['role']=='direct':
            _require(bool(supports),'direct evidence without a declared claim')


def score_evidence(case: Mapping[str, Any], observation: Mapping[str, Any], *, k: int = 5) -> dict[str, Any]:
    """Score judged delivered claims, never a whole document by association.

    Claim equivalence is supplied by reviewed labels, not inferred from anchors.
    Anchors only prove that those labels apply to this exact delivered variant.
    Unknown evidence contributes no verified gain and is reported explicitly.
    No combined quality/answerability verdict or independent-source score exists.
    """
    validate_case(case)
    _require(type(k) is int and 1<=k<=25,'k must be 1..25')
    _require(isinstance(observation,Mapping),'observation mapping')
    rows=observation.get('results')
    _require(isinstance(rows,list),'results list')
    boundary=observation.get('boundary_failures',[])
    _require(isinstance(boundary,list) and all(_name(v) for v in boundary),'boundary failure list')
    prefix=observation.get('prefix_stable')
    _require(prefix is None or type(prefix) is bool,'prefix boolean/null')
    judgments=case['evidence_judgments']
    # Validate all supplied rows so a malformed tail cannot disappear at k.
    for row in rows:
        _require(isinstance(row,Mapping),'result mapping')
        _require(_name(row.get('evidence_id')) and _name(row.get('document_id')),'result identity')
        _require(type(row.get('policy_allowed')) is bool,'result policy boolean')
        text=row.get('text')
        _require(isinstance(text,str) if case['passage_applicable'] else text is None,'delivered content shape')
        if not case['passage_applicable']:
            continue
        label=judgments.get(row['evidence_id'])
        if label is None:
            continue
        _require(row['document_id']==label['document_id'],'judged document changed')
        _require(hashlib.sha256(text.encode('utf-8')).hexdigest()==label['text_sha256'],'judged delivery changed')
        _require(all(anchor in text for anchor in label['supports'].values()),'judged claim absent from delivery')
    selected=rows[:k]
    failures=list(dict.fromkeys(boundary))
    doc_counts=Counter(row['document_id'] for row in selected)
    common={'schema_version':SCHEMA_VERSION,'case_id':case['case_id'],'k':k,'returned_slots':len(selected),
            'passage_applicable':case['passage_applicable'],'conflict_unresolved':case['conflict_unresolved'],
            'answer_authority_inferred':False,'independent_corroboration_inferred':False,'prefix_stable':prefix,
            'document_concentration_at_k':round(max(doc_counts.values())/len(selected),6) if selected else None,
            'unique_documents_at_k':len(doc_counts),
            'no_answer_false_positive':bool(case['expects_no_answer'] and selected)}
    if not case['passage_applicable']:
        if any(not row['policy_allowed'] for row in selected):
            failures.append('forbidden_evidence_exposed')
        return {**common,'assessment_status':'not_applicable','coverage_interpretation':'not_applicable',
                'required_aspect_coverage_at_k':None,'covered_required_aspects':None,'uncovered_required_aspects':None,
                'covered_optional_aspects':None,'new_aspects_by_rank':None,'repeated_aspects_by_rank':None,
                'redundant_slots':None,'partially_repeated_slots':None,'unknown_slots':None,
                'judged_slot_fraction':None,'redundancy_rate_over_judged_usable_slots':None,
                'discovery_result_count':len(selected),'boundary_failures':list(dict.fromkeys(failures))}
    seen=set(); identities=set(); texts=set(); new_by_rank=[]; repeated_by_rank=[]; slot_details=[]
    redundant=partial=unknown=judged=usable_judged=forbidden=contexts=irrelevant=locators=identity_repeat=text_repeat=0
    for rank,row in enumerate(selected,1):
        label=judgments.get(row['evidence_id'])
        role=label['role'] if label else 'unknown'
        allowed=row['policy_allowed'] and (label is None or label['policy_allowed'])
        identity=row['evidence_id']
        identity_repeat+=int(identity in identities); identities.add(identity)
        digest=hashlib.sha256(row['text'].encode('utf-8')).hexdigest()
        text_repeat+=int(digest in texts); texts.add(digest)
        is_judged=label is not None and role!='unknown'
        judged+=int(is_judged)
        unknown+=int(not is_judged)
        if not allowed:
            forbidden+=1
        usable_judged+=int(is_judged and allowed)
        supports=set(label['supports']) if is_judged and allowed else set()
        repeated=supports&seen; new=supports-seen; seen.update(new)
        is_redundant=bool(supports and not new)
        is_partial=bool(new and repeated)
        redundant+=int(is_redundant); partial+=int(is_partial)
        contexts+=int(allowed and role=='context')
        irrelevant+=int(allowed and role=='irrelevant')
        locators+=int(allowed and role=='locator')
        new_by_rank.append(sorted(new)); repeated_by_rank.append(sorted(repeated))
        slot_details.append({'rank':rank,'role':role,'judged':is_judged,'policy_allowed':bool(allowed),
                             'new_aspects':sorted(new),'repeated_aspects':sorted(repeated),
                             'wholly_redundant':is_redundant,'partially_repeated':is_partial})
    if forbidden:
        failures.append('forbidden_evidence_exposed')
    required=set(case['required_aspects']); optional=set(case['optional_aspects'])
    return {**common,'assessment_status':'partially_judged' if unknown else 'judged',
            'coverage_interpretation':'judged_lower_bound' if unknown else 'judged_aspects_only',
            'required_aspect_coverage_at_k':round(len(seen&required)/len(required),6) if required else None,
            'covered_required_aspects':sorted(seen&required),'uncovered_required_aspects':sorted(required-seen),
            'covered_optional_aspects':sorted(seen&optional),'new_aspects_by_rank':new_by_rank,
            'repeated_aspects_by_rank':repeated_by_rank,'redundant_slots':redundant,
            'partially_repeated_slots':partial,'unknown_slots':unknown,'forbidden_slots':forbidden,
            'nonanswer_context_slots':contexts,'irrelevant_slots':irrelevant,'locator_slots':locators,
            'duplicate_identity_slots':identity_repeat,'exact_text_repeat_slots':text_repeat,
            'judged_slot_fraction':round(judged/len(selected),6) if selected else None,
            'redundancy_rate_over_judged_usable_slots':round(redundant/usable_judged,6) if usable_judged else None,
            'slot_details':slot_details,'boundary_failures':list(dict.fromkeys(failures))}
